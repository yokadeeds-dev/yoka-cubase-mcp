"""
Xboard-zu-Mackie Bridge — Pure Funcs für die CC-Konvertierung.

Problem:
- Xboard (und ähnliche generic MIDI-Controller) senden ABSOLUTE Werte (0-127)
- Mackie-Encoder (CC 16-23) erwarten RELATIVE Inkremente:
  - Bit 6 = Direction (1=CCW, 0=CW)
  - Bits 0-5 = Speed (1-63)

Lösung:
- Tracker hält letzten Xboard-Wert pro Knopf
- Bei neuem Wert: Differenz berechnen, in Mackie-Inkrement-Format umsetzen
- Sender schickt Mackie-konformen CC auf den entsprechenden Encoder

Dadurch verhält sich das Xboard für Cubase wie ein Hardware-Mackie-Controller.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import mido

from runtime.mackie.parser import SPEC


MACKIE_ENCODER_CC_START = SPEC["encoders"]["cc_start"]  # 16
MACKIE_DIRECTION_MASK = SPEC["encoders"]["direction_mask"]  # 0x40 = 64
MACKIE_SPEED_MASK = SPEC["encoders"]["speed_mask"]  # 0x3F = 63


def absolute_diff_to_mackie_increment(diff: int) -> int:
    """
    Übersetzt eine absolute Wert-Differenz in Mackie-Increment-Encoding.

    diff > 0  →  CW-Drehung mit Speed=|diff| (gecapped auf 63)
    diff < 0  →  CCW-Drehung mit Speed=|diff| (gecapped auf 63)
    diff == 0 →  None (kein Send)
    """
    if diff == 0:
        return 0
    speed = min(abs(diff), MACKIE_SPEED_MASK)
    if diff < 0:
        return MACKIE_DIRECTION_MASK | speed
    return speed


@dataclass
class XboardKnobMapping:
    """Mappt einen Xboard-Knopf auf einen Mackie-Encoder."""
    xboard_cc: int
    mackie_encoder_index: int  # 0-7

    @property
    def mackie_cc(self) -> int:
        return MACKIE_ENCODER_CC_START + self.mackie_encoder_index


# Default-Mapping für Yokas E-MU Xboard 49 (Werks-Preset, vom Display abgelesen 2026-05-04):
# Obere Reihe Poti 1-8 sequentiell CC 21-28 → Mackie-Encoder 0-7
# Untere Reihe Poti 9-16 sind CC 70-73 + 91 + 93 + 82 + 83 — werden NICHT auf
# Mackie-Encoder gemappt (würde mit oberer Reihe kollidieren), sondern via
# Pass-Through an Cubase weitergegeben für freie MIDI-Learn-Belegung
# (z. B. Quick Controls, Channel-Strip-Send, Mute/Solo etc.).
DEFAULT_XBOARD_TO_MACKIE_MAPPINGS: list[XboardKnobMapping] = [
    XboardKnobMapping(xboard_cc=21, mackie_encoder_index=0),  # Poti 1
    XboardKnobMapping(xboard_cc=22, mackie_encoder_index=1),  # Poti 2
    XboardKnobMapping(xboard_cc=23, mackie_encoder_index=2),  # Poti 3
    XboardKnobMapping(xboard_cc=24, mackie_encoder_index=3),  # Poti 4
    XboardKnobMapping(xboard_cc=25, mackie_encoder_index=4),  # Poti 5
    XboardKnobMapping(xboard_cc=26, mackie_encoder_index=5),  # Poti 6
    XboardKnobMapping(xboard_cc=27, mackie_encoder_index=6),  # Poti 7
    XboardKnobMapping(xboard_cc=28, mackie_encoder_index=7),  # Poti 8
]

# Untere Reihe — bekannt, gehen aber via Pass-Through (nicht Mackie):
#   Poti 9  = CC 70
#   Poti 10 = CC 71
#   Poti 11 = CC 72
#   Poti 12 = CC 73
#   Poti 13 = CC 91
#   Poti 14 = CC 93
#   Poti 15 = CC 82
#   Poti 16 = CC 83
LOWER_ROW_PASSTHROUGH_CCS: list[tuple[int, int]] = [
    (9, 70), (10, 71), (11, 72), (12, 73),
    (13, 91), (14, 93), (15, 82), (16, 83),
]

# Mod-Wheel: Standard-MIDI CC 1, geht ohnehin via Pass-Through.
# Pitchbend: separate Message-Type, geht ebenfalls via Pass-Through.
MOD_WHEEL_CC = 1


@dataclass
class XboardBridgeState:
    """Hält den letzten Xboard-Wert pro Knopf, um Inkremente zu berechnen."""
    last_values: dict[int, int] = field(default_factory=dict)

    def update_and_compute_increment(self, xboard_cc: int, new_value: int) -> int | None:
        """
        Akzeptiert einen neuen Xboard-Wert für einen CC, returned das
        Mackie-Inkrement-Encoding (für value-Field in CC-Message),
        oder None wenn keine Änderung (z. B. erster Wert seit Start).
        """
        last = self.last_values.get(xboard_cc)
        self.last_values[xboard_cc] = new_value
        if last is None:
            # Erster Wert seit Start — kein Inkrement, nur Init
            return None
        diff = new_value - last
        if diff == 0:
            return None
        return absolute_diff_to_mackie_increment(diff)


def make_mackie_encoder_message(encoder_index: int, mackie_increment: int) -> mido.Message:
    """Baut die Mackie-Encoder-CC-Message."""
    cc = MACKIE_ENCODER_CC_START + encoder_index
    return mido.Message("control_change", control=cc, value=mackie_increment)


def is_xboard_knob_for_mackie(xboard_cc: int, mappings: list[XboardKnobMapping]) -> XboardKnobMapping | None:
    """Prüft ob ein Xboard-CC zu einem gemappten Mackie-Encoder gehört."""
    for m in mappings:
        if m.xboard_cc == xboard_cc:
            return m
    return None
