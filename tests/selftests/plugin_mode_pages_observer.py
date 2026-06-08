"""
Plugin-Mode-Pages-Observer — navigiert durch Plugin-Parameter-Pages und
loggt was Cubase auf jeder Page pusht.

Strategie:
- in plugin-mode wechseln
- initialen Snapshot loggen (Page 1 = Übersicht)
- channel_right senden (typischer Page-Navigator in Plugin-Mode)
- erneut Snapshot
- bank_right senden (alternativer Navigator)
- erneut Snapshot
- nach 3 Pages: Restore auf track-mode

Voraussetzung: Cubase, Plugin geladen, Track selektiert.
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from runtime.mackie.closedloop import ClosedLoopController  # noqa: E402


def dump_lcd(cl: ClosedLoopController, label: str) -> None:
    snap = cl.state.snapshot()
    row1 = "".join(cl.state._lcd_row1)
    row2 = "".join(cl.state._lcd_row2)
    print(f"\n--- {label} ---")
    print(f"  mode: {snap.get('mode')!r}  2char: {snap.get('two_char_display')!r}")
    print(f"  row1 raw: {row1!r}")
    print(f"  row2 raw: {row2!r}")
    print(f"  Strips:")
    for i, t in enumerate(snap["tracks"]):
        print(f"    ch{i}: r1={t['name']!r:14} r2={t['name_lower_lcd']!r:14}")


def main() -> int:
    print("Plugin-Mode-Pages-Observer\n")

    with ClosedLoopController(
        listener_port="MACKIE_FROM_CUBASE",
        sender_port="MACKIE_TO_CUBASE",
    ) as cl:
        cl.start_listening()
        time.sleep(0.2)

        # Plugin-Mode aktivieren
        print(">>> set_mode('plugin')")
        cl.set_mode("plugin", timeout_ms=1000)
        time.sleep(0.8)
        dump_lcd(cl, "Page 1 (initial, after set_mode plugin)")

        # channel_right — typischer Page-Navigator in Plugin-Mode
        print("\n>>> channel_right (Page-Navigator)")
        cl.sender.channel_right()
        time.sleep(0.8)
        dump_lcd(cl, "After channel_right")

        # nochmal channel_right
        print("\n>>> channel_right #2")
        cl.sender.channel_right()
        time.sleep(0.8)
        dump_lcd(cl, "After channel_right #2")

        # bank_right — alternativer Navigator (möglicherweise Slot-Wechsel)
        print("\n>>> bank_right")
        cl.sender.bank_right()
        time.sleep(0.8)
        dump_lcd(cl, "After bank_right")

        # zurück auf track mode
        print("\n>>> Restore set_mode('track')")
        cl.set_mode("track", timeout_ms=800)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
