"""
Mackie-Sender — schreibt MIDI-Messages auf einen MIDI-Output-Port.

Architektur:
- Pure functions `make_*_message(...)` bauen mido-Messages, ohne I/O.
  → testbar ohne Port, parser-roundtrip-fähig.
- Klasse `MackieSender` hält den geöffneten Port und ruft die Pure-Funcs.
- CLI: einzelne Befehle für manuellen Live-Test gegen Cubase.

Aufruf (CLI):
    python -m runtime.mackie.sender --list-ports
    python -m runtime.mackie.sender --port MACKIE_TO_CUBASE select 1
    python -m runtime.mackie.sender --port MACKIE_TO_CUBASE mode track
    python -m runtime.mackie.sender --port MACKIE_TO_CUBASE transport play
    python -m runtime.mackie.sender --port MACKIE_TO_CUBASE fader 0 12286
    python -m runtime.mackie.sender --port MACKIE_TO_CUBASE encoder 3 +1 --speed 2
    python -m runtime.mackie.sender --port MACKIE_TO_CUBASE force-track-mode
"""

from __future__ import annotations

import argparse
import sys
import time
from typing import Any

import mido

from runtime.mackie.parser import SPEC


# ---------- Pure message builders (ohne I/O) ----------

def make_button_press_messages(note: int) -> tuple[mido.Message, mido.Message]:
    """Mackie-Buttons: Note-On Velocity 127 = press, Velocity 0 = release."""
    return (
        mido.Message("note_on", note=note, velocity=127),
        mido.Message("note_on", note=note, velocity=0),
    )


def make_select_messages(channel: int, spec: dict[str, Any] = SPEC) -> tuple[mido.Message, mido.Message]:
    if not 0 <= channel < 8:
        raise ValueError(f"channel must be 0..7, got {channel}")
    note = spec["buttons"]["select"]["start"] + channel
    return make_button_press_messages(note)


def make_mode_messages(mode: str, spec: dict[str, Any] = SPEC) -> tuple[mido.Message, mido.Message]:
    modes = spec["buttons"]["mode"]
    if mode not in modes:
        raise ValueError(f"mode must be one of {sorted(modes.keys())}, got {mode!r}")
    return make_button_press_messages(modes[mode])


def make_transport_messages(action: str, spec: dict[str, Any] = SPEC) -> tuple[mido.Message, mido.Message]:
    actions = spec["buttons"]["transport"]
    if action not in actions:
        raise ValueError(f"transport action must be one of {sorted(actions.keys())}, got {action!r}")
    return make_button_press_messages(actions[action])


def make_bank_messages(direction: str, spec: dict[str, Any] = SPEC) -> tuple[mido.Message, mido.Message]:
    """direction: 'left' (8 Tracks zurück) | 'right' (8 Tracks vor)."""
    if direction == "left":
        return make_button_press_messages(spec["buttons"]["bank_left"])
    if direction == "right":
        return make_button_press_messages(spec["buttons"]["bank_right"])
    raise ValueError(f"direction must be 'left' or 'right', got {direction!r}")


def make_channel_messages(direction: str, spec: dict[str, Any] = SPEC) -> tuple[mido.Message, mido.Message]:
    """direction: 'left' (1 Track zurück) | 'right' (1 Track vor)."""
    if direction == "left":
        return make_button_press_messages(spec["buttons"]["channel_left"])
    if direction == "right":
        return make_button_press_messages(spec["buttons"]["channel_right"])
    raise ValueError(f"direction must be 'left' or 'right', got {direction!r}")


def make_fader_message(channel: int, value14: int) -> mido.Message:
    """value14: 0..16383, Mackie 14-Bit-Auflösung. channel 8 = Master-Fader."""
    if not 0 <= channel <= 8:
        raise ValueError(f"channel must be 0..8 (8=master), got {channel}")
    v = max(0, min(16383, value14))
    pitch = v - 8192  # mido normalisiert -8192..+8191
    return mido.Message("pitchwheel", channel=channel, pitch=pitch)


def make_encoder_message(encoder: int, direction: int, speed: int = 1, spec: dict[str, Any] = SPEC) -> mido.Message:
    """direction: +1=CW, -1=CCW. speed: 1..63 (Mackie-Inkrement)."""
    if not 0 <= encoder < 8:
        raise ValueError(f"encoder must be 0..7, got {encoder}")
    if direction not in (-1, 1):
        raise ValueError(f"direction must be -1 or +1, got {direction}")
    cc = spec["encoders"]["cc_start"] + encoder
    val = max(1, min(63, speed))
    if direction < 0:
        val |= spec["encoders"]["direction_mask"]
    return mido.Message("control_change", control=cc, value=val)


# ---------- Port-Resolver ----------

def list_output_ports() -> list[str]:
    return list(mido.get_output_names())


def resolve_output_port(requested: str) -> str:
    """Wie listener.resolve_port, aber für Output-Ports.
    Unterstützt Exact-, Prefix-, Suffix- und Substring-Match.
    None-Einträge (defekte Ports) werden gefiltert.
    """
    available = [p for p in mido.get_output_names() if p is not None]
    if requested in available:
        return requested
    req_lower = requested.lower()
    matches = [n for n in available if n.lower().startswith(req_lower)]
    if len(matches) == 1:
        return matches[0]
    if len(matches) > 1:
        raise ValueError(f"Mehrere Output-Prefix-Treffer für {requested!r}: {matches}")
    matches = [n for n in available if n.lower().endswith(req_lower)]
    if len(matches) == 1:
        return matches[0]
    if len(matches) > 1:
        raise ValueError(f"Mehrere Output-Suffix-Treffer für {requested!r}: {matches}")
    matches = [n for n in available if req_lower in n.lower()]
    if len(matches) == 1:
        return matches[0]
    if len(matches) > 1:
        raise ValueError(f"Mehrere Output-Substring-Treffer für {requested!r}: {matches}")
    raise ValueError(f"Kein Output-Port gefunden für {requested!r}. Verfügbar: {available}")


# ---------- Sender-Klasse ----------

class MackieSender:
    """
    Hält einen offenen MIDI-Output-Port und sendet Mackie-konforme Befehle.
    Context-Manager-tauglich: schließt den Port am Ende.
    """

    DEFAULT_BUTTON_HOLD_MS = 50

    def __init__(self, port_name: str, spec: dict[str, Any] = SPEC) -> None:
        self.spec = spec
        full = resolve_output_port(port_name)
        self._port = mido.open_output(full)
        self.port_name = full

    def close(self) -> None:
        if hasattr(self, "_port") and not self._port.closed:
            self._port.close()

    def __enter__(self) -> "MackieSender":
        return self

    def __exit__(self, *exc: Any) -> None:
        self.close()

    # --- Internals ---

    def _send(self, msg: mido.Message) -> None:
        self._port.send(msg)

    def _press_button(self, note: int, hold_ms: int | None = None) -> None:
        on, off = make_button_press_messages(note)
        self._send(on)
        time.sleep((hold_ms or self.DEFAULT_BUTTON_HOLD_MS) / 1000.0)
        self._send(off)

    # --- Public API ---

    def select_track(self, channel: int) -> None:
        on, off = make_select_messages(channel, self.spec)
        self._send(on)
        time.sleep(self.DEFAULT_BUTTON_HOLD_MS / 1000.0)
        self._send(off)

    def set_mode(self, mode: str) -> None:
        on, off = make_mode_messages(mode, self.spec)
        self._send(on)
        time.sleep(self.DEFAULT_BUTTON_HOLD_MS / 1000.0)
        self._send(off)

    def force_track_mode(self) -> None:
        """Convenience: bringt Cubase in den Track-Mode (row1 = Track-Names)."""
        self.set_mode("track")

    def transport(self, action: str) -> None:
        on, off = make_transport_messages(action, self.spec)
        self._send(on)
        time.sleep(self.DEFAULT_BUTTON_HOLD_MS / 1000.0)
        self._send(off)

    def transport_play(self) -> None:
        self.transport("play")

    def transport_stop(self) -> None:
        self.transport("stop")

    def transport_record(self) -> None:
        self.transport("record")

    def bank_left(self) -> None:
        on, off = make_bank_messages("left", self.spec)
        self._send(on)
        time.sleep(self.DEFAULT_BUTTON_HOLD_MS / 1000.0)
        self._send(off)

    def bank_right(self) -> None:
        on, off = make_bank_messages("right", self.spec)
        self._send(on)
        time.sleep(self.DEFAULT_BUTTON_HOLD_MS / 1000.0)
        self._send(off)

    def channel_left(self) -> None:
        on, off = make_channel_messages("left", self.spec)
        self._send(on)
        time.sleep(self.DEFAULT_BUTTON_HOLD_MS / 1000.0)
        self._send(off)

    def channel_right(self) -> None:
        on, off = make_channel_messages("right", self.spec)
        self._send(on)
        time.sleep(self.DEFAULT_BUTTON_HOLD_MS / 1000.0)
        self._send(off)

    def set_fader(self, channel: int, value14: int) -> None:
        self._send(make_fader_message(channel, value14))

    def turn_encoder(self, encoder: int, direction: int, speed: int = 1) -> None:
        self._send(make_encoder_message(encoder, direction, speed, self.spec))


# ---------- CLI ----------

def main() -> int:
    p = argparse.ArgumentParser(description="Mackie-Sender CLI (Etappe 3).")
    p.add_argument("--port", help="Output-Port-Name (z. B. MACKIE_TO_CUBASE).")
    p.add_argument("--list-ports", action="store_true", help="Verfügbare Output-Ports anzeigen.")

    sub = p.add_subparsers(dest="cmd")

    s_select = sub.add_parser("select", help="select_track(channel)")
    s_select.add_argument("channel", type=int, help="0..7")

    s_mode = sub.add_parser("mode", help="set_mode(mode)")
    s_mode.add_argument("mode", choices=["track", "send", "pan", "plugin", "eq", "instrument"])

    s_transport = sub.add_parser("transport", help="transport(action)")
    s_transport.add_argument("action", choices=["play", "stop", "record", "rewind", "fast_forward"])

    s_fader = sub.add_parser("fader", help="set_fader(channel, value14)")
    s_fader.add_argument("channel", type=int, help="0..8 (8=master)")
    s_fader.add_argument("value14", type=int, help="0..16383")

    s_encoder = sub.add_parser("encoder", help="turn_encoder(encoder, direction, speed)")
    s_encoder.add_argument("encoder", type=int, help="0..7")
    s_encoder.add_argument("direction", type=int, choices=[-1, 1])
    s_encoder.add_argument("--speed", type=int, default=1)

    sub.add_parser("force-track-mode", help="set_mode('track') — convenience")
    sub.add_parser("bank-left", help="Bank um 8 Tracks zurück")
    sub.add_parser("bank-right", help="Bank um 8 Tracks vor")
    sub.add_parser("channel-left", help="Selektion 1 Track zurück")
    sub.add_parser("channel-right", help="Selektion 1 Track vor")

    args = p.parse_args()

    if args.list_ports:
        for n in list_output_ports():
            print(n)
        return 0

    if not args.port:
        p.error("--port ist erforderlich (oder --list-ports)")
    if not args.cmd:
        p.error("Subcommand fehlt (select | mode | transport | fader | encoder | force-track-mode)")

    try:
        with MackieSender(args.port) as sender:
            if args.cmd == "select":
                sender.select_track(args.channel)
                print(f"select_track({args.channel}) gesendet auf {sender.port_name!r}")
            elif args.cmd == "mode":
                sender.set_mode(args.mode)
                print(f"set_mode({args.mode!r}) gesendet")
            elif args.cmd == "transport":
                sender.transport(args.action)
                print(f"transport({args.action!r}) gesendet")
            elif args.cmd == "fader":
                sender.set_fader(args.channel, args.value14)
                print(f"set_fader(channel={args.channel}, value14={args.value14}) gesendet")
            elif args.cmd == "encoder":
                sender.turn_encoder(args.encoder, args.direction, args.speed)
                print(f"turn_encoder(encoder={args.encoder}, direction={args.direction:+d}, speed={args.speed}) gesendet")
            elif args.cmd == "force-track-mode":
                sender.force_track_mode()
                print("force_track_mode gesendet (= mode-button 'track')")
            elif args.cmd == "bank-left":
                sender.bank_left()
                print("bank-left gesendet")
            elif args.cmd == "bank-right":
                sender.bank_right()
                print("bank-right gesendet")
            elif args.cmd == "channel-left":
                sender.channel_left()
                print("channel-left gesendet")
            elif args.cmd == "channel-right":
                sender.channel_right()
                print("channel-right gesendet")
    except (OSError, ValueError) as e:
        print(f"FEHLER: {e}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
