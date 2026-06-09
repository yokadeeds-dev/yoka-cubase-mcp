"""
generate_value_bindings.py — Macht Plugin-Parameter der SELEKTIERTEN Spur per
MIDI-CC steuerbar (Cubase MIDI Remote API, makeValueBinding). Das ist die
zweite Achse neben dem Command-Remote: nicht Aktionen, sondern Plugin-Werte —
inkl. Cubase-Stock-Plugins ohne eigenes MIDI-Learn.

Erzeugt deterministisch zwei Artefakte:

  1. runtime/midi_remote/ki_studio_value_remote.js
       MIDI-Remote-Script (Cubase 15). Bindet pro Insert-Slot (0-7) der
       selektierten Spur MAX_PARAMS Parameter-Positionen an CC auf Port AI_VAL.
       Plugin-agnostisch: das JS weiss nicht, welches Plugin auf welchem Slot
       liegt — es bindet generisch Slot x Param.

  2. runtime/midi_bridge/cubase_value_cc_map.json
       Lookup fuer die KI/MCP-Seite: pro Plugin (aus cubase_plugin_param_map.json)
       je Parameter -> (cc, title, role). Der Channel ergibt sich zur Laufzeit aus
       dem Insert-Slot, auf dem das Plugin liegt (channel = slot + 1).

ADRESSIERUNGS-MODELL (fest):
  Port      : AI_VAL  (dedizierter loopMIDI-Port, kollisionsfrei zu
              AI_INPUT/AI_CMD/AI_SCAN/AI_RETURN)
  Channel   : 1-8 (API-Index 0-7) = Insert-Slot 0-7 der selektierten Spur
  CC        : 0-(MAX_PARAMS-1)     = Parameter-Index im Slot
  Binding   : sel.mInsertAndStripEffects.makeInsertEffectViewer('slotN')
              .accessSlotAtIndex(N) -> .mParameterBankZone.makeParameterValue()
              je Param; an Knob.mSurfaceValue mit bindToControlChange(N, pIdx);
              page.makeValueBinding(knob.mSurfaceValue, hostValue).
  (Verifiziert 2026-06-09: mInserts[n] und makeParameterBank existieren NICHT.)

Aufruf:
  python outputs/generate_value_bindings.py            # JS + JSON ins Repo
  python outputs/generate_value_bindings.py --install  # + JS nach Cubase-Local (Backup)

Voraussetzung fuer Betrieb: loopMIDI-Port "AI_VAL" + Cubase MIDI-Remote-Reload.
"""

from __future__ import annotations

import argparse
import hashlib
import io
import json
import shutil
import sys
from datetime import datetime
from pathlib import Path

if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

REPO = Path(__file__).resolve().parent.parent
PARAM_MAP = REPO / "runtime" / "midi_bridge" / "cubase_plugin_param_map.json"
JS_OUT = REPO / "runtime" / "midi_remote" / "ki_studio_value_remote.js"
CC_MAP_OUT = REPO / "runtime" / "midi_bridge" / "cubase_value_cc_map.json"

# Cubase-MIDI-Remote-Local-Verzeichnis (Pflicht-Struktur wie command_remote):
#   <Driver Scripts>/Local/<vendor>/<device>/<vendor>_<device>.js
_VENDOR_SLUG = "ki_studio"
_DEVICE_SLUG = "value_remote"
JS_FILENAME = f"{_VENDOR_SLUG}_{_DEVICE_SLUG}.js"
CUBASE_MIDI_REMOTE_LOCAL = (
    Path.home()
    / "Documents/Steinberg/Cubase/MIDI Remote/Driver Scripts/Local"
    / _VENDOR_SLUG
    / _DEVICE_SLUG
)

PORT_NAME = "AI_VAL"
NUM_SLOTS = 8          # Insert-Slots 0-7 -> Channel 1-8
MAX_PARAMS = 64        # Param-Positionen je Slot -> CC 0-63 (deckt alle gescannten Plugins, inkl. Frequency 58 / Eventide 64)

VENDOR = "KI Studio"
DEVICE_NAME = "Value Remote"
AUTHOR = "KI Studio 2026"


def load_param_map() -> dict:
    return json.loads(PARAM_MAP.read_text(encoding="utf-8"))


def source_hash() -> str:
    return hashlib.sha256(PARAM_MAP.read_bytes()).hexdigest()


def build_cc_map(param_map: dict) -> dict:
    """Lookup pro Plugin: param_index -> cc (= param_index), title, role.
    Channel ist NICHT fix (haengt vom Insert-Slot zur Laufzeit ab): channel = slot + 1.
    Params mit index >= MAX_PARAMS werden als 'out_of_range' markiert (nicht adressierbar).
    """
    plugins: dict[str, dict] = {}
    for p in param_map.get("scanned_plugins", []):
        title = p["object_title"]
        params_out = []
        for prm in p.get("params", []):
            idx = prm["index"]
            entry = {
                "param_index": idx,
                "cc": idx,                       # CC == Param-Index (innerhalb des Slot-Channels)
                "title": prm.get("title", ""),
            }
            if "role" in prm:
                entry["role"] = prm["role"]
            if idx >= MAX_PARAMS:
                entry["out_of_range"] = True     # jenseits CC 0-47 -> nicht gebunden
            params_out.append(entry)
        plugins[title] = {
            "param_count": len(params_out),
            "pagination_period": p.get("pagination_period"),
            "params": params_out,
        }

    return {
        "version": "1.0",
        "generated_at": datetime.now().strftime("%Y-%m-%d"),
        "generated_from": "runtime/midi_bridge/cubase_plugin_param_map.json",
        "source_sha256": source_hash(),
        "transport": "midi_remote_api",
        "addressing": {
            "port": PORT_NAME,
            "channel": "1-8 (API 0-7) = Insert-Slot 0-7 der selektierten Spur",
            "cc": f"0-{MAX_PARAMS - 1} = Parameter-Index im Slot",
            "channel_from_slot": "channel = insert_slot + 1 (zur Laufzeit, je nachdem wo das Plugin liegt)",
            "max_params": MAX_PARAMS,
            "rule": "Steuere Plugin-Param: sende auf Channel=(Slot+1), CC=param_index. Wert 0-127 = Param 0..100%.",
        },
        "num_slots": NUM_SLOTS,
        "plugin_count": len(plugins),
        "plugins": dict(sorted(plugins.items(), key=lambda kv: kv[0].lower())),
    }


def render_js(mapping: dict) -> str:
    lines: list[str] = []
    lines.append("//" + "-" * 77)
    lines.append("// KI Studio 2026 — Value Remote (MIDI Remote API, Cubase 15)")
    lines.append("// GENERIERT von outputs/generate_value_bindings.py — NICHT manuell editieren.")
    lines.append(f"// Quelle: {mapping['generated_from']} (sha256 {mapping['source_sha256'][:12]}…)")
    lines.append(f"// Generiert: {mapping['generated_at']} | Slots: {NUM_SLOTS} x {MAX_PARAMS} Params | Port: {PORT_NAME}")
    lines.append("//")
    lines.append("// Bindet Plugin-Parameter der SELEKTIERTEN Spur an MIDI-CC:")
    lines.append("//   Channel 1-8 (API 0-7) = Insert-Slot 0-7")
    lines.append("//   CC 0-" + str(MAX_PARAMS - 1) + " = Parameter-Index im Slot")
    lines.append("// Plugin-agnostisch — welcher CC welchen Plugin-Param trifft, sagt")
    lines.append("// runtime/midi_bridge/cubase_value_cc_map.json (KI/MCP-Seite).")
    lines.append("//" + "-" * 77)
    lines.append("")
    lines.append("var midiremote_api = require('midiremote_api_v1')")
    lines.append("")
    lines.append(
        f"var deviceDriver = midiremote_api.makeDeviceDriver('{VENDOR}', '{DEVICE_NAME}', '{AUTHOR}')"
    )
    lines.append("var midiInput = deviceDriver.mPorts.makeMidiInput()")
    lines.append("")
    lines.append("// Auto-Detection: laedt sobald ein Input-Port AI_VAL auftaucht.")
    lines.append(
        f"deviceDriver.makeDetectionUnit().detectSingleInput(midiInput)"
        f".expectInputNameContains('{PORT_NAME}')"
    )
    lines.append("")
    lines.append("var surface = deviceDriver.mSurface")
    lines.append("var page = deviceDriver.mMapping.makePage('Values')")
    lines.append("var sel = page.mHostAccess.mTrackSelection.mMixerChannel")
    lines.append("")
    lines.append("// Pro Insert-Slot ein InsertEffectViewer, fest auf den Slot gestellt;")
    lines.append("// dessen mParameterBankZone liefert die Parameter via makeParameterValue().")
    lines.append("// Knob-Koordinaten sind kosmetisch (nur fuer den Surface-Editor).")
    lines.append("function bindSlot(slot, rowY) {")
    lines.append("    var viewer = sel.mInsertAndStripEffects.makeInsertEffectViewer('slot' + slot)")
    lines.append("    viewer.accessSlotAtIndex(slot)")
    lines.append("    var bankZone = viewer.mParameterBankZone")
    lines.append(f"    for (var p = 0; p < {MAX_PARAMS}; p++) {{")
    lines.append("        var hostVal = bankZone.makeParameterValue()")
    lines.append("        var knob = surface.makeKnob(p % 24, rowY + Math.floor(p / 24), 1, 1)")
    lines.append("        knob.mSurfaceValue.mMidiBinding.setInputPort(midiInput).bindToControlChange(slot, p)")
    lines.append("        page.makeValueBinding(knob.mSurfaceValue, hostVal)")
    lines.append("    }")
    lines.append("}")
    lines.append("")
    lines.append(f"for (var s = 0; s < {NUM_SLOTS}; s++) {{ bindSlot(s, s * 3) }}")
    lines.append("")
    return "\n".join(lines)


def write_utf8_no_bom(path: Path, text: str) -> None:
    """BOM-frei (Cubase JS-Engine + JSON strict)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(text.encode("utf-8"))


def install_js(js_text: str) -> Path:
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
    ap = argparse.ArgumentParser(description="Cubase Value-Binding-Generator (Plugin-Parameter per CC).")
    ap.add_argument("--install", action="store_true", help="JS zusaetzlich nach Cubase-Local kopieren (Backup).")
    args = ap.parse_args()

    if not PARAM_MAP.exists():
        raise SystemExit(f"FEHLER: Param-Map fehlt: {PARAM_MAP}")

    param_map = load_param_map()
    cc_map = build_cc_map(param_map)
    js_text = render_js(cc_map)

    write_utf8_no_bom(CC_MAP_OUT, json.dumps(cc_map, ensure_ascii=False, indent=2) + "\n")
    write_utf8_no_bom(JS_OUT, js_text)

    bindings = NUM_SLOTS * MAX_PARAMS
    print(f"Value-Bindings generiert: {NUM_SLOTS} Slots x {MAX_PARAMS} Params = {bindings} CC-Bindings")
    print(f"Plugins in CC-Map: {cc_map['plugin_count']}")
    print(f"  JS:  {JS_OUT.relative_to(REPO)}")
    print(f"  MAP: {CC_MAP_OUT.relative_to(REPO)}")

    # Out-of-range-Hinweis (Params jenseits CC 0-47).
    oor = []
    for name, pl in cc_map["plugins"].items():
        n = sum(1 for prm in pl["params"] if prm.get("out_of_range"))
        if n:
            oor.append(f"{name} ({n})")
    if oor:
        print(f"  Hinweis: Params jenseits CC{MAX_PARAMS-1} (nicht gebunden): {', '.join(oor)}")

    if args.install:
        print("Install nach Cubase-Local:")
        target = install_js(js_text)
        print(f"  -> {target}")
        print(f"  loopMIDI-Port '{PORT_NAME}' muss existieren; dann MIDI-Remote-Manager -> 'Skripte neu laden'.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
