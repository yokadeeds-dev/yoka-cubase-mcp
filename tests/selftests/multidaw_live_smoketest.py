"""
Live-Cross-DAW-Test: ClosedLoopController gegen Cubase und Ableton parallel.

Voraussetzung:
- loopMIDI mit MACKIE_FROM_CUBASE / MACKIE_TO_CUBASE / MACKIE_FROM_ABLETON / MACKIE_TO_ABLETON
- Cubase 15 + Mackie Control auf cubase-Ports
- Ableton Live 12 + MackieControl auf ableton-Ports

Aufruf:
    python -m tests.selftests.multidaw_live_smoketest
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from runtime.mackie.closedloop import ClosedLoopController  # noqa: E402


DAW_CONFIGS = {
    "cubase":  {"listener": "MACKIE_FROM_CUBASE",  "sender": "MACKIE_TO_CUBASE"},
    "ableton": {"listener": "MACKIE_FROM_ABLETON", "sender": "MACKIE_TO_ABLETON"},
}


def run_per_daw_sequence(cl: ClosedLoopController, daw: str) -> list[tuple[str, bool, int]]:
    """Standard-Sequenz pro DAW. Returns Liste (label, verified, elapsed_ms)."""
    results: list[tuple[str, bool, int]] = []

    # 1) Force track-mode
    r = cl.set_mode("track", timeout_ms=800)
    results.append((f"{daw}: set_mode(track)", r["verified"], r["elapsed_ms"]))

    # 2) pan-mode (state-change → Echo erwartet)
    r = cl.set_mode("pan", timeout_ms=800)
    results.append((f"{daw}: set_mode(pan)", r["verified"], r["elapsed_ms"]))

    # 3) zurück auf track
    r = cl.set_mode("track", timeout_ms=800)
    results.append((f"{daw}: set_mode(track) #2", r["verified"], r["elapsed_ms"]))

    # 4) select-track 0, 1, 2
    for ch in range(3):
        r = cl.select_track(ch, timeout_ms=800)
        active = r["snapshot"].get("active_track") or {}
        name = active.get("name", "")
        results.append((f"{daw}: select_track({ch}) name={name!r}", r["verified"], r["elapsed_ms"]))

    return results


def main() -> int:
    print("Multi-DAW Live-Smoketest — Cubase und Ableton parallel.\n")

    # Beide Controller öffnen
    controllers: dict[str, ClosedLoopController] = {}
    try:
        for daw, cfg in DAW_CONFIGS.items():
            try:
                cl = ClosedLoopController(
                    listener_port=cfg["listener"],
                    sender_port=cfg["sender"],
                    daw=daw,
                )
                cl.start_listening()
                controllers[daw] = cl
                print(f"  [OK] {daw:8} — listener {cl._listener_port_name!r}, sender {cl.sender.port_name!r}")
            except Exception as e:
                print(f"  [FAIL] {daw}: {type(e).__name__}: {e}")
        print()

        if not controllers:
            print("Kein Controller offen. Abbruch.")
            return 1

        # Pro DAW Standard-Sequenz
        all_results: list[tuple[str, bool, int]] = []
        for daw, cl in controllers.items():
            print(f"--- {daw.upper()} ---")
            results = run_per_daw_sequence(cl, daw)
            for label, verified, elapsed in results:
                mark = "OK  " if verified else "FAIL"
                print(f"  [{mark}] {elapsed:>4} ms  {label}")
            all_results.extend(results)
            print()

        # Cross-DAW: gleichzeitig play auf beiden, dann gleichzeitig stop
        if len(controllers) >= 2:
            print("--- CROSS-DAW SYNC TEST ---")
            print("Sende play auf alle DAWs (mit minimalem Versatz)...")
            t0 = time.monotonic()
            for cl in controllers.values():
                cl.sender.transport_play()
            t1 = time.monotonic()
            send_ms = int((t1 - t0) * 1000)
            print(f"  Alle play-Befehle gesendet in {send_ms} ms")

            time.sleep(0.5)

            for daw, cl in controllers.items():
                snap = cl.state.snapshot()
                state = snap["transport"]["state"]
                print(f"  {daw:8} transport.state nach play: {state!r}")

            print("Sende stop auf alle DAWs...")
            for cl in controllers.values():
                cl.sender.transport_stop()
            time.sleep(0.5)

            for daw, cl in controllers.items():
                snap = cl.state.snapshot()
                state = snap["transport"]["state"]
                print(f"  {daw:8} transport.state nach stop: {state!r}")
            print()

        # Zusammenfassung
        ok_count = sum(1 for _, v, _ in all_results if v)
        total = len(all_results)
        print(f"Verified: {ok_count}/{total} per-DAW Operations.")
        return 0 if ok_count == total else 1

    finally:
        for cl in controllers.values():
            cl.stop()


if __name__ == "__main__":
    raise SystemExit(main())
