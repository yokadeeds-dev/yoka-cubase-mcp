"""
Closed-Loop-Controller — Sender + Listener + StateMirror in EINEM Prozess.

Pattern:
    with ClosedLoopController(in_port, out_port) as cl:
        cl.start_listening()                              # Background-Thread
        ok = cl.send_and_verify(
            send=lambda s: s.select_track(2),
            predicate=lambda snap: snap["active_track"] and snap["active_track"]["index"] == 3,
            timeout_ms=500,
        )
        # ok=True wenn StateMirror innerhalb 500ms den erwarteten Stand zeigt.

Vorteil gegenüber CLI: kein File-Round-Trip via state.json — direkt In-Memory-State.
Wird ab Etappe 4 (MCP-Server) das Backbone für jeden Tool-Call mit Verifikation.
"""

from __future__ import annotations

import threading
import time
from typing import Any, Callable

import mido

from runtime.mackie.listener import resolve_port
from runtime.mackie.parser import parse_message
from runtime.mackie.sender import MackieSender
from runtime.mackie.state import StateMirror


Predicate = Callable[[dict[str, Any]], bool]


class ClosedLoopController:
    """
    Hält Listener-Input-Port + Sender-Output-Port + StateMirror.
    Listener läuft im Background-Thread und füttert den State.
    """

    def __init__(
        self,
        listener_port: str,
        sender_port: str,
        daw: str = "cubase",
    ) -> None:
        self._state = StateMirror(daw=daw)
        self._listener_port_name = resolve_port(listener_port)
        self._sender = MackieSender(sender_port)
        self._listener_input: mido.ports.BaseInput | None = None
        self._thread: threading.Thread | None = None
        self._stop_event = threading.Event()

    @property
    def state(self) -> StateMirror:
        return self._state

    @property
    def sender(self) -> MackieSender:
        return self._sender

    def start_listening(self) -> None:
        if self._thread is not None and self._thread.is_alive():
            return
        self._listener_input = mido.open_input(self._listener_port_name)
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._listener_loop, daemon=True, name="mackie-listener")
        self._thread.start()
        # kurzer Spin damit der Listener wirklich offen ist, bevor wir senden
        time.sleep(0.05)

    def stop(self) -> None:
        self._stop_event.set()
        if self._listener_input is not None:
            try:
                self._listener_input.close()
            except Exception:
                pass
            self._listener_input = None
        if self._thread is not None:
            self._thread.join(timeout=1.0)
            self._thread = None
        self._sender.close()

    def __enter__(self) -> "ClosedLoopController":
        return self

    def __exit__(self, *exc: Any) -> None:
        self.stop()

    def _listener_loop(self) -> None:
        assert self._listener_input is not None
        # poll() statt blocking iteration, damit stop_event ankommt
        while not self._stop_event.is_set():
            for msg in self._listener_input.iter_pending():
                event = parse_message(msg)
                self._state.apply_event(event)
            time.sleep(0.005)  # 5 ms tick

    # ---------- Verifikation ----------

    def wait_for(self, predicate: Predicate, timeout_ms: int = 500, poll_ms: int = 10) -> bool:
        """
        Pollt den State-Snapshot bis predicate(snap) True wird oder Timeout.
        """
        deadline = time.monotonic() + timeout_ms / 1000.0
        while time.monotonic() < deadline:
            if predicate(self._state.snapshot()):
                return True
            time.sleep(poll_ms / 1000.0)
        return predicate(self._state.snapshot())  # ein letzter Versuch

    def send_and_verify(
        self,
        send: Callable[[MackieSender], None],
        predicate: Predicate,
        timeout_ms: int = 500,
    ) -> dict[str, Any]:
        """
        Führt `send(sender)` aus und wartet, bis `predicate(snap)` True ist.

        Returns Result-Dict mit:
            ok:                    bool — predicate erfüllt innerhalb timeout
            verified:              bool — ok && consistent
            was_already_satisfied: bool — predicate war schon vor dem Send wahr
                                          (idempotente Operation, DAW musste nicht echoen)
            snapshot:              letzter geprüfter Snapshot
            elapsed_ms:            int
            timeout_ms:            int
        """
        # Pre-Snapshot-Diff: war predicate bereits wahr, BEVOR wir senden?
        # Dann gilt der State als erreicht, auch wenn die DAW nicht mehr echoed.
        # Das fixt den Cubase-No-Op-Echo-Quirk: wenn du schon im Track-Mode bist
        # und set_mode("track") aufrufst, sendet Cubase keinen Echo zurück.
        pre_snap = self._state.snapshot()
        was_already = predicate(pre_snap)

        send(self._sender)
        t0 = time.monotonic()
        ok = self.wait_for(predicate, timeout_ms=timeout_ms)
        elapsed_ms = int((time.monotonic() - t0) * 1000)
        snap = self._state.snapshot()
        return {
            "ok": ok,
            "verified": ok,
            "was_already_satisfied": was_already,
            "snapshot": snap,
            "elapsed_ms": elapsed_ms,
            "timeout_ms": timeout_ms,
        }

    # ---------- Convenience ----------

    def select_track(self, channel: int, timeout_ms: int = 500) -> dict[str, Any]:
        return self.send_and_verify(
            send=lambda s: s.select_track(channel),
            predicate=lambda snap: (
                snap.get("active_track") is not None
                and snap["active_track"]["index"] == channel + 1
            ),
            timeout_ms=timeout_ms,
        )

    def set_mode(self, mode: str, timeout_ms: int = 500) -> dict[str, Any]:
        return self.send_and_verify(
            send=lambda s: s.set_mode(mode),
            predicate=lambda snap: snap.get("mode") == mode,
            timeout_ms=timeout_ms,
        )

    def transport(self, action: str, timeout_ms: int = 500) -> dict[str, Any]:
        # action_map mirrors state.py: "play"/"stop"/"record" landen 1:1 in transport.state
        return self.send_and_verify(
            send=lambda s: s.transport(action),
            predicate=lambda snap: snap["transport"]["state"] == action,
            timeout_ms=timeout_ms,
        )

    def bank_shift(self, direction: str, channel_step: bool = False) -> dict[str, Any]:
        """
        Bank-Shift (8 Tracks) oder Channel-Shift (1 Track).
        Cubase sendet keinen direkten "Bank-Position-Echo" — wir feuern den Button
        und exposen den Send. Verifikation indirekt: nach kurzem Wait sollten neue
        Track-Namen via LCD-Push reinkommen, was die Bank wechselte.
        direction: 'left' | 'right'
        """
        if direction not in ("left", "right"):
            raise ValueError(f"direction must be 'left' or 'right', got {direction!r}")

        # Pre-Snapshot für Diff-Vergleich (LCD-State sollte sich ändern)
        pre = self._state.snapshot()
        pre_lcd = tuple(t["name"] + t["name_lower_lcd"] for t in pre["tracks"])

        send_fn = (
            (lambda s: s.channel_left() if direction == "left" else s.channel_right())
            if channel_step
            else (lambda s: s.bank_left() if direction == "left" else s.bank_right())
        )
        send_fn(self._sender)

        # Bis zu 800 ms warten, ob sich der LCD-Inhalt ändert
        t0 = time.monotonic()
        timeout = t0 + 0.8
        changed = False
        while time.monotonic() < timeout:
            snap = self._state.snapshot()
            now_lcd = tuple(t["name"] + t["name_lower_lcd"] for t in snap["tracks"])
            if now_lcd != pre_lcd:
                changed = True
                break
            time.sleep(0.02)

        snap = self._state.snapshot()
        return {
            "ok": True,  # Send ging immer durch
            "verified": changed,  # Display hat sich geändert
            "snapshot": snap,
            "elapsed_ms": int((time.monotonic() - t0) * 1000),
            "timeout_ms": 800,
        }
