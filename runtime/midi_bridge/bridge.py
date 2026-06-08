"""
KI-Studio MIDI-Bridge — Xboard ↔ Cubase + KI-Input-Merger.

Architektur (erweitert 2026-05-07):
    Xboard Hardware ─────┐
                         ├──→ Bridge ──→ MACKIE_TO_CUBASE (Mackie-Encoder)
                         ├──→         ──→ XBOARD_BRIDGED  (Pass-Through)
    AI_INPUT (loopMIDI) ─┘                       ↑
                                                 KI sendet auch hierhin via
                                                 runtime.midi_bridge.send_cc

Beide Inputs (Xboard-Hardware + AI_INPUT-loopMIDI-Port) werden in zwei
parallelen Threads gehoert; deren Nachrichten gehen in die gleichen
Output-Ports (Mackie-Encoder bzw. Pass-Through).

Routing-Regeln:
  - Xboard Knoepfe 1-8 (CC 16-23 absolut): -> Mackie-Encoder via MACKIE_TO_CUBASE
  - Xboard alles andere: -> Pass-Through via XBOARD_BRIDGED
  - AI_INPUT alles: -> direkt Pass-Through via XBOARD_BRIDGED (Plugin-MIDI-Learn)

AI_INPUT ist optional. Wenn der Port nicht existiert (Yoka hat ihn noch nicht
in loopMIDI angelegt), laeuft die Bridge ohne diesen Pfad weiter — Backward-
Compatibility.

Aufruf:
    python -m runtime.midi_bridge.bridge
    python -m runtime.midi_bridge.bridge --ai-input-port AI_INPUT
    python -m runtime.midi_bridge.bridge --no-ai-input  # explizit deaktiviert
"""

from __future__ import annotations

import argparse
import sys
import threading
import time

import mido

from runtime.midi_bridge.xboard_to_mackie import (
    DEFAULT_XBOARD_TO_MACKIE_MAPPINGS,
    XboardBridgeState,
    is_xboard_knob_for_mackie,
    make_mackie_encoder_message,
)


# ASCII-Pfeil statt Unicode "→": cp1252-Konsolen-Robustheit.
_ARROW = "->"


def resolve_input_port(hint: str) -> str:
    """Findet einen Input-Port via Substring-Match."""
    available = [p for p in mido.get_input_names() if p is not None]
    if hint in available:
        return hint
    matches = [n for n in available if hint.lower() in n.lower()]
    if len(matches) == 1:
        return matches[0]
    if len(matches) > 1:
        raise ValueError(f"Mehrere Input-Treffer für {hint!r}: {matches}")
    raise ValueError(f"Kein Input-Port für {hint!r}. Verfügbar: {available}")


def resolve_output_port(hint: str) -> str:
    available = [p for p in mido.get_output_names() if p is not None]
    if hint in available:
        return hint
    matches = [n for n in available if hint.lower() in n.lower()]
    if len(matches) == 1:
        return matches[0]
    if len(matches) > 1:
        raise ValueError(f"Mehrere Output-Treffer für {hint!r}: {matches}")
    raise ValueError(f"Kein Output-Port für {hint!r}. Verfügbar: {available}")


def try_resolve_input_port(hint: str) -> str | None:
    """Wie resolve_input_port, aber returnt None statt Exception wenn nicht gefunden."""
    try:
        return resolve_input_port(hint)
    except ValueError:
        return None


def _xboard_handler(
    xboard_in_name: str,
    mackie_out_port: mido.ports.BaseOutput,
    pass_out_port: mido.ports.BaseOutput,
    out_lock: threading.Lock,
    state: XboardBridgeState,
    mappings: list,
    stop_event: threading.Event,
    verbose: bool,
) -> None:
    """Thread-Handler: Xboard-Input -> Mackie-Encoder + Pass-Through."""
    with mido.open_input(xboard_in_name) as inp:  # type: ignore[attr-defined]
        for msg in inp:
            if stop_event.is_set():
                break
            if msg.type == "control_change":
                m = is_xboard_knob_for_mackie(msg.control, mappings)
                if m is not None:
                    increment = state.update_and_compute_increment(msg.control, msg.value)
                    if increment is not None:
                        encoded = make_mackie_encoder_message(m.mackie_encoder_index, increment)
                        with out_lock:
                            mackie_out_port.send(encoded)
                        if verbose:
                            direction = "CCW" if (increment & 0x40) else "CW "
                            speed = increment & 0x3F
                            print(
                                f"  [Xboard] CC {msg.control} val={msg.value} {_ARROW} "
                                f"Mackie Enc {m.mackie_encoder_index} {direction} speed={speed}",
                                flush=True,
                            )
                    continue
                # Andere CCs durchreichen
                with out_lock:
                    pass_out_port.send(msg)
                if verbose:
                    print(f"  [Xboard] Pass-through CC {msg.control}={msg.value} (ch {msg.channel})", flush=True)
            else:
                # Notes, Pitchbend, etc. immer durchreichen
                with out_lock:
                    pass_out_port.send(msg)


def _ai_handler(
    ai_in_name: str,
    pass_out_port: mido.ports.BaseOutput,
    out_lock: threading.Lock,
    stop_event: threading.Event,
    verbose: bool,
) -> None:
    """Thread-Handler: AI_INPUT-Port -> Pass-Through (alle Messages)."""
    with mido.open_input(ai_in_name) as inp:  # type: ignore[attr-defined]
        for msg in inp:
            if stop_event.is_set():
                break
            # KI-Nachrichten gehen alle direkt zum Pass-Through.
            # Cubase MIDI-Spuren mit Input XBOARD_BRIDGED erhalten sie wie Xboard-Pass-Through.
            with out_lock:
                pass_out_port.send(msg)
            if verbose:
                if msg.type == "control_change":
                    print(
                        f"  [AI]     CC {msg.control}={msg.value} (ch {msg.channel}) {_ARROW} pass-through",
                        flush=True,
                    )
                else:
                    print(f"  [AI]     {msg.type} {_ARROW} pass-through", flush=True)


def run_bridge(
    xboard_port: str,
    mackie_port: str,
    pass_port: str,
    ai_input_port: str | None = "AI_INPUT",
    verbose: bool = True,
) -> None:
    """
    Bridge mit Xboard-Input und optionalem AI_INPUT-Port.

    Wenn ai_input_port None ist oder nicht in loopMIDI gefunden wird,
    laeuft die Bridge nur mit Xboard (backward-compatible).
    """
    state = XboardBridgeState()
    mappings = DEFAULT_XBOARD_TO_MACKIE_MAPPINGS

    in_name = resolve_input_port(xboard_port)
    mackie_out = resolve_output_port(mackie_port)
    pass_out = resolve_output_port(pass_port)

    ai_in_name = try_resolve_input_port(ai_input_port) if ai_input_port else None

    print(f"Bridge gestartet:")
    print(f"  Input  (Xboard):       {in_name!r}")
    if ai_in_name:
        print(f"  Input  (AI_INPUT):     {ai_in_name!r}  [KI-Send-Pfad aktiv]")
    else:
        if ai_input_port:
            print(f"  Input  (AI_INPUT):     NICHT GEFUNDEN ({ai_input_port!r}) — KI-Send-Pfad inaktiv")
            print(f"                          (Lege Port {ai_input_port!r} in loopMIDI an um KI-Send zu aktivieren)")
        else:
            print(f"  Input  (AI_INPUT):     deaktiviert (--no-ai-input)")
    print(f"  Mackie-Out (Cubase):   {mackie_out!r}")
    print(f"  Pass-Through (notes):  {pass_out!r}")
    print(f"  Mackie-Mappings: {len(mappings)} Knöpfe")
    for m in mappings:
        print(f"    Xboard CC {m.xboard_cc:>3}  {_ARROW}  Mackie Encoder {m.mackie_encoder_index} (CC {m.mackie_cc})")
    print(f"  Strg+C zum Stoppen.\n")

    stop_event = threading.Event()
    out_lock = threading.Lock()

    with mido.open_output(mackie_out) as mackie_out_port, \
         mido.open_output(pass_out) as pass_out_port:  # type: ignore[attr-defined]

        threads: list[threading.Thread] = []

        # Xboard-Thread immer starten
        t_xboard = threading.Thread(
            target=_xboard_handler,
            args=(in_name, mackie_out_port, pass_out_port, out_lock, state, mappings, stop_event, verbose),
            name="bridge-xboard",
            daemon=True,
        )
        t_xboard.start()
        threads.append(t_xboard)

        # AI-Thread nur wenn Port verfuegbar
        if ai_in_name:
            t_ai = threading.Thread(
                target=_ai_handler,
                args=(ai_in_name, pass_out_port, out_lock, stop_event, verbose),
                name="bridge-ai",
                daemon=True,
            )
            t_ai.start()
            threads.append(t_ai)

        # Main-Thread wartet auf Ctrl+C
        try:
            while any(t.is_alive() for t in threads):
                time.sleep(0.2)
        except KeyboardInterrupt:
            stop_event.set()
            print("\nBridge wird gestoppt...")


def main() -> int:
    p = argparse.ArgumentParser(description="KI-Studio MIDI-Bridge — Xboard + KI zu Cubase")
    p.add_argument("--xboard-port", default="Xboard",
                   help="Substring/Hint des Xboard-Input-Ports (default: 'Xboard')")
    p.add_argument("--mackie-port", default="MACKIE_TO_CUBASE",
                   help="Mackie-Output-Port-Name (default: MACKIE_TO_CUBASE)")
    p.add_argument("--pass-port", default="XBOARD_BRIDGED",
                   help="Pass-Through-Port (default: XBOARD_BRIDGED)")
    p.add_argument("--ai-input-port", default="AI_INPUT",
                   help="loopMIDI-Port den die KI als Send-Endpoint nutzt (default: AI_INPUT). "
                        "Wenn Port nicht existiert, laeuft Bridge ohne KI-Pfad.")
    p.add_argument("--no-ai-input", action="store_true",
                   help="Deaktiviert den AI_INPUT-Pfad explizit (auch wenn Port existiert).")
    p.add_argument("--quiet", action="store_true", help="Kein Verbose-Logging")
    args = p.parse_args()

    ai_input = None if args.no_ai_input else args.ai_input_port

    try:
        run_bridge(
            xboard_port=args.xboard_port,
            mackie_port=args.mackie_port,
            pass_port=args.pass_port,
            ai_input_port=ai_input,
            verbose=not args.quiet,
        )
    except KeyboardInterrupt:
        print("\nBridge gestoppt.")
        return 0
    except (OSError, ValueError) as e:
        print(f"FEHLER: {e}", file=sys.stderr)
        return 2

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
