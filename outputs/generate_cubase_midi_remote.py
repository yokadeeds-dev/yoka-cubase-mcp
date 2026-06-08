"""
generate_cubase_midi_remote.py — Macht ALLE ungebundenen Cubase-Commands per
MIDI-CC adressierbar (jenseits des ~350-Tasten-Hotkey-Limits).

Pfad: MIDI Remote API (Cubase 12+). Generic Remote ist in Cubase 15 Legacy/
entfernt — der MIDI-Remote-Pfad ist der einzige supported, scriptbare Weg.

Quelle der Wahrheit: docs/cubase_keymap.csv (Category, Command, Key, Bound).
Erzeugt deterministisch zwei Artefakte:

  1. runtime/midi_bridge/cubase_command_midi_map.json
       Kanonische Mapping-Tabelle: jeder ungebundene Command -> eindeutige
       (channel, cc)-Adresse. Versioniert + Quell-Hash. Wird vom Runtime-
       Resolver (cubase_commands.py) UND vom JS-Generator gelesen.

  2. runtime/midi_remote/ki_studio_command_remote.js
       Cubase-MIDI-Remote-Script. Pro Command: ein virtueller Button, an
       (channel, cc) auf Port AI_CMD gebunden, via makeCommandBinding an den
       Host-Command (category, command) gehaengt. Aus dem JSON generiert.

Allokation (deterministisch):
  Ungebundene Commands sortiert nach (Category, Command).
  Index i -> channel = i // 128, cc = i % 128. 16 Kanaele x 128 CC = 2048.

Port-Trennung:
  AI_CMD (neuer dedizierter loopMIDI-Port) != AI_INPUT.
  AI_INPUT-CCs treffen Plugin-MIDI-Learn auf scharfen Spuren; AI_CMD-CCs
  werden vom MIDI Remote konsumiert und erreichen nie eine Spur. Kein
  Kollisionsrisiko mit der Plugin-Param-Ebene (siehe midi_channel_layout.json).

Aufruf:
  python outputs/generate_cubase_midi_remote.py            # JSON + JS in Repo
  python outputs/generate_cubase_midi_remote.py --install  # + JS in Cubase kopieren (Backup)
  python outputs/generate_cubase_midi_remote.py --all       # auch GEBUNDENE Commands mappen
"""

from __future__ import annotations

import argparse
import csv
import hashlib
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
KEYMAP_CSV = REPO / "docs" / "cubase_keymap.csv"
JSON_OUT = REPO / "runtime" / "midi_bridge" / "cubase_command_midi_map.json"
JS_OUT = REPO / "runtime" / "midi_remote" / "ki_studio_command_remote.js"

# Cubase-MIDI-Remote-Script-Verzeichnis (Local = User-eigene Scripts).
# PFLICHT-STRUKTUR laut README_v1.html:
#   <Driver Scripts>/<Local|Public>/<vendor>/<device>/<vendor>_<device>.js
# Die Datei MUSS exakt <vendor>_<device>.js heissen (lowercase, Underscore),
# sonst ueberspringt der Scanner sie still. Die Anzeige-Namen (mit Leerzeichen)
# kommen aus makeDeviceDriver() und sind von Ordner/Datei unabhaengig.
_VENDOR_SLUG = "ki_studio"
_DEVICE_SLUG = "command_remote"
JS_FILENAME = f"{_VENDOR_SLUG}_{_DEVICE_SLUG}.js"
CUBASE_MIDI_REMOTE_LOCAL = (
    Path.home()
    / "Documents/Steinberg/Cubase/MIDI Remote/Driver Scripts/Local"
    / _VENDOR_SLUG
    / _DEVICE_SLUG
)

PORT_NAME = "AI_CMD"
TRIGGER_VALUE = 127          # Button-Press -> Command feuert
CHANNELS = 16
CC_PER_CHANNEL = 128
ADDRESS_SPACE = CHANNELS * CC_PER_CHANNEL  # 2048

VENDOR = "KI Studio"
DEVICE_NAME = "Command Remote"
AUTHOR = "KI Studio 2026"


def _slug(category: str, command: str) -> str:
    """Lookup-Slug: kategorie_command, normalisiert. Nicht garantiert eindeutig
    (Resolver nutzt primaer 'Category/Command'); dient nur als Komfort-Alias."""
    base = f"{category}_{command}".lower()
    base = re.sub(r"[^a-z0-9]+", "_", base).strip("_")
    return base


def load_commands(include_bound: bool) -> list[tuple[str, str, bool]]:
    """(category, command, is_bound) aus der versionierten CSV."""
    rows: list[tuple[str, str, bool]] = []
    with open(KEYMAP_CSV, encoding="utf-8-sig", newline="") as f:
        for r in csv.DictReader(f):
            cat = (r.get("Category") or "").strip()
            cmd = (r.get("Command") or "").strip()
            bound = (r.get("Bound") or "").strip().lower() == "true"
            if not cat or not cmd:
                continue
            if bound and not include_bound:
                continue
            rows.append((cat, cmd, bound))
    return rows


def source_hash() -> str:
    return hashlib.sha256(KEYMAP_CSV.read_bytes()).hexdigest()


def build_map(include_bound: bool) -> dict:
    cmds = load_commands(include_bound)
    # Deterministische, stabile Reihenfolge.
    cmds.sort(key=lambda x: (x[0], x[1]))

    if len(cmds) > ADDRESS_SPACE:
        raise SystemExit(
            f"FEHLER: {len(cmds)} Commands > {ADDRESS_SPACE} CC-Adressen. "
            f"Note-On-Bank noetig (siehe Doku) oder include_bound=False lassen."
        )

    commands: dict[str, dict] = {}
    slug_index: dict[str, str] = {}
    slug_collisions: set[str] = set()
    for i, (cat, cmd, bound) in enumerate(cmds):
        channel = i // CC_PER_CHANNEL          # 0-15 (DAW-Anzeige: +1)
        cc = i % CC_PER_CHANNEL                 # 0-127
        key = f"{cat}/{cmd}"
        sl = _slug(cat, cmd)
        if sl in slug_index:
            slug_collisions.add(sl)
        else:
            slug_index[sl] = key
        commands[key] = {
            "category": cat,
            "command": cmd,
            "channel": channel,
            "cc": cc,
            "slug": sl,
            "midi": f"ch{channel + 1}/cc{cc}",
            "was_bound": bound,
        }
    # Mehrdeutige Slugs raus — Resolver erzwingt dort die volle Form.
    for sl in slug_collisions:
        slug_index.pop(sl, None)

    return {
        "version": "1.0",
        "generated_at": datetime.now().strftime("%Y-%m-%d"),
        "generated_from": "docs/cubase_keymap.csv",
        "source_sha256": source_hash(),
        "transport": "midi_remote_api",
        "rationale": (
            "Generic Remote ist in Cubase 15 Legacy/entfernt. MIDI Remote API "
            "ist der supported, scriptbare Pfad. Dieses JSON ist die Single "
            "Source of Truth; das JS-Script ist ein regeneriertes Artefakt."
        ),
        "port": PORT_NAME,
        "trigger_value": TRIGGER_VALUE,
        "include_bound": include_bound,
        "address_space": {
            "channels": CHANNELS,
            "cc_per_channel": CC_PER_CHANNEL,
            "total": ADDRESS_SPACE,
        },
        "command_count": len(commands),
        "slug_index": dict(sorted(slug_index.items())),
        "commands": commands,
    }


def _js_str(s: str) -> str:
    """String fuer JS-Literal escapen (einfache Quotes)."""
    return s.replace("\\", "\\\\").replace("'", "\\'")


def render_js(mapping: dict) -> str:
    cmds = mapping["commands"]
    lines: list[str] = []
    lines.append("//" + "-" * 77)
    lines.append("// KI Studio 2026 — Command Remote (MIDI Remote API, Cubase 15)")
    lines.append(f"// GENERIERT von outputs/generate_cubase_midi_remote.py — NICHT manuell editieren.")
    lines.append(f"// Quelle: {mapping['generated_from']} (sha256 {mapping['source_sha256'][:12]}…)")
    lines.append(f"// Generiert: {mapping['generated_at']} | Commands: {mapping['command_count']} | Port: {mapping['port']}")
    lines.append("//" + "-" * 77)
    lines.append("")
    lines.append("var midiremote_api = require('midiremote_api_v1')")
    lines.append("")
    lines.append(
        f"var deviceDriver = midiremote_api.makeDeviceDriver('{_js_str(VENDOR)}', "
        f"'{_js_str(DEVICE_NAME)}', '{_js_str(AUTHOR)}')"
    )
    lines.append("var midiInput = deviceDriver.mPorts.makeMidiInput()")
    lines.append("")
    lines.append("// Auto-Detection: Script lädt sobald ein Input-Port AI_CMD auftaucht.")
    lines.append(
        f"deviceDriver.makeDetectionUnit().detectSingleInput(midiInput)"
        f".expectInputNameContains('{_js_str(PORT_NAME)}')"
    )
    lines.append("")
    lines.append("var surface = deviceDriver.mSurface")
    lines.append("var page = deviceDriver.mMapping.makePage('Commands')")
    lines.append("")
    lines.append("// Virtuelle Buttons -> CC-Bindings -> Host-Command-Bindings.")
    lines.append("// Koordinaten sind kosmetisch (Tile-Grid); nur fuer den Surface-Editor.")
    lines.append("function bindCmd(ch, cc, x, y, category, command) {")
    lines.append("    var btn = surface.makeButton(x, y, 1, 1)")
    lines.append("    btn.mSurfaceValue.mMidiBinding.setInputPort(midiInput).bindToControlChange(ch, cc)")
    lines.append("    page.makeCommandBinding(btn.mSurfaceValue, category, command)")
    lines.append("}")
    lines.append("")

    # Stabile Ausgabe-Reihenfolge = nach (channel, cc).
    ordered = sorted(cmds.values(), key=lambda c: (c["channel"], c["cc"]))
    grid_w = 64
    for n, c in enumerate(ordered):
        x = n % grid_w
        y = n // grid_w
        lines.append(
            f"bindCmd({c['channel']}, {c['cc']}, {x}, {y}, "
            f"'{_js_str(c['category'])}', '{_js_str(c['command'])}')"
        )
    lines.append("")
    return "\n".join(lines)


def write_utf8_no_bom(path: Path, text: str) -> None:
    """BOM-frei schreiben (Cubase JS-Engine + JSON strict)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(text.encode("utf-8"))


def install_js(js_text: str) -> Path:
    """JS in Cubase-Local-Verzeichnis kopieren, vorher Backup falls vorhanden."""
    CUBASE_MIDI_REMOTE_LOCAL.mkdir(parents=True, exist_ok=True)
    target = CUBASE_MIDI_REMOTE_LOCAL / JS_FILENAME
    if target.exists():
        stamp = datetime.now().strftime("%Y-%m-%d")
        backup = target.with_suffix(f".js.backup_{stamp}")
        shutil.copy2(target, backup)
        print(f"  Backup: {backup}")
    write_utf8_no_bom(target, js_text)
    return target


def main() -> int:
    ap = argparse.ArgumentParser(description="Cubase MIDI Remote Command-Mapping generieren.")
    ap.add_argument("--install", action="store_true", help="JS zusaetzlich in Cubase-Local kopieren (Backup).")
    ap.add_argument("--all", action="store_true", help="Auch GEBUNDENE Commands mappen (sofern <=2048).")
    args = ap.parse_args()

    mapping = build_map(include_bound=args.all)
    js_text = render_js(mapping)

    write_utf8_no_bom(JSON_OUT, json.dumps(mapping, ensure_ascii=False, indent=2) + "\n")
    write_utf8_no_bom(JS_OUT, js_text)

    print(f"Commands gemappt: {mapping['command_count']} / {ADDRESS_SPACE} Adressen")
    print(f"  JSON: {JSON_OUT.relative_to(REPO)}")
    print(f"  JS:   {JS_OUT.relative_to(REPO)}")

    if args.install:
        print("Install nach Cubase-Local:")
        target = install_js(js_text)
        print(f"  -> {target}")
        print("  Cubase neu starten ODER MIDI Remote Manager neu scannen, "
              "und loopMIDI-Port 'AI_CMD' muss existieren.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
