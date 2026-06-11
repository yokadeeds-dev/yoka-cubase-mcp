"""Sync-Job: Cubase Vst*Plug*Info-XMLs -> yoka_plugins.json.

Liest Cubase's native Plugin-Datenbanken (deutlich reicher als der
Plug-in Manager Report) und merged sie in die Nicker-Plugin-Registry:

    %APPDATA%/Steinberg/Cubase 15_64/VstPlugInfoV4.xml          (VST3, ~465 Eintraege)
    %APPDATA%/Steinberg/Cubase 15_64/Vst2xPlugin Infos Cubase.xml (VST2)

Liefert pro Plugin technische Felder, die der Report nicht hat:
    uid (VST3) / cid (VST2)  — Primary Key fuer Merge
    Number of Input/Output Busses
    Input/Output Speaker Arrangement
    Latency (samples)
    Side chain input busses (VST3)
    Flags (VST3 — Rohwert; Bit-Semantik undokumentiert, siehe NOTE_FLAGS unten)

Merge-Regel (UID als Primary Key, Name als Fallback):
    - Existiert UID in Registry  -> UPDATE: technische Felder refreshed,
                                    handgepflegte Felder (vendor/type/version
                                    aus Report + Tags aus plugin_tags.json)
                                    bleiben unangetastet.
    - Existiert UID NICHT, aber Name match -> als UID-Annotation (Backfill).
    - Neuer UID, neuer Name      -> ADD (mit nur technischen Feldern;
                                    vendor/type bleiben "" bis Plug-in Report
                                    neu eingelesen wird).
    - Registry-Plugin nicht im XML -> als "to_remove" reported, aber NIEMALS
                                    auto-geloescht. User entscheidet manuell.

Aufruf (Modul):
    from runtime.persona.cubase_plugin_sync import (
        compute_diff, apply_diff, default_xml_paths,
    )

CLI:
    python -m runtime.persona.cubase_plugin_sync --dry-run
    python -m runtime.persona.cubase_plugin_sync --apply

NOTE_FLAGS:
    Das `Flags`-Bitfeld in VstPlugInfoV4.xml ist Steinberg-intern und nicht
    oeffentlich dokumentiert. Beobachtungen aus dem Korpus:
        Omnisphere (Instrument)        : 13  (0b1101)
        VST Connect Monitor (Fx)       : 25  (0b11001)
        CurveEQ (Fx, alt)              : 0
        VST AmbiConverter (Fx)         : 0
    Eine saubere Bit-Dekodierung ohne SDK-Spec ist Raten. Wir persistieren
    den Rohwert; ein Decoder kann spaeter ergaenzt werden, sobald die
    Bit-Semantik durch externe Quelle bestaetigt ist.
"""

from __future__ import annotations

import json
import os
import shutil
import time
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


_KNOWLEDGE_DIR = Path(__file__).resolve().parent / "knowledge"
_REGISTRY_FILE = _KNOWLEDGE_DIR / "yoka_plugins.json"


# ---------- Defaults ----------

def default_xml_paths() -> dict[str, Path]:
    """Standard-Pfade fuer Cubase 15 auf Windows.

    Override via ENV CUBASE_VST3_XML / CUBASE_VST2_XML moeglich.
    """
    appdata = Path(os.environ.get("APPDATA", str(Path.home() / "AppData/Roaming")))
    base = appdata / "Steinberg" / "Cubase 15_64"
    return {
        "vst3": Path(os.environ.get("CUBASE_VST3_XML", str(base / "VstPlugInfoV4.xml"))),
        "vst2": Path(os.environ.get("CUBASE_VST2_XML", str(base / "Vst2xPlugin Infos Cubase.xml"))),
    }


# ---------- Datenklassen ----------

@dataclass
class XmlPluginEntry:
    """Ein Plugin wie es in der Cubase-XML steht.

    Felder die VST3 nur kennt: flags, sidechain_bus.
    Felder die VST2 nur kennt: sub_category, sdk_version, vendor_version, vendor.
    """
    uid: str                     # VST3 uid / VST2 cid
    name: str
    vst_format: str              # "VST3" | "VST2"
    in_bus: int = 0
    out_bus: int = 0
    in_arr: int = 0
    out_arr: int = 0
    latency: int = 0
    sidechain_bus: int | None = None  # VST3 nur
    flags: int | None = None          # VST3 nur (raw)
    sub_category: str | None = None   # VST2
    vendor: str | None = None         # VST2 liefert das mit
    sdk_version: str | None = None    # VST2
    vendor_version: str | None = None # VST2

    def to_cubase_tech(self) -> dict[str, Any]:
        """Subdict fuer plugin-record['cubase_tech']."""
        d: dict[str, Any] = {
            "in_bus": self.in_bus,
            "out_bus": self.out_bus,
            "in_arr": self.in_arr,
            "out_arr": self.out_arr,
            "latency": self.latency,
        }
        if self.sidechain_bus is not None:
            d["sidechain_bus"] = self.sidechain_bus
        if self.flags is not None:
            d["flags"] = self.flags
        if self.sub_category is not None:
            d["sub_category"] = self.sub_category
        return d


# ---------- Parser ----------

def _xml_int(obj: ET.Element, name: str, default: int = 0) -> int:
    el = obj.find(f"int[@name='{name}']")
    if el is None:
        return default
    try:
        return int(el.get("value", str(default)))
    except (TypeError, ValueError):
        return default


def _xml_str(obj: ET.Element, name: str) -> str | None:
    el = obj.find(f"string[@name='{name}']")
    if el is None:
        return None
    return el.get("value")


def parse_vst3_xml(path: Path) -> list[XmlPluginEntry]:
    """Parsed VstPlugInfoV4.xml -> Liste von XmlPluginEntry (vst_format='VST3')."""
    if not path.exists():
        return []
    tree = ET.parse(path)
    root = tree.getroot()
    entries: list[XmlPluginEntry] = []
    for obj in root.iter("obj"):
        if obj.get("class") != "VstPlugInfo":
            continue
        uid = _xml_str(obj, "uid") or ""
        name = _xml_str(obj, "name") or ""
        if not uid or not name:
            continue
        entries.append(XmlPluginEntry(
            uid=uid,
            name=name,
            vst_format="VST3",
            in_bus=_xml_int(obj, "Number of Input Busses"),
            out_bus=_xml_int(obj, "Number of Output Busses"),
            in_arr=_xml_int(obj, "Input Speaker Arrangement"),
            out_arr=_xml_int(obj, "Output Speaker Arrangement"),
            latency=_xml_int(obj, "Latency"),
            sidechain_bus=_xml_int(obj, "Side chain input busses"),
            flags=_xml_int(obj, "Flags"),
        ))
    return entries


def parse_vst2_xml(path: Path) -> list[XmlPluginEntry]:
    """Parsed Vst2xPlugin Infos Cubase.xml -> Liste von XmlPluginEntry (vst_format='VST2').

    VST2 hat keine Side-Chain-/Flags-Felder im XML; cid (32-hex) fungiert als UID.
    """
    if not path.exists():
        return []
    tree = ET.parse(path)
    root = tree.getroot()
    entries: list[XmlPluginEntry] = []
    for item in root.iter("item"):
        group_el = item.find("string[@name='Group']")
        if group_el is None:
            continue
        group_val = group_el.get("value", "")
        if not group_val.startswith("Vst2xPlug\\"):
            continue
        info = item.find(".//member[@name='Vst2xPlugInfo']")
        if info is None:
            continue
        cid = _xml_str(info, "cid") or ""
        name = _xml_str(info, "name") or ""
        if not cid or not name:
            continue
        entries.append(XmlPluginEntry(
            uid=cid,
            name=name,
            vst_format="VST2",
            in_bus=_xml_int(info, "audioInputBusCount"),
            out_bus=_xml_int(info, "audioOutputBusCount"),
            in_arr=_xml_int(info, "mainAudioInputArr"),
            out_arr=_xml_int(info, "mainAudioOutputArr"),
            latency=_xml_int(info, "latencySamples"),
            sidechain_bus=None,
            flags=None,
            sub_category=_xml_str(info, "subCategory"),
            vendor=_xml_str(info, "vendor"),
            sdk_version=_xml_str(info, "sdkVersion"),
            vendor_version=_xml_str(info, "vendorVersion"),
        ))
    return entries


# ---------- Diff / Merge ----------

@dataclass
class SyncDiff:
    to_add: list[dict[str, Any]] = field(default_factory=list)
    to_update: list[dict[str, Any]] = field(default_factory=list)
    to_remove: list[dict[str, Any]] = field(default_factory=list)
    unchanged_count: int = 0
    registry_count: int = 0
    xml_vst3_count: int = 0
    xml_vst2_count: int = 0

    def summary(self) -> dict[str, Any]:
        return {
            "registry_count": self.registry_count,
            "xml_vst3_count": self.xml_vst3_count,
            "xml_vst2_count": self.xml_vst2_count,
            "to_add": len(self.to_add),
            "to_update": len(self.to_update),
            "to_remove": len(self.to_remove),
            "unchanged": self.unchanged_count,
        }

    def to_dict(self) -> dict[str, Any]:
        return {
            "summary": self.summary(),
            "to_add": self.to_add,
            "to_update": self.to_update,
            "to_remove": self.to_remove,
        }


def _registry_index(registry: dict[str, Any]) -> tuple[dict[str, dict], dict[str, dict]]:
    """Indiziert Registry-Plugins nach UID und nach Name.

    Plugins ohne UID-Feld (alte Datensaetze) sind nur ueber Name auffindbar.
    """
    by_uid: dict[str, dict] = {}
    by_name: dict[str, dict] = {}
    for p in registry.get("plugins", []):
        if uid := p.get("uid"):
            by_uid[uid] = p
        if name := p.get("name"):
            by_name.setdefault(name, p)
    return by_uid, by_name


def _tech_equal(old: dict[str, Any] | None, new: dict[str, Any]) -> bool:
    if not old:
        return False
    keys = set(old) | set(new)
    for k in keys:
        if old.get(k) != new.get(k):
            return False
    return True


def compute_diff(
    registry: dict[str, Any],
    vst3_entries: list[XmlPluginEntry],
    vst2_entries: list[XmlPluginEntry],
) -> SyncDiff:
    """Vergleicht Registry mit XML-Inventar. Modifiziert `registry` nicht."""
    by_uid, by_name = _registry_index(registry)
    diff = SyncDiff(
        registry_count=len(registry.get("plugins", [])),
        xml_vst3_count=len(vst3_entries),
        xml_vst2_count=len(vst2_entries),
    )

    seen_uids: set[str] = set()
    seen_names: set[str] = set()

    for xml_p in (*vst3_entries, *vst2_entries):
        seen_uids.add(xml_p.uid)
        seen_names.add(xml_p.name)
        new_tech = xml_p.to_cubase_tech()

        existing = by_uid.get(xml_p.uid)
        match_strategy = "uid"
        if existing is None:
            existing = by_name.get(xml_p.name)
            match_strategy = "name_backfill" if existing is not None else "new"

        if existing is None:
            diff.to_add.append({
                "uid": xml_p.uid,
                "name": xml_p.name,
                "vst_format": xml_p.vst_format,
                "vendor": xml_p.vendor or "",
                "cubase_tech": new_tech,
                "_match": match_strategy,
            })
            continue

        changes: dict[str, Any] = {}
        if existing.get("uid") != xml_p.uid:
            changes["uid"] = (existing.get("uid"), xml_p.uid)
        if not _tech_equal(existing.get("cubase_tech"), new_tech):
            changes["cubase_tech"] = (existing.get("cubase_tech"), new_tech)

        if changes:
            diff.to_update.append({
                "uid": xml_p.uid,
                "name": xml_p.name,
                "match": match_strategy,
                "changes": changes,
            })
        else:
            diff.unchanged_count += 1

    for p in registry.get("plugins", []):
        uid = p.get("uid")
        name = p.get("name")
        in_xml = (uid and uid in seen_uids) or (name and name in seen_names)
        if not in_xml:
            diff.to_remove.append({
                "uid": uid,
                "name": name,
                "reason": "not in current Cubase XML (deinstalled / blocked / renamed?)",
            })

    return diff


def apply_diff(
    registry: dict[str, Any],
    diff: SyncDiff,
    remove_stale: bool = False,
) -> dict[str, Any]:
    """Wendet Diff auf eine *Kopie* der Registry an und gibt das Ergebnis zurueck.

    Handgepflegte Felder (alle ausser uid + cubase_tech) bleiben unveraendert.
    `remove_stale=True` entfernt to_remove-Eintraege physisch — Default False.
    """
    plugins = [dict(p) for p in registry.get("plugins", [])]
    by_uid = {p.get("uid"): p for p in plugins if p.get("uid")}
    by_name = {p.get("name"): p for p in plugins if p.get("name") and not p.get("uid")}

    for add in diff.to_add:
        plugins.append({
            "name": add["name"],
            "uid": add["uid"],
            "vendor": add.get("vendor", ""),
            "type": "",
            "version": "",
            "sdk_version": "",
            "architecture": "",
            "asio_guard": "",
            "instances": 0,
            "path": "",
            "vst_format": add["vst_format"],
            "cubase_tech": add["cubase_tech"],
        })

    for upd in diff.to_update:
        target = by_uid.get(upd["uid"]) or by_name.get(upd["name"])
        if target is None:
            continue
        for field_name, (_old, new) in upd["changes"].items():
            target[field_name] = new

    if remove_stale:
        stale_uids = {r["uid"] for r in diff.to_remove if r.get("uid")}
        stale_names = {r["name"] for r in diff.to_remove if r.get("name") and not r.get("uid")}
        plugins = [
            p for p in plugins
            if not (p.get("uid") in stale_uids or (not p.get("uid") and p.get("name") in stale_names))
        ]

    new_registry = dict(registry)
    new_registry["plugins"] = plugins
    new_registry.setdefault("summary", {})
    new_registry["summary"] = {
        **new_registry.get("summary", {}),
        "total_plugins": len(plugins),
        "vst3_count": sum(1 for p in plugins if p.get("vst_format") == "VST3"),
        "vst2_count": sum(1 for p in plugins if p.get("vst_format") == "VST2"),
    }
    new_registry["last_xml_sync"] = time.strftime("%Y-%m-%d %H:%M:%S")
    return new_registry


# ---------- IO ----------

def _backup_registry(path: Path) -> Path:
    stamp = time.strftime("%Y-%m-%d")
    backup = path.with_suffix(path.suffix + f".backup_{stamp}")
    if backup.exists():
        backup = path.with_suffix(path.suffix + f".backup_{stamp}_{int(time.time())}")
    shutil.copy2(path, backup)
    return backup


def load_registry(path: Path | None = None) -> dict[str, Any]:
    p = path or _REGISTRY_FILE
    if not p.exists():
        return {"plugins": []}
    return json.loads(p.read_text(encoding="utf-8"))


def save_registry(registry: dict[str, Any], path: Path | None = None) -> None:
    p = path or _REGISTRY_FILE
    p.write_text(json.dumps(registry, indent=2, ensure_ascii=False), encoding="utf-8")


# ---------- High-Level Sync ----------

def sync(
    apply: bool = False,
    remove_stale: bool = False,
    registry_path: Path | None = None,
    xml_paths: dict[str, Path] | None = None,
) -> dict[str, Any]:
    """Komplette Sync-Pipeline: Parse -> Diff -> (optional) Apply + Save.

    Returns:
        Dict mit `summary`, `diff`, `applied`, `backup` (falls geschrieben),
        `xml_paths`, `registry_path`.
    """
    paths = xml_paths or default_xml_paths()
    vst3 = parse_vst3_xml(paths["vst3"])
    vst2 = parse_vst2_xml(paths["vst2"])
    registry = load_registry(registry_path)

    diff = compute_diff(registry, vst3, vst2)

    result: dict[str, Any] = {
        "summary": diff.summary(),
        "diff": diff.to_dict(),
        "applied": False,
        "backup": None,
        "xml_paths": {k: str(v) for k, v in paths.items()},
        "registry_path": str(registry_path or _REGISTRY_FILE),
        "remove_stale": remove_stale,
    }

    if apply:
        target = registry_path or _REGISTRY_FILE
        backup = _backup_registry(target) if target.exists() else None
        new_registry = apply_diff(registry, diff, remove_stale=remove_stale)
        save_registry(new_registry, target)
        result["applied"] = True
        result["backup"] = str(backup) if backup else None

    return result


# ---------- CLI ----------

def _main() -> int:
    import argparse
    p = argparse.ArgumentParser(description="Sync Cubase Vst*PlugInfo XMLs -> yoka_plugins.json")
    p.add_argument("--apply", action="store_true", help="Schreibt yoka_plugins.json. Ohne: nur Diff.")
    p.add_argument("--remove-stale", action="store_true",
                   help="Loescht Plugins die nicht mehr im XML sind. Default: nur reporten.")
    p.add_argument("--vst3", type=Path, help="Override VstPlugInfoV4.xml-Pfad.")
    p.add_argument("--vst2", type=Path, help="Override Vst2xPlugin Infos Cubase.xml-Pfad.")
    args = p.parse_args()

    paths = default_xml_paths()
    if args.vst3:
        paths["vst3"] = args.vst3
    if args.vst2:
        paths["vst2"] = args.vst2

    res = sync(apply=args.apply, remove_stale=args.remove_stale, xml_paths=paths)
    print(json.dumps(res["summary"], indent=2))
    if not args.apply:
        print("\n-- to_add (first 10) --")
        for x in res["diff"]["to_add"][:10]:
            print(f"  + {x['name']} [{x['vst_format']}] uid={x['uid'][:12]}...")
        print("\n-- to_update (first 10) --")
        for x in res["diff"]["to_update"][:10]:
            print(f"  ~ {x['name']} ({x['match']}) -> {list(x['changes'])}")
        print("\n-- to_remove (first 10) --")
        for x in res["diff"]["to_remove"][:10]:
            print(f"  - {x['name']} uid={x['uid']}")
        print("\n(dry-run, nichts geschrieben — --apply zum Persistieren)")
    else:
        print(f"\n[OK] applied. backup: {res['backup']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(_main())
