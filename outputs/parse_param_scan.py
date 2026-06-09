"""
parse_param_scan.py — Zwei Funktionen rund um ki_studio_param_scan.js:

  1. --install : kopiert runtime/midi_remote/ki_studio_param_scan.js in das
                 Cubase-MIDI-Remote-Local-Verzeichnis (mit Backup).

  2. <logfile> : parst die aus der Cubase Script Console kopierte [PARAMSCAN]-
                 Ausgabe und erzeugt runtime/midi_bridge/cubase_plugin_param_map.json
                 — die Single Source of Truth fuer den Value-Binding-Generator
                 (analog cubase_command_midi_map.json).

Henne-Ei aufgeloest: Der Generator braucht Param-Titel; die liefert nur Cubase
zur Laufzeit. Dieser Scan-Schritt ist einmalig pro Plugin-Typ.

Aufruf:
  python outputs/parse_param_scan.py --install            # Scanner nach Cubase kopieren
  python outputs/parse_param_scan.py scan_output.txt      # Console-Log -> JSON
  python outputs/parse_param_scan.py scan_output.txt --merge   # in bestehende Map mergen
"""

from __future__ import annotations

import argparse
import io
import json
import re
import shutil
import sys
from datetime import datetime
from pathlib import Path

if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

REPO = Path(__file__).resolve().parent.parent
SCANNER_JS = REPO / "runtime" / "midi_remote" / "ki_studio_param_scan.js"
JSON_OUT = REPO / "runtime" / "midi_bridge" / "cubase_plugin_param_map.json"

_VENDOR_SLUG = "ki_studio"
_DEVICE_SLUG = "param_scan"
CUBASE_MIDI_REMOTE_LOCAL = (
    Path.home()
    / "Documents/Steinberg/Cubase/MIDI Remote/Driver Scripts/Local"
    / _VENDOR_SLUG
    / _DEVICE_SLUG
)
JS_FILENAME = f"{_VENDOR_SLUG}_{_DEVICE_SLUG}.js"

# [PARAMSCAN] slot=0 idx=3 obj="Magneto 2" val="Saturation"
LINE_RE = re.compile(
    r'\[PARAMSCAN\]\s+slot=(\d+)\s+idx=(\d+)\s+obj="(.*?)"\s+val="(.*?)"\s*$'
)


def write_utf8_no_bom(path: Path, text: str) -> None:
    """BOM-frei (Cubase JS-Engine + JSON strict)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(text.encode("utf-8"))


def install_scanner() -> Path:
    if not SCANNER_JS.exists():
        raise SystemExit(f"FEHLER: Scanner-JS fehlt: {SCANNER_JS}")
    CUBASE_MIDI_REMOTE_LOCAL.mkdir(parents=True, exist_ok=True)
    target = CUBASE_MIDI_REMOTE_LOCAL / JS_FILENAME
    if target.exists():
        stamp = datetime.now().strftime("%Y-%m-%d")
        backup = target.with_suffix(f".js.backup_{stamp}")
        shutil.copy2(target, backup)
        print(f"  Backup: {backup}")
    write_utf8_no_bom(target, SCANNER_JS.read_text(encoding="utf-8"))
    return target


def _detect_pagination_period(idxs: list, params: dict):
    """Erkennt Pagination-Wiederholung: makeParameterValue() ueber die echte
    Param-Zahl hinaus liefert dieselben Titel erneut (mit hoeheren idx). Findet
    das kleinste p>1, ab dem sich die Titelsequenz periodisch wiederholt
    (>=2 aufeinanderfolgende Treffer als Schutz vor Zufall). Liefert p oder None.
    """
    if len(idxs) < 4:
        return None
    base = idxs[0]
    titles = {i: params[i] for i in idxs}
    for p in range(2, len(idxs)):
        cand = base + p
        if cand not in titles:
            continue
        # zwei aufeinanderfolgende Positionen muessen matchen
        nxt = idxs[1] + p
        if titles.get(cand) == titles[base] and titles.get(nxt) == titles[idxs[1]]:
            # verifiziere ueber den restlichen Ueberlapp
            ok = all(
                titles.get(i + p) == titles[i]
                for i in idxs if (i + p) in titles and i < base + p
            )
            if ok:
                return p
    return None


def parse_log(text: str) -> dict:
    """Console-Log -> strukturierte Plugin-Param-Map.

    Gruppiert nach (slot, object_title). Leere/Doppel-Zeilen ignoriert.
    idx ist die Host-Parameter-Position (= spaeterer Binding-Index).
    """
    # (slot, obj) -> { idx: title }
    groups: dict[tuple[int, str], dict[int, str]] = {}
    seen = 0
    for line in text.splitlines():
        m = LINE_RE.search(line.strip())
        if not m:
            continue
        slot = int(m.group(1))
        idx = int(m.group(2))
        obj = m.group(3).strip()
        val = m.group(4).strip()
        if not val:                      # leere Param-Position -> ueberspringen
            continue
        seen += 1
        groups.setdefault((slot, obj), {})[idx] = val

    scanned = []
    for (slot, obj), params in sorted(groups.items(), key=lambda kv: (kv[0][0], kv[0][1])):
        idxs = sorted(params)
        period = _detect_pagination_period(idxs, params)
        kept = [i for i in idxs if i < period] if period else idxs
        ordered = [{"index": i, "title": params[i]} for i in kept]
        entry = {
            "slot": slot,
            "object_title": obj,
            "param_count": len(ordered),
            "params": ordered,
        }
        if period:
            entry["pagination_period"] = period
            entry["dropped_repeats"] = len(idxs) - len(kept)
        scanned.append(entry)

    return {
        "version": "1.0",
        "generated_at": datetime.now().strftime("%Y-%m-%d"),
        "source": "cubase_script_console (ki_studio_param_scan.js)",
        "transport": "midi_remote_api",
        "rationale": (
            "Plugin-Parameter-Titel aus dem MIDI-Remote-Scan. Single Source of "
            "Truth fuer den Value-Binding-Generator (makeValueBinding). Adressiert "
            "ueber selektierte Spur -> Insert-Slot -> Param-Index, unabhaengig von "
            "plugin-internem MIDI-Learn (auch Cubase-Stock-Plugins)."
        ),
        "lines_parsed": seen,
        "plugin_count": len(scanned),
        "scanned_plugins": scanned,
    }


def merge_maps(existing: dict, fresh: dict) -> dict:
    """Frische Scans in bestehende Map mergen (per (slot, object_title) ersetzen)."""
    by_key = {(p["slot"], p["object_title"]): p for p in existing.get("scanned_plugins", [])}
    for p in fresh["scanned_plugins"]:
        by_key[(p["slot"], p["object_title"])] = p
    merged = dict(fresh)
    merged["scanned_plugins"] = [
        by_key[k] for k in sorted(by_key, key=lambda k: (k[0], k[1]))
    ]
    merged["plugin_count"] = len(merged["scanned_plugins"])
    return merged


def main() -> int:
    ap = argparse.ArgumentParser(description="Cubase Plugin-Param-Scan installieren/parsen.")
    ap.add_argument("logfile", nargs="?", help="Aus der Script Console kopierte [PARAMSCAN]-Ausgabe (.txt).")
    ap.add_argument("--install", action="store_true", help="Scanner-JS nach Cubase-Local kopieren (Backup).")
    ap.add_argument("--merge", action="store_true", help="In bestehende param_map.json mergen statt ueberschreiben.")
    args = ap.parse_args()

    if args.install:
        print("Install Scanner nach Cubase-Local:")
        target = install_scanner()
        print(f"  -> {target}")
        print("  In Cubase: Studio -> MIDI Remote-Manager -> Refresh-Icon -> 'Skripte neu laden'.")
        print("  loopMIDI-Port 'AI_SCAN' muss existieren (eigener Detection-Port, NICHT AI_CMD).")
        if not args.logfile:
            return 0

    if not args.logfile:
        ap.error("Kein Logfile angegeben (und kein --install). Eines von beidem noetig.")

    log_path = Path(args.logfile)
    if not log_path.is_absolute():
        log_path = (Path.cwd() / log_path).resolve()
    if not log_path.exists():
        raise SystemExit(f"FEHLER: Logfile nicht gefunden: {log_path}")

    fresh = parse_log(log_path.read_text(encoding="utf-8", errors="replace"))

    if not fresh["scanned_plugins"]:
        print("WARNUNG: Keine [PARAMSCAN]-Zeilen erkannt. Wurde die Ziel-Spur "
              "selektiert + die Console-Ausgabe vollstaendig kopiert?")

    if args.merge and JSON_OUT.exists():
        existing = json.loads(JSON_OUT.read_text(encoding="utf-8"))
        fresh = merge_maps(existing, fresh)
        print("  (in bestehende Map gemergt)")

    write_utf8_no_bom(JSON_OUT, json.dumps(fresh, ensure_ascii=False, indent=2) + "\n")

    print(f"Geparst: {fresh['lines_parsed']} Param-Zeilen -> {fresh['plugin_count']} Plugin(s)")
    for p in fresh["scanned_plugins"]:
        n = p.get("param_count", len(p.get("params", [])))
        print(f"  Slot {p['slot']}: {p['object_title']!r} - {n} Params")
    print(f"  JSON: {JSON_OUT.relative_to(REPO)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
