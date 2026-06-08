"""
Mackie-Einheiten-Konvertierung — Pure Funcs, keine Side-Effects.

Mackie-Fader sind 14-Bit (0..16383). Die Mapping-Kurve auf dB ist nicht
streng spezifiziert; wir verwenden eine piecewise-lineare Annäherung, die
den meisten DAWs (Cubase, Ableton, Reaper) ausreichend nahe kommt:

  value14 = 0        →  -inf dB (mute)
  value14 = 12286    →   0 dB
  value14 = 16383    →  +10 dB

Bereich -70 dB bis 0 dB linear über value14 0..12286.
Bereich 0 dB bis +10 dB linear über value14 12286..16383.

Für präzise Mastering-Anwendungen kalibriert man später gegen die echten
DAW-Werte (Etappe 8+, Persona Nicker mit Reference-Track-Vergleich).
"""

from __future__ import annotations


VALUE14_MAX = 16383
VALUE14_AT_ZERO_DB = 12286
DB_AT_VALUE14_MAX = 10.0
DB_AT_VALUE14_ZERO_FLOOR = -70.0
DB_NEG_INF = -144.0  # Proxy für Mute / -inf


def value14_to_db(value14: int) -> float:
    """Mackie-Fader-Wert (0..16383) → dB. value14<=0 → DB_NEG_INF."""
    if value14 <= 0:
        return DB_NEG_INF
    if value14 >= VALUE14_MAX:
        return DB_AT_VALUE14_MAX
    if value14 < VALUE14_AT_ZERO_DB:
        # 0..12286 → -70..0 dB linear
        return DB_AT_VALUE14_ZERO_FLOOR + (value14 / VALUE14_AT_ZERO_DB) * abs(DB_AT_VALUE14_ZERO_FLOOR)
    # 12286..16383 → 0..+10 dB linear
    span_v = VALUE14_MAX - VALUE14_AT_ZERO_DB
    span_db = DB_AT_VALUE14_MAX
    return ((value14 - VALUE14_AT_ZERO_DB) / span_v) * span_db


def db_to_value14(db: float) -> int:
    """dB → Mackie-Fader-Wert (0..16383). Clamp + Rundung."""
    if db <= DB_AT_VALUE14_ZERO_FLOOR:
        # für sehr leise Werte: -inf-Region → 0
        if db <= DB_NEG_INF + 1.0:  # näher an -inf
            return 0
        # zwischen -inf und -70 dB: extrapolieren wir nicht, return 0
        return 0
    if db >= DB_AT_VALUE14_MAX:
        return VALUE14_MAX
    if db < 0:
        # -70..0 dB linear → 0..12286
        return int(round((db - DB_AT_VALUE14_ZERO_FLOOR) / abs(DB_AT_VALUE14_ZERO_FLOOR) * VALUE14_AT_ZERO_DB))
    # 0..+10 dB linear → 12286..16383
    span_v = VALUE14_MAX - VALUE14_AT_ZERO_DB
    span_db = DB_AT_VALUE14_MAX
    return int(round(VALUE14_AT_ZERO_DB + (db / span_db) * span_v))
