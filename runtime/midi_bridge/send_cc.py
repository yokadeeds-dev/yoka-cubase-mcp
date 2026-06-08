"""
Minimaler MIDI-CC-Sender (Sprint D POC) — sendet rohe Control-Change-Nachrichten
an einen MIDI-Output-Port. Genutzt fuer Cubase Quick Controls / MIDI Learn /
Generic Remote.

Use-Case: Studio-KI sendet z.B. CC74 mit Wert 87 -> Cubase QC1 -> Plugin-Param.

Aufruf via CLI:
    python -m runtime.midi_bridge.send_cc --cc 74 --value 87
    python -m runtime.midi_bridge.send_cc --cc 74 --value 87 --port XBOARD_BRIDGED
    python -m runtime.midi_bridge.send_cc --cc 74 --value 87 --channel 1

Aufruf via Python-API:
    from runtime.midi_bridge.send_cc import send_cc, send_cc_value_for_param
    send_cc(cc=74, value=87)
    send_cc_value_for_param(cc=74, target_value_pct=68.5)  # 0-100% -> 0-127

Default-Port: XBOARD_BRIDGED — der Pass-Through-Port den die Xboard-Bridge
nutzt. Cubase erkennt diesen Port als MIDI-Input wenn er als Quick-Controls-
oder Generic-Remote-Source konfiguriert ist.
"""

from __future__ import annotations

import argparse
import sys
import time
from dataclasses import dataclass, field

import mido


DEFAULT_PORT_HINT = "XBOARD_BRIDGED"


@dataclass
class SendResult:
    """Ergebnis eines Send-Versuchs."""
    ok: bool
    port_used: str | None
    cc: int
    value: int
    channel: int
    error: str | None = None


def _resolve_output_port(hint: str) -> str:
    """Findet einen Output-Port via Substring-Match."""
    available = [p for p in mido.get_output_names() if p is not None]
    if hint in available:
        return hint
    matches = [n for n in available if hint.lower() in n.lower()]
    if len(matches) == 1:
        return matches[0]
    if len(matches) > 1:
        raise ValueError(f"Mehrere Output-Treffer fuer {hint!r}: {matches}")
    raise ValueError(f"Kein Output-Port fuer {hint!r}. Verfuegbar: {available}")


def list_ports() -> list[str]:
    """Liefert alle verfuegbaren MIDI-Output-Ports."""
    return [p for p in mido.get_output_names() if p is not None]


def send_cc(
    cc: int,
    value: int,
    port: str = DEFAULT_PORT_HINT,
    channel: int = 0,
) -> SendResult:
    """
    Sendet eine einzelne Control-Change-Nachricht.

    Args:
        cc: CC-Nummer (0-127)
        value: CC-Wert (0-127)
        port: Output-Port-Name oder Substring-Hint
        channel: MIDI-Kanal (0-15, default 0 = Kanal 1 in DAW-Zaehlung)

    Returns:
        SendResult mit ok/error-Status.
    """
    if not 0 <= cc <= 127:
        return SendResult(
            ok=False, port_used=None, cc=cc, value=value, channel=channel,
            error=f"CC ausserhalb 0-127: {cc}",
        )
    if not 0 <= value <= 127:
        return SendResult(
            ok=False, port_used=None, cc=cc, value=value, channel=channel,
            error=f"Value ausserhalb 0-127: {value}",
        )
    if not 0 <= channel <= 15:
        return SendResult(
            ok=False, port_used=None, cc=cc, value=value, channel=channel,
            error=f"Channel ausserhalb 0-15: {channel}",
        )

    try:
        port_name = _resolve_output_port(port)
    except ValueError as e:
        return SendResult(
            ok=False, port_used=None, cc=cc, value=value, channel=channel,
            error=str(e),
        )

    try:
        with mido.open_output(port_name) as outport:  # type: ignore[attr-defined]
            msg = mido.Message("control_change", control=cc, value=value, channel=channel)
            outport.send(msg)
    except Exception as e:
        return SendResult(
            ok=False, port_used=port_name, cc=cc, value=value, channel=channel,
            error=f"{type(e).__name__}: {e}",
        )

    return SendResult(
        ok=True, port_used=port_name, cc=cc, value=value, channel=channel,
    )


def send_cc_value_for_param(
    cc: int,
    target_value_pct: float,
    port: str = DEFAULT_PORT_HINT,
    channel: int = 0,
) -> SendResult:
    """
    Komfort-Funktion: nimmt einen Ziel-Wert in Prozent (0.0-100.0)
    und konvertiert auf CC-Wert (0-127).

    Args:
        cc: CC-Nummer
        target_value_pct: 0.0 bis 100.0
        port: Output-Port
        channel: MIDI-Kanal

    Returns:
        SendResult.

    Beispiel:
        send_cc_value_for_param(74, 50.0)  # CC74 auf Mitte (CC-Wert 64)
        send_cc_value_for_param(74, 0.0)   # CC74 auf Min (CC-Wert 0)
        send_cc_value_for_param(74, 100.0) # CC74 auf Max (CC-Wert 127)
    """
    if not 0.0 <= target_value_pct <= 100.0:
        return SendResult(
            ok=False, port_used=None, cc=cc, value=-1, channel=channel,
            error=f"target_value_pct ausserhalb 0-100: {target_value_pct}",
        )
    cc_value = round(target_value_pct / 100.0 * 127)
    return send_cc(cc=cc, value=cc_value, port=port, channel=channel)


def send_cc_value_for_range(
    cc: int,
    target_value: float,
    range_min: float,
    range_max: float,
    port: str = DEFAULT_PORT_HINT,
    channel: int = 0,
) -> SendResult:
    """
    Komfort-Funktion: nimmt einen Ziel-Wert in einer beliebigen Range
    (z.B. -60 bis 0 dB fuer Comp-Threshold) und mapped auf CC 0-127.

    Args:
        cc: CC-Nummer
        target_value: Wert in der Range
        range_min: Minimum der Range (CC-Wert 0)
        range_max: Maximum der Range (CC-Wert 127)
        port: Output-Port
        channel: MIDI-Kanal

    Beispiel (Compressor-Threshold von -60 bis 0 dB, Ziel -18 dB):
        send_cc_value_for_range(74, -18.0, -60.0, 0.0)
        # Berechnet: pct = (-18 - -60) / (0 - -60) * 100 = 70%
        # CC-Wert = round(70/100 * 127) = 89
    """
    if range_max == range_min:
        return SendResult(
            ok=False, port_used=None, cc=cc, value=-1, channel=channel,
            error=f"Range ungueltig: min={range_min}, max={range_max}",
        )
    if not (range_min <= target_value <= range_max) and not (range_max <= target_value <= range_min):
        return SendResult(
            ok=False, port_used=None, cc=cc, value=-1, channel=channel,
            error=f"target_value {target_value} ausserhalb [{range_min}, {range_max}]",
        )
    pct = (target_value - range_min) / (range_max - range_min) * 100.0
    return send_cc_value_for_param(cc=cc, target_value_pct=pct, port=port, channel=channel)


# ---------- Note-Send (Sprint H — autonomer MIDI-Workflow) ----------

@dataclass
class NoteSendResult:
    """Ergebnis eines Note-On/Off-Send-Versuchs."""
    ok: bool
    port_used: str | None
    notes: list[int] = field(default_factory=list)
    velocity: int = 0
    channel: int = 0
    duration_ms: int = 0
    error: str | None = None


def send_notes(
    notes: list[int],
    duration_ms: int = 500,
    velocity: int = 80,
    port: str = DEFAULT_PORT_HINT,
    channel: int = 0,
) -> NoteSendResult:
    """
    Sendet einen Akkord: alle Note-Ons zusammen, wartet duration_ms,
    alle Note-Offs zusammen.

    Args:
        notes: Liste MIDI-Notennummern (0-127). C4=60, C-Dur-Akkord = [60, 64, 67].
        duration_ms: Wie lange die Noten gehalten werden (1-30000).
        velocity: Note-On-Velocity (0-127, typisch 80).
        port: Output-Port-Name oder Substring-Hint.
        channel: MIDI-Kanal (0-15, default 0 = Kanal 1 in DAW-Zaehlung).

    Wichtig: blockt fuer duration_ms Sekunden. Fuer lange Noten Tool-Caller
    bedenken (timeout). Default 500ms = halbe Sekunde.

    Use-Case: Cubase-Track scharfgeschaltet auf Recording, Input-Port = dieser
    Output-Port (loopMIDI-Loopback). Cubase nimmt die Noten als MIDI-Daten auf.
    """
    if not notes:
        return NoteSendResult(
            ok=False, port_used=None, notes=[], velocity=velocity,
            channel=channel, duration_ms=duration_ms,
            error="notes-Liste leer",
        )
    for n in notes:
        if not 0 <= n <= 127:
            return NoteSendResult(
                ok=False, port_used=None, notes=notes, velocity=velocity,
                channel=channel, duration_ms=duration_ms,
                error=f"Note ausserhalb 0-127: {n}",
            )
    if not 0 <= velocity <= 127:
        return NoteSendResult(
            ok=False, port_used=None, notes=notes, velocity=velocity,
            channel=channel, duration_ms=duration_ms,
            error=f"Velocity ausserhalb 0-127: {velocity}",
        )
    if not 0 <= channel <= 15:
        return NoteSendResult(
            ok=False, port_used=None, notes=notes, velocity=velocity,
            channel=channel, duration_ms=duration_ms,
            error=f"Channel ausserhalb 0-15: {channel}",
        )
    if not 1 <= duration_ms <= 30000:
        return NoteSendResult(
            ok=False, port_used=None, notes=notes, velocity=velocity,
            channel=channel, duration_ms=duration_ms,
            error=f"duration_ms ausserhalb 1-30000: {duration_ms}",
        )

    try:
        port_name = _resolve_output_port(port)
    except ValueError as e:
        return NoteSendResult(
            ok=False, port_used=None, notes=notes, velocity=velocity,
            channel=channel, duration_ms=duration_ms, error=str(e),
        )

    note_off_errors: list[str] = []
    try:
        with mido.open_output(port_name) as outport:  # type: ignore[attr-defined]
            # sent_on trackt, welche Noten tatsaechlich ein Note-On bekommen haben.
            # Das finally garantiert fuer JEDE dieser Noten ein Note-Off — auch wenn
            # die On-Schleife oder der sleep durch Exception/KeyboardInterrupt abbricht.
            # Verhindert "stuck notes" (Instrument toent endlos weiter).
            sent_on: list[int] = []
            try:
                for n in notes:
                    # append VOR send: schliesst die SIGINT-Race-Luecke. Landet ein
                    # KeyboardInterrupt zwischen send() und append(), waere die Note-On
                    # sonst auf der Wire aber n nicht in sent_on -> kein Note-Off -> stuck.
                    # Ein spurious Note-Off fuer eine (durch send-Fehler) nie geklungene
                    # Note ist auf MIDI harmlos; ein fehlendes Note-Off ist der Bug.
                    sent_on.append(n)
                    outport.send(mido.Message(
                        "note_on", note=n, velocity=velocity, channel=channel,
                    ))
                time.sleep(duration_ms / 1000.0)
            finally:
                for n in sent_on:
                    try:
                        outport.send(mido.Message(
                            "note_off", note=n, velocity=0, channel=channel,
                        ))
                    except Exception as off_err:
                        # Best-effort: ein fehlgeschlagenes Note-Off darf die uebrigen
                        # nicht blockieren — aber den Fehler NICHT schlucken, sonst
                        # meldet die Funktion faelschlich ok=True trotz moeglicher
                        # stuck notes. Wird unten zu ok=False eskaliert.
                        note_off_errors.append(f"note {n}: {type(off_err).__name__}: {off_err}")
    except Exception as e:
        return NoteSendResult(
            ok=False, port_used=port_name, notes=notes, velocity=velocity,
            channel=channel, duration_ms=duration_ms,
            error=f"{type(e).__name__}: {e}",
        )

    if note_off_errors:
        return NoteSendResult(
            ok=False, port_used=port_name, notes=notes, velocity=velocity,
            channel=channel, duration_ms=duration_ms,
            error="Note-Off-Fehler (moegliche stuck notes): " + "; ".join(note_off_errors),
        )

    return NoteSendResult(
        ok=True, port_used=port_name, notes=notes, velocity=velocity,
        channel=channel, duration_ms=duration_ms,
    )


def send_note_sequence(
    notes: list[int],
    note_duration_ms: int = 250,
    gap_ms: int = 50,
    velocity: int = 80,
    port: str = DEFAULT_PORT_HINT,
    channel: int = 0,
) -> NoteSendResult:
    """
    Spielt eine Melodie: Note 1 fuer note_duration_ms, gap_ms Pause, Note 2, ...
    Aggregiert alle Send-Fehler — bei erstem Fehler wird abgebrochen.

    Use-Case: einfache Melodien fuer Demo (z.B. C-Dur-Tonleiter).
    Fuer komplexere Patterns bitte mehrere send_notes-Aufrufe orchestrieren.
    """
    if not notes:
        return NoteSendResult(
            ok=False, port_used=None, notes=[], velocity=velocity,
            channel=channel, duration_ms=0, error="notes-Liste leer",
        )
    total_ms = (note_duration_ms + gap_ms) * len(notes)
    if total_ms > 30000:
        return NoteSendResult(
            ok=False, port_used=None, notes=notes, velocity=velocity,
            channel=channel, duration_ms=total_ms,
            error=f"Sequenz waere {total_ms}ms — max 30000ms erlaubt",
        )

    last_result = None
    for n in notes:
        last_result = send_notes(
            notes=[n], duration_ms=note_duration_ms,
            velocity=velocity, port=port, channel=channel,
        )
        if not last_result.ok:
            return last_result
        if gap_ms > 0:
            time.sleep(gap_ms / 1000.0)

    return NoteSendResult(
        ok=True, port_used=last_result.port_used if last_result else None,
        notes=notes, velocity=velocity, channel=channel,
        duration_ms=total_ms,
    )


# ---------- CLI ----------

def _cli() -> int:
    p = argparse.ArgumentParser(description="Minimaler MIDI-CC-Sender (KI-Studio Sprint D POC).")
    p.add_argument("--cc", type=int, required=False, help="CC-Nummer 0-127")
    p.add_argument("--value", type=int, required=False, help="CC-Wert 0-127")
    p.add_argument("--port", type=str, default=DEFAULT_PORT_HINT, help=f"Output-Port (default: {DEFAULT_PORT_HINT})")
    p.add_argument("--channel", type=int, default=0, help="MIDI-Kanal 0-15 (default 0)")
    p.add_argument("--list-ports", action="store_true", help="Listet alle verfuegbaren Output-Ports")
    p.add_argument("--pct", type=float, help="Ziel-Wert in Prozent 0-100 statt --value")
    args = p.parse_args()

    if args.list_ports:
        print("Verfuegbare MIDI-Output-Ports:")
        for port_name in list_ports():
            print(f"  {port_name}")
        return 0

    if args.cc is None:
        print("ERROR: --cc benoetigt (oder --list-ports)", file=sys.stderr)
        return 2

    if args.pct is not None:
        result = send_cc_value_for_param(
            cc=args.cc, target_value_pct=args.pct,
            port=args.port, channel=args.channel,
        )
    elif args.value is not None:
        result = send_cc(
            cc=args.cc, value=args.value,
            port=args.port, channel=args.channel,
        )
    else:
        print("ERROR: --value oder --pct benoetigt", file=sys.stderr)
        return 2

    if result.ok:
        print(
            f"[OK] CC{result.cc}={result.value} auf '{result.port_used}' "
            f"(Kanal {result.channel + 1})"
        )
        return 0
    else:
        print(f"[FAIL] {result.error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(_cli())
