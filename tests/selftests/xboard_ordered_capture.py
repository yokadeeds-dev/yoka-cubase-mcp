"""
Geordneter Xboard-Capture — Yoka dreht Poti 1, 2, 3, ... 16 in physikalischer
Reihenfolge. Aus first-occurrence-timestamps wird das CC-zu-Position-Mapping
eindeutig zugeordnet.

Aufruf:
    python -m tests.selftests.xboard_ordered_capture
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

CAPTURE_SECONDS = 60
PORT_HINT = "Xboard"


def find_port() -> str:
    for name in mido.get_input_names():
        if name and PORT_HINT.lower() in name.lower():
            return name
    raise RuntimeError(f"Kein Port gefunden mit Hint {PORT_HINT!r}.")


def main() -> int:
    port_name = find_port()
    print(f"Xboard-Port: {port_name!r}")
    print(f"\n>>> Drehe Poti 1, 2, 3, ... 16 in physikalischer Reihenfolge.")
    print(f"    Oben 1-8 (links nach rechts), unten 9-16 (links nach rechts).")
    print(f"    ~3-4 Sekunden pro Poti, langsam und vollstaendig.")
    print(f"    Capture: {CAPTURE_SECONDS}s\n")

    cc_first_seen: dict[tuple[int, int], float] = {}  # (channel, cc) → first timestamp
    cc_count: dict[tuple[int, int], int] = defaultdict(int)

    t0 = time.monotonic()
    with mido.open_input(port_name) as inp:
        while time.monotonic() - t0 < CAPTURE_SECONDS:
            msg = inp.poll()
            if msg is None:
                time.sleep(0.005)
                continue
            t = time.monotonic() - t0
            if msg.type == "control_change":
                key = (msg.channel, msg.control)
                if key not in cc_first_seen:
                    cc_first_seen[key] = t
                    print(f"  +{t:5.2f}s  NEU  ch={msg.channel}  cc={msg.control}")
                cc_count[key] += 1

    print(f"\n=== Zusammenfassung ===\n")
    print(f"{len(cc_first_seen)} unterschiedliche (ch, cc) Kombinationen erfasst")
    print(f"\nGeordnete Liste (Reihenfolge des ersten Auftretens):\n")
    sorted_items = sorted(cc_first_seen.items(), key=lambda x: x[1])
    print(f"{'#':>3}  {'physisch':>10}  {'channel':>7}  {'cc':>3}  {'first @':>8}  {'count':>6}")
    for i, ((ch, cc), t) in enumerate(sorted_items, 1):
        physisch = f"Poti {i}" if i <= 16 else f"#{i}"
        print(f"{i:>3}  {physisch:>10}  {ch:>7}  {cc:>3}  {t:>6.2f}s  {cc_count[(ch,cc)]:>6}")

    print(f"\n=== YAML-Mapping-Vorschlag ===\n")
    print(f"# runtime/midi_bridge/configs/xboard49.yaml")
    print(f"xboard:")
    print(f"  port_name_hint: 'Xboard'")
    print(f"  potis:")
    for i, ((ch, cc), _) in enumerate(sorted_items, 1):
        if i <= 16:
            print(f"    {i}: {{ ch: {ch}, cc: {cc} }}    # Poti {i}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
