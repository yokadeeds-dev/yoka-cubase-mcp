"""
Live-Smoke-Test für ClosedLoopController gegen Cubase.

Voraussetzung:
- loopMIDI läuft mit MACKIE_FROM_CUBASE / MACKIE_TO_CUBASE
- Cubase ist offen mit Mackie Control auf diesen Ports

Aufruf:
    python -m tests.selftests.closedloop_smoketest

Kein Selftest im engen Sinn (braucht echtes Cubase) — eher ein End-to-End-Test.
"""

from __future__ import annotations

import sys
from pathlib import Path
import time

ROOT = Path(__file__).resolve().parent.parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from runtime.mackie.closedloop import ClosedLoopController  # noqa: E402


def main() -> int:
    print("Closed-Loop Smoke-Test — sender + listener im selben Prozess.\n")

    with ClosedLoopController(
        listener_port="MACKIE_FROM_CUBASE",
        sender_port="MACKIE_TO_CUBASE",
    ) as cl:
        cl.start_listening()
        print(f"Listener offen auf {cl._listener_port_name!r}, sender offen auf {cl.sender.port_name!r}\n")

        results = []

        # 1) force track mode
        r = cl.set_mode("track", timeout_ms=800)
        print(f"  set_mode('track')      verified={r['verified']:1}  elapsed={r['elapsed_ms']:>4} ms")
        results.append(("set_mode track", r["verified"]))

        # 2) cycle to pan, back to track
        r = cl.set_mode("pan", timeout_ms=800)
        print(f"  set_mode('pan')        verified={r['verified']:1}  elapsed={r['elapsed_ms']:>4} ms")
        results.append(("set_mode pan", r["verified"]))

        r = cl.set_mode("track", timeout_ms=800)
        print(f"  set_mode('track')      verified={r['verified']:1}  elapsed={r['elapsed_ms']:>4} ms")
        results.append(("set_mode track #2", r["verified"]))

        # 3) select track 1, 2, 3
        for ch in range(3):
            r = cl.select_track(ch, timeout_ms=800)
            active = r["snapshot"].get("active_track", {})
            name = active.get("name", "") if active else ""
            print(f"  select_track({ch})       verified={r['verified']:1}  elapsed={r['elapsed_ms']:>4} ms  active_name={name!r}")
            results.append((f"select_track {ch}", r["verified"]))

        # 4) transport play, then stop
        r = cl.transport("play", timeout_ms=800)
        print(f"  transport('play')      verified={r['verified']:1}  elapsed={r['elapsed_ms']:>4} ms")
        results.append(("transport play", r["verified"]))

        time.sleep(0.3)

        r = cl.transport("stop", timeout_ms=800)
        print(f"  transport('stop')      verified={r['verified']:1}  elapsed={r['elapsed_ms']:>4} ms")
        results.append(("transport stop", r["verified"]))

        # 5) zurück auf track 1
        r = cl.select_track(0, timeout_ms=800)
        print(f"  select_track(0) final  verified={r['verified']:1}  elapsed={r['elapsed_ms']:>4} ms")
        results.append(("select_track 0 final", r["verified"]))

        print()
        ok_count = sum(1 for _, ok in results if ok)
        print(f"Verified: {ok_count}/{len(results)}")
        for name, ok in results:
            mark = "OK  " if ok else "FAIL"
            print(f"  [{mark}] {name}")

        return 0 if ok_count == len(results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
