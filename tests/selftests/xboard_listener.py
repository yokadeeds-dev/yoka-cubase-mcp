"""
Standalone-Listener fuer das E-Mu Xboard 49 — loggt alle eingehenden MIDI-Events
fuer ein Capture-Fenster, gruppiert nach Typ (CC/Note/Pitch/Mod).

Aufruf:
    python -m tests.selftests.xboard_listener
"""

from __future__ import annotations

import sys
import time
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import mido  # noqa: E402

CAPTURE_SECONDS = 35
PORT_HINT = "Xboard"


def find_port() -> str:
    for name in mido.get_input_names():
        if name and PORT_HINT.lower() in name.lower():
            return name
    raise RuntimeError(f"Kein Port gefunden mit Hint {PORT_HINT!r}. Verfuegbar: {mido.get_input_names()}")


def main() -> int:
    port_name = find_port()
    print(f"Xboard-Port: {port_name!r}")
    print(f"Capture {CAPTURE_SECONDS}s — drueck/drehe nach der Reihe alle Knoepfe + Mod-Wheel + Pitchbend.")
    print("    Konvention: links-oben → rechts-oben → links-unten → rechts-unten o.ae., 1 Element pro 2-3s.\n")

    cc_events: dict[tuple[int, int], list[tuple[float, int]]] = defaultdict(list)
    note_events: dict[int, list[tuple[float, str, int]]] = defaultdict(list)
    pitch_events: list[tuple[float, int]] = []
    other_events: list[tuple[float, str]] = []

    t0 = time.monotonic()
    with mido.open_input(port_name) as inp:
        while time.monotonic() - t0 < CAPTURE_SECONDS:
            msg = inp.poll()
            if msg is None:
                time.sleep(0.005)
                continue
            t = time.monotonic() - t0
            if msg.type == "control_change":
                cc_events[(msg.channel, msg.control)].append((t, msg.value))
            elif msg.type in ("note_on", "note_off"):
                note_events[msg.note].append((t, msg.type, msg.velocity))
            elif msg.type == "pitchwheel":
                pitch_events.append((t, msg.pitch))
            else:
                other_events.append((t, str(msg)))

    print(f"\n=== Zusammenfassung nach {CAPTURE_SECONDS}s ===\n")

    print(f"** Control-Change-Events (Knoepfe / Slider / Mod-Wheel) **")
    print(f"   {len(cc_events)} unterschiedliche (channel, cc) Kombinationen erfasst:\n")
    # Sortiert nach erstem Auftreten — entspricht Reihenfolge in der Yoka gedreht hat
    sorted_keys = sorted(cc_events.keys(), key=lambda k: cc_events[k][0][0])
    for i, (ch, cc) in enumerate(sorted_keys, 1):
        events = cc_events[(ch, cc)]
        first_t = events[0][0]
        values = [v for _, v in events]
        v_min, v_max = min(values), max(values)
        print(f"   #{i:2d}  ch={ch}  cc={cc:>3d}  first@{first_t:5.2f}s  events={len(events):>4d}  range={v_min}..{v_max}")
    print()

    print(f"** Pitchbend-Events **  {len(pitch_events)} insgesamt")
    if pitch_events:
        ranges = [p for _, p in pitch_events]
        print(f"   range={min(ranges)}..{max(ranges)} (mido normalisiert -8192..+8191)")
    print()

    print(f"** Note-Events (Tasten / Pads) **  {len(note_events)} unterschiedliche Notes")
    if note_events:
        sorted_notes = sorted(note_events.keys())
        for note in sorted_notes:
            evs = note_events[note]
            on_count = sum(1 for _, t, _ in evs if t == "note_on")
            print(f"   note={note:>3d}  on={on_count}  total={len(evs)}")
    print()

    if other_events:
        print(f"** Andere Events ** {len(other_events)}")
        for t, s in other_events[:10]:
            print(f"   +{t:5.2f}s  {s}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
