"""
Mackie-Listener — öffnet einen MIDI-Eingangsport, parst eingehende
Mackie-Messages und schreibt den Zustand in einen StateMirror.

CLI-Modus:
    python -m runtime.mackie.listener --port "MACKIE_FROM_CUBASE"
    python -m runtime.mackie.listener --list-ports
    python -m runtime.mackie.listener --port "MACKIE_FROM_CUBASE" --json-out runtime/state/snapshots/cubase.json
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path
from typing import Any

import mido

from runtime.mackie.parser import parse_message
from runtime.mackie.state import StateMirror


def list_ports() -> list[str]:
    # mido gibt auf manchen Systemen None-Einträge zurück (defekte Ports)
    return [p for p in mido.get_input_names() if p is not None]


def resolve_port(requested: str) -> str:
    """
    Findet den vollen Portnamen via (Priorität hoch → niedrig):
    1. Exact match
    2. Prefix-Match  (Windows loopMIDI: 'MACKIE_FROM_CUBASE 3')
    3. Suffix-Match  (macOS IAC: 'IAC-Treiber KI-Studio MACKIE_FROM_CUBASE')
    4. Substring-Match als Fallback

    None-Einträge (defekte Ports) werden von list_ports() bereits gefiltert.
    """
    available = list_ports()
    if requested in available:
        return requested
    req_lower = requested.lower()
    # Prefix-Match
    matches = [n for n in available if n.lower().startswith(req_lower)]
    if len(matches) == 1:
        return matches[0]
    if len(matches) > 1:
        raise ValueError(f"Mehrere Prefix-Treffer für {requested!r}: {matches}")
    # Suffix-Match — bevorzugt auf macOS wo IAC-Device-Name als Prefix steht
    matches = [n for n in available if n.lower().endswith(req_lower)]
    if len(matches) == 1:
        return matches[0]
    if len(matches) > 1:
        raise ValueError(f"Mehrere Suffix-Treffer für {requested!r}: {matches}")
    # Substring-Fallback
    matches = [n for n in available if req_lower in n.lower()]
    if len(matches) == 1:
        return matches[0]
    if len(matches) > 1:
        raise ValueError(f"Mehrere Substring-Treffer für {requested!r}: {matches}")
    raise ValueError(f"Kein MIDI-Port gefunden für {requested!r}. Verfügbar: {available}")


_SILENT_KINDS = {
    "vu",                # 10 Hz Pegel-Updates
    "timecode_digit",    # CC 64–73 Flood während Play
    "cc_other",          # alles, was wir nicht explizit kennen
    "button_other",      # Mackie-Buttons, die Phase 1 nicht braucht (Edit, Zoom, etc.)
    "lcd",               # einzelne LCD-Patches sind verbose; Track-Name kommt im SELECT-Output
    "unknown",
    "sysex_other",
    "encoder",           # in Phase 1 unbenutzt
    "fader",             # Phase 2 — würde sonst beim Slider-Drag fluten
}


def _print_event(event: dict[str, Any], state: StateMirror) -> None:
    kind = event.get("kind", "?")
    if kind in _SILENT_KINDS:
        return
    if kind == "select":
        if event["pressed"]:
            snap = state.snapshot()
            track = snap["tracks"][event["channel"]]
            # name_resolved ist mode-aware; track["name"] ist nur die rohe LCD-Reihe 1
            name = track.get("name_resolved") or track["name"]
            print(f"[SELECT] track_index={event['channel'] + 1} name={name!r} mode={snap.get('mode')}", flush=True)
    elif kind == "mute" and event["pressed"]:
        print(f"[MUTE] track={event['channel'] + 1} toggled", flush=True)
    elif kind == "solo" and event["pressed"]:
        print(f"[SOLO] track={event['channel'] + 1} toggled", flush=True)
    elif kind == "rec_arm" and event["pressed"]:
        print(f"[REC] track={event['channel'] + 1} toggled", flush=True)
    elif kind == "transport_button" and event["pressed"]:
        print(f"[TRANSPORT] {event['action']}", flush=True)
    elif kind == "mode_button" and event["pressed"]:
        print(f"[MODE] {event['mode']}", flush=True)
    elif kind == "two_char_display":
        print(f"[2CHAR] {event['text']!r}", flush=True)


def run(port_name: str, json_out: Path | None = None, write_every_ms: int = 200) -> None:
    state = StateMirror(daw="cubase")
    full_name = resolve_port(port_name)
    print(f"Opening MIDI input port: {full_name!r}")
    last_write = time.monotonic()

    with mido.open_input(full_name) as inp:
        print("Listener läuft. Strg+C zum Stoppen.\n")
        for msg in inp:
            event = parse_message(msg)
            state.apply_event(event)
            _print_event(event, state)

            if json_out is not None:
                now = time.monotonic()
                if (now - last_write) * 1000 >= write_every_ms:
                    json_out.parent.mkdir(parents=True, exist_ok=True)
                    state.write_json(json_out)
                    last_write = now


def main() -> int:
    p = argparse.ArgumentParser(description="Mackie-Listener (Etappe 1).")
    p.add_argument("--port", help="Name des MIDI-Eingangsports (z. B. 'MACKIE_FROM_CUBASE')")
    p.add_argument("--list-ports", action="store_true", help="Verfügbare MIDI-Ports anzeigen.")
    p.add_argument("--json-out", type=Path, help="Pfad für State-Snapshot-JSON (Atomic Write).")
    p.add_argument("--write-every-ms", type=int, default=200, help="JSON-Schreib-Intervall in ms.")
    args = p.parse_args()

    if args.list_ports:
        for name in list_ports():
            print(name)
        return 0

    if not args.port:
        p.error("--port ist erforderlich (oder --list-ports verwenden)")

    try:
        run(args.port, json_out=args.json_out, write_every_ms=args.write_every_ms)
    except KeyboardInterrupt:
        print("\nListener gestoppt.")
        return 0
    except (OSError, ValueError) as e:
        print(f"FEHLER beim Öffnen des Ports {args.port!r}: {e}", file=sys.stderr)
        print("Tipp: erst 'python -m runtime.mackie.listener --list-ports' aufrufen.", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
