"""
Mackie Control Universal — pure parser functions.

Wandelt mido Messages in strukturierte Events. Keine I/O, keine Seiteneffekte.
Damit ist die gesamte Parser-Logik ohne MIDI-Port testbar (siehe
tests/selftest_scripts/listener_selftest.py).
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


_SPEC_PATH = Path(__file__).parent.parent.parent / "specs" / "mackie_spec.json"


def load_spec(path: Path | None = None) -> dict[str, Any]:
    """Lädt mackie_spec.json einmal beim Modul-Init oder explizit."""
    p = path or _SPEC_PATH
    with p.open("r", encoding="utf-8") as f:
        return json.load(f)


SPEC = load_spec()


def _is_lcd_sysex(data: list[int], spec: dict[str, Any]) -> bool:
    header = spec["sysex"]["header_lcd"]
    # data von mido enthält den Sysex-Body OHNE F0/F7
    return list(data[: len(header) - 1]) == header[1:]


def _is_2char_sysex(data: list[int], spec: dict[str, Any]) -> bool:
    header = spec["sysex"]["header_2char"]
    return list(data[: len(header) - 1]) == header[1:]


def _is_tc_sysex(data: list[int], spec: dict[str, Any]) -> bool:
    header = spec["sysex"]["header_tc"]
    return list(data[: len(header) - 1]) == header[1:]


def _decode_ascii(bytes_list: list[int]) -> str:
    return "".join(chr(b) if 32 <= b <= 126 else " " for b in bytes_list)


def parse_message(msg, spec: dict[str, Any] = SPEC) -> dict[str, Any]:
    """
    Wandelt eine mido Message in ein Event-Dict.

    Returns einen dict mit mindestens dem Schlüssel `kind`. Unbekannte
    Messages bekommen `kind="unknown"` und behalten den raw-Type.
    """
    if msg.type == "sysex":
        data = list(msg.data)
        if _is_lcd_sysex(data, spec):
            offset = data[5]
            text = _decode_ascii(data[6:])
            return {"kind": "lcd", "offset": offset, "text": text}
        if _is_2char_sysex(data, spec):
            text = _decode_ascii(data[5:])
            return {"kind": "two_char_display", "text": text}
        if _is_tc_sysex(data, spec):
            return {"kind": "timecode", "raw": data[5:]}
        return {"kind": "sysex_other", "data": data}

    if msg.type in ("note_on", "note_off"):
        note = msg.note
        pressed = msg.type == "note_on" and msg.velocity > 0
        btn = spec["buttons"]

        if btn["select"]["start"] <= note <= btn["select"]["end"]:
            return {"kind": "select", "channel": note - btn["select"]["start"], "pressed": pressed}
        if btn["mute"]["start"] <= note <= btn["mute"]["end"]:
            return {"kind": "mute", "channel": note - btn["mute"]["start"], "pressed": pressed}
        if btn["solo"]["start"] <= note <= btn["solo"]["end"]:
            return {"kind": "solo", "channel": note - btn["solo"]["start"], "pressed": pressed}
        if btn["rec_arm"]["start"] <= note <= btn["rec_arm"]["end"]:
            return {"kind": "rec_arm", "channel": note - btn["rec_arm"]["start"], "pressed": pressed}

        for action, action_note in btn["transport"].items():
            if note == action_note:
                return {"kind": "transport_button", "action": action, "pressed": pressed}

        for mode_name, mode_note in btn["mode"].items():
            if note == mode_note:
                return {"kind": "mode_button", "mode": mode_name, "pressed": pressed}

        return {"kind": "button_other", "note": note, "pressed": pressed}

    if msg.type == "control_change":
        cc = msg.control
        enc = spec["encoders"]
        if enc["cc_start"] <= cc <= enc["cc_end"]:
            value = msg.value
            direction = -1 if (value & enc["direction_mask"]) else 1
            speed = value & enc["speed_mask"]
            return {
                "kind": "encoder",
                "encoder": cc - enc["cc_start"],
                "direction": direction,
                "speed": speed,
            }
        # Mackie-Timecode-Display: CC 0x40–0x49 (64–73), 10 Stellen, 7-Segment.
        # Werte sind ASCII-Codes (32=blank, 48–57='0'–'9', plus Sonderzeichen).
        # Cubase flutet diese im Play-Mode → wir geben einen kompakten Event-Typ
        # zurück, den der Listener-Print stumm lässt.
        if 64 <= cc <= 73:
            return {"kind": "timecode_digit", "digit_index": cc - 64, "ascii": msg.value}
        return {"kind": "cc_other", "control": cc, "value": msg.value}

    if msg.type == "pitchwheel":
        # mido normalisiert Pitch Bend auf -8192..+8191; wir reichen den
        # Channel und den 14-Bit-Wert (umgerechnet auf 0..16383) durch.
        value14 = msg.pitch + 8192
        return {"kind": "fader", "channel": msg.channel, "value14": value14}

    if msg.type == "aftertouch":
        # Channel Pressure: high nibble = Kanal, low nibble = Pegel
        v = msg.value
        return {
            "kind": "vu",
            "channel": (v & spec["vu_meters"]["channel_mask"]) >> 4,
            "level": v & spec["vu_meters"]["level_mask"],
        }

    return {"kind": "unknown", "type": msg.type}


def lcd_text_to_channel_strips(text: str, spec: dict[str, Any] = SPEC) -> list[str]:
    """
    Splittet einen 56-Zeichen-LCD-String in 8 Channel-Strips à 7 Zeichen.
    Funktioniert sowohl für die obere wie die untere LCD-Reihe.
    """
    width = spec["lcd"]["chars_per_channel"]
    count = spec["lcd"]["channels_per_row"]
    padded = text.ljust(width * count)[: width * count]
    return [padded[i * width : (i + 1) * width].strip() for i in range(count)]
