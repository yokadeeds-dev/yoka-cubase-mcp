"""
Plugin-Mode-Observer — bringt Cubase in den Plugin-Mode und loggt alles roh,
was Cubase auf MACKIE_FROM_CUBASE pusht. Ziel: Schema für active_plugin
empirisch ermitteln.

Voraussetzung: Cubase offen, eine Spur mit mindestens einem Insert-Plugin,
diese Spur selektiert.

Aufruf:
    python -m tests.selftests.plugin_mode_observer
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from runtime.mackie.closedloop import ClosedLoopController  # noqa: E402

CAPTURE_SECONDS = 6


def main() -> int:
    print("Plugin-Mode-Observer — captures Cubase Plugin-Mode-Output.\n")

    with ClosedLoopController(
        listener_port="MACKIE_FROM_CUBASE",
        sender_port="MACKIE_TO_CUBASE",
    ) as cl:
        cl.start_listening()
        cl.state.start_session_log()
        time.sleep(0.2)  # listener warm-up

        # Pre-state
        pre = cl.state.snapshot()
        print(f"Pre-State: mode={pre.get('mode')!r}, active={pre.get('active_track')}")

        print("\n>>> Sende set_mode('plugin') ...")
        result = cl.set_mode("plugin", timeout_ms=1500)
        print(f"  Result: verified={result['verified']}, was_already={result.get('was_already_satisfied')}, elapsed={result['elapsed_ms']}ms")

        print(f"\n>>> Capture {CAPTURE_SECONDS}s alles, was Cubase pusht ...")
        time.sleep(CAPTURE_SECONDS)

        # Snapshot
        snap = cl.state.snapshot()
        print("\n=== Final State ===")
        print(f"  mode:               {snap.get('mode')!r}")
        print(f"  two_char_display:   {snap.get('two_char_display')!r}")
        print(f"  active_track:       {snap.get('active_track')}")
        print(f"  position_smpte:     {snap['transport'].get('position_smpte')!r}")

        print("\n=== LCD-Reihen (raw, je 56 chars) ===")
        # Wir holen die internen Buffer für die Anzeige (state.py hält sie privat)
        row1 = "".join(cl.state._lcd_row1)
        row2 = "".join(cl.state._lcd_row2)
        print(f"  row1: {row1!r}")
        print(f"  row2: {row2!r}")

        print("\n=== Track-Strips (jeweils 7 chars) ===")
        for i, t in enumerate(snap["tracks"]):
            print(f"  ch{i}: r1={t['name']!r:10} r2={t['name_lower_lcd']!r:10}  resolved={t['name_resolved']!r}")

        print("\n=== Session-Log (alle Events) ===")
        log = cl.state.get_session_log()
        kinds_count: dict[str, int] = {}
        for ev in log:
            kinds_count[ev["kind"]] = kinds_count.get(ev["kind"], 0) + 1
        print(f"  Total: {len(log)} Events. Kinds:")
        for k, c in sorted(kinds_count.items(), key=lambda x: -x[1]):
            print(f"    {k:25} {c:>5}")

        # Zurück auf track-mode aus Höflichkeit
        print("\n>>> Restore: set_mode('track')")
        cl.set_mode("track", timeout_ms=800)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
