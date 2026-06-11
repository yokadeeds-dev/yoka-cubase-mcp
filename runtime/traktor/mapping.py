"""
Traktor-Bridge — MIDI-Mapping-Definitionen.

Traktor sendet Deck-State via Generic MIDI Controller (Controller Manager).
Dieses Modul definiert das Mapping: welcher CC/Note → welcher Deck-State.

Convention (angelehnt an Traktor-Defaults):
  CH 1 = Deck A, CH 2 = Deck B, CH 3 = Deck C, CH 4 = Deck D

  CC 1  = Play state        (0=stop, 127=play)
  CC 2  = Cue point active  (0=off, 127=on)
  CC 3  = Crossfader        (0-127)
  CC 4  = Volume Deck       (0-127)
  CC 5  = EQ Hi             (0-127, 64=center)
  CC 6  = EQ Mid            (0-127, 64=center)
  CC 7  = EQ Lo             (0-127, 64=center)
  CC 8  = Filter            (0-127, 64=center)
  CC 9  = Loop active       (0=off, 127=on)
  CC 10 = Sync active       (0=off, 127=on)
  CC 11 = Master BPM (MSB)  (integer part, 60-200)
  CC 12 = Master BPM (LSB)  (fractional *100, 0-99)

  Note 0 = Beat (pulse per beat, velocity=127 on beat)

Diese Werte müssen im Traktor Controller Manager so gemappt werden.
Das TSI-File (export aus Traktor) liegt in specs/traktor_bridge.tsi (wird generiert).
"""

from __future__ import annotations

# MIDI-Kanal pro Deck (1-basiert, wie in mido channel+1)
DECK_CHANNELS: dict[str, int] = {
    "A": 0,   # mido: channel 0 = MIDI CH 1
    "B": 1,
    "C": 2,
    "D": 3,
}

CHANNEL_TO_DECK: dict[int, str] = {v: k for k, v in DECK_CHANNELS.items()}

# CC-Nummern → Bedeutung
CC_MAP: dict[int, str] = {
    1:  "play",
    2:  "cue_active",
    3:  "crossfader",
    4:  "volume",
    5:  "eq_hi",
    6:  "eq_mid",
    7:  "eq_lo",
    8:  "filter",
    9:  "loop_active",
    10: "sync_active",
    11: "bpm_msb",
    12: "bpm_lsb",
}

CC_REVERSE: dict[str, int] = {v: k for k, v in CC_MAP.items()}

# Note-Nummern → Bedeutung
NOTE_MAP: dict[int, str] = {
    0: "beat_pulse",
}

# Normalisierungs-Hilfsfunktionen
def cc_to_bool(value: int) -> bool:
    return value >= 64

def cc_to_float(value: int, center: bool = False) -> float:
    """0-127 → 0.0-1.0, optional mit 64=0.0 (center-relative)."""
    if center:
        return max(-1.0, min(1.0, (value - 64) / 63.0))
    return value / 127.0

BPM_OFFSET = 60  # CC-Wert 0 = 60 BPM, CC 127 = 187 BPM

def bpm_from_msb_lsb(msb: int, lsb: int) -> float:
    """Rekonstruiert BPM aus zwei CC-Werten.
    MSB = BPM_integer - BPM_OFFSET (CC 0-127 → 60-187 BPM)
    LSB = fractional * 100 (CC 0-99)
    """
    return (msb + BPM_OFFSET) + lsb / 100.0

def bpm_to_msb_lsb(bpm: float) -> tuple[int, int]:
    """BPM → (MSB, LSB) für Traktor-Mapping-Kalibrierung."""
    integer = int(bpm)
    frac = round((bpm - integer) * 100)
    return (max(0, min(127, integer - BPM_OFFSET)), frac)
