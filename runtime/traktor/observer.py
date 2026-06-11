"""
Traktor-Bridge — Observer (MIDI-Listener + Polling-Sender für Deck-State).

Architektur (Input→Output Round-Trip):
  1. Observer sendet periodisch CCs auf MACKIE_TO_CUBASE (Input-Mappings)
  2. Traktor empfängt Input → State ändert sich → Output-Mapping feuert
  3. Observer empfängt Output-CCs auf MACKIE_FROM_CUBASE → befüllt TraktorMirror

Ports:
  IN  (Python→Traktor): MACKIE_TO_CUBASE   — Input-Mappings (CC50-55)
  OUT (Traktor→Python): MACKIE_FROM_CUBASE  — Output-Mappings (CC1-10)

CLI:
    python -m runtime.traktor.observer --list-ports
    python -m runtime.traktor.observer
    python -m runtime.traktor.observer --json-out /tmp/traktor.json
"""

from __future__ import annotations

import argparse
import json
import sys
import threading
import time
from pathlib import Path

import mido

from runtime.traktor.state import TraktorMirror

# Default port names (IAC sub-ports)
DEFAULT_IN_PORT = "MACKIE_FROM_CUBASE"   # Traktor Output → Python
DEFAULT_OUT_PORT = "MACKIE_TO_CUBASE"    # Python → Traktor Input

# Polling CCs: these Input-Mappings trigger Output-Mappings in Traktor
# (channel_0based, cc, description)
POLL_CCS = [
    # Deck A (Ch1)
    (0, 50, "Vol A"),
    (0, 51, "EQ Hi A"),
    (0, 52, "EQ Mid A"),
    (0, 53, "EQ Lo A"),
    (0, 54, "Filter A"),
    (0, 55, "XFader"),
    # Deck B (Ch2)
    (1, 50, "Vol B"),
    (1, 51, "EQ Hi B"),
    (1, 52, "EQ Mid B"),
    (1, 53, "EQ Lo B"),
    (1, 54, "Filter B"),
    (1, 55, "XFader B"),
]


def _resolve_port(requested: str, direction: str = "input") -> str:
    if direction == "input":
        available = [p for p in mido.get_input_names() if p is not None]
    else:
        available = [p for p in mido.get_output_names() if p is not None]

    if requested in available:
        return requested
    req_lower = requested.lower()
    # Suffix-Match (macOS IAC-Treiber-Prefix)
    matches = [n for n in available if n.lower().endswith(req_lower)]
    if len(matches) == 1:
        return matches[0]
    if len(matches) > 1:
        raise ValueError(f"Mehrere Treffer für {requested!r}: {matches}")
    matches = [n for n in available if req_lower in n.lower()]
    if len(matches) == 1:
        return matches[0]
    raise ValueError(f"Kein Port für {requested!r}. Verfügbar: {available}")


def _poll_once(out_port: mido.ports.BaseOutput) -> None:
    """Einmaliger Snapshot-Poll: sendet 0 dann 127 pro CC um Output zu triggern."""
    for ch, cc, _desc in POLL_CCS:
        out_port.send(mido.Message("control_change", channel=ch, control=cc, value=0))
    time.sleep(0.05)
    for ch, cc, _desc in POLL_CCS:
        out_port.send(mido.Message("control_change", channel=ch, control=cc, value=127))


def _poll_loop(out_port: mido.ports.BaseOutput, interval: float, stop: threading.Event) -> None:
    """Periodisch Polling-CCs senden, damit Traktor Output-Mappings feuert."""
    # Alternating values to ensure state-change triggers
    toggle = False
    while not stop.is_set():
        val = 127 if toggle else 0
        for ch, cc, _desc in POLL_CCS:
            out_port.send(mido.Message("control_change", channel=ch, control=cc, value=val))
        toggle = not toggle
        stop.wait(interval)


def snapshot(
    in_port_name: str = DEFAULT_IN_PORT,
    out_port_name: str = DEFAULT_OUT_PORT,
    timeout: float = 2.0,
) -> dict:
    """Einmaliger Snapshot: pollt Traktor einmal und gibt DeckState zurück."""
    mirror = TraktorMirror()
    full_in = _resolve_port(in_port_name, "input")
    full_out = _resolve_port(out_port_name, "output")

    with mido.open_input(full_in) as inp, mido.open_output(full_out) as out:
        # Einmal pollen
        _poll_once(out)
        # Antworten sammeln
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            msg = inp.poll()
            if msg is None:
                time.sleep(0.01)
                continue
            mirror.apply_message(msg)
    return mirror.snapshot()


def run(
    in_port_name: str,
    out_port_name: str | None = None,
    json_out: Path | None = None,
    write_every_ms: int = 200,
    poll_interval: float = 0.5,
    no_poll: bool = False,
) -> None:
    mirror = TraktorMirror()
    full_in = _resolve_port(in_port_name, "input")
    print(f"Traktor-Observer: empfange auf {full_in!r}", flush=True)

    stop = threading.Event()
    poll_thread = None
    out_port = None

    if not no_poll and out_port_name:
        full_out = _resolve_port(out_port_name, "output")
        print(f"Traktor-Observer: sende Polling auf {full_out!r} (alle {poll_interval}s)", flush=True)
        out_port = mido.open_output(full_out)
        poll_thread = threading.Thread(
            target=_poll_loop,
            args=(out_port, poll_interval, stop),
            daemon=True,
        )
        poll_thread.start()

    last_write = time.monotonic()

    try:
        with mido.open_input(full_in) as inp:
            print("Observer läuft. Ctrl+C zum Stoppen.\n", flush=True)
            for msg in inp:
                event = mirror.apply_message(msg)
                if event:
                    _print_event(event, mirror)

                if json_out is not None:
                    now = time.monotonic()
                    if (now - last_write) * 1000 >= write_every_ms:
                        _write_json(json_out, mirror.snapshot())
                        last_write = now
    finally:
        stop.set()
        if poll_thread:
            poll_thread.join(timeout=2)
        if out_port:
            out_port.close()


def _print_event(event: dict, mirror: TraktorMirror) -> None:
    kind = event.get("kind")
    deck = event.get("deck", "?")
    if kind == "cc":
        param = event["param"]
        val = event["value"]
        # Interessante Events ausgeben
        if param in ("play", "cue_active", "loop_active", "sync_active"):
            snap = mirror.get_deck(deck) or {}
            if param == "play":
                state = "▶ PLAY" if snap.get("play") else "■ STOP"
                print(f"[DECK {deck}] {state}", flush=True)
            else:
                on_off = "ON" if val >= 64 else "off"
                print(f"[DECK {deck}] {param}={on_off}", flush=True)
        elif param in ("volume", "eq_hi", "eq_mid", "eq_lo", "filter", "crossfader"):
            snap = mirror.get_deck(deck) or {}
            print(f"[DECK {deck}] {param}={snap.get(param, val)}", flush=True)
    elif kind == "beat":
        print(f"[DECK {deck}] ♩ beat", flush=True)


def _write_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, indent=2))
    tmp.replace(path)


def main() -> int:
    p = argparse.ArgumentParser(description="Traktor-Observer — MIDI-Deck-State-Listener mit Polling")
    p.add_argument("--in-port", default=DEFAULT_IN_PORT,
                   help=f"MIDI-Eingangsport (default: {DEFAULT_IN_PORT})")
    p.add_argument("--out-port", default=DEFAULT_OUT_PORT,
                   help=f"MIDI-Ausgangsport für Polling (default: {DEFAULT_OUT_PORT})")
    p.add_argument("--no-poll", action="store_true",
                   help="Polling deaktivieren (nur passiv lauschen)")
    p.add_argument("--poll-interval", type=float, default=0.5,
                   help="Polling-Intervall in Sekunden (default: 0.5)")
    p.add_argument("--snapshot", action="store_true",
                   help="Einmaliger Snapshot (pollt einmal, gibt JSON aus, beendet)")
    p.add_argument("--list-ports", action="store_true")
    p.add_argument("--json-out", type=Path)
    p.add_argument("--write-every-ms", type=int, default=200)
    args = p.parse_args()

    if args.list_ports:
        print("Input-Ports:")
        for n in mido.get_input_names():
            if n is not None:
                print(f"  {n}")
        print("Output-Ports:")
        for n in mido.get_output_names():
            if n is not None:
                print(f"  {n}")
        return 0

    if args.snapshot:
        data = snapshot(args.in_port, args.out_port)
        print(json.dumps(data, indent=2))
        if args.json_out:
            _write_json(args.json_out, data)
        return 0

    try:
        run(
            in_port_name=args.in_port,
            out_port_name=args.out_port,
            json_out=args.json_out,
            write_every_ms=args.write_every_ms,
            poll_interval=args.poll_interval,
            no_poll=args.no_poll,
        )
    except KeyboardInterrupt:
        print("\nObserver gestoppt.")
        return 0
    except (OSError, ValueError) as e:
        print(f"FEHLER: {e}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
