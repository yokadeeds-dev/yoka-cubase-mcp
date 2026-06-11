"""
Traktor-Bridge — DeckState + TraktorMirror.

Hält den aktuellen Zustand aller Decks thread-safe.
Wird vom Observer mit eingehenden MIDI-Messages befüllt.
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field
from typing import Any

from runtime.traktor.mapping import (
    CHANNEL_TO_DECK,
    CC_MAP,
    NOTE_MAP,
    cc_to_bool,
    cc_to_float,
    bpm_from_msb_lsb,
)


@dataclass
class DeckState:
    deck: str                    # "A", "B", "C", "D"
    play: bool = False
    cue_active: bool = False
    volume: float = 1.0          # 0.0-1.0
    eq_hi: float = 0.0           # -1.0 to +1.0 (center=0)
    eq_mid: float = 0.0
    eq_lo: float = 0.0
    filter: float = 0.0          # -1.0 to +1.0
    loop_active: bool = False
    sync_active: bool = False
    bpm_msb: int = 0
    bpm_lsb: int = 0
    last_beat_ms: int = 0        # Timestamp letzter Beat-Pulse
    crossfader: float = 0.5      # 0.0-1.0 (master, nur Deck A trägt es)

    @property
    def bpm(self) -> float:
        return bpm_from_msb_lsb(self.bpm_msb, self.bpm_lsb)

    def to_dict(self) -> dict[str, Any]:
        return {
            "deck": self.deck,
            "play": self.play,
            "cue_active": self.cue_active,
            "volume": round(self.volume, 3),
            "eq_hi": round(self.eq_hi, 3),
            "eq_mid": round(self.eq_mid, 3),
            "eq_lo": round(self.eq_lo, 3),
            "filter": round(self.filter, 3),
            "loop_active": self.loop_active,
            "sync_active": self.sync_active,
            "bpm": round(self.bpm, 2) if self.bpm > 0 else None,
            "crossfader": round(self.crossfader, 3),
            "last_beat_ms": self.last_beat_ms,
        }


class TraktorMirror:
    """Thread-sicherer Zustandsspiegel für alle Traktor-Decks."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._decks: dict[str, DeckState] = {
            "A": DeckState("A"),
            "B": DeckState("B"),
            "C": DeckState("C"),
            "D": DeckState("D"),
        }
        self._created_at = time.monotonic()
        self._event_count = 0

    def apply_message(self, msg: Any) -> dict[str, Any] | None:
        """
        Verarbeitet eine mido-Message und aktualisiert den Deck-State.
        Gibt das geparste Event zurück oder None wenn unbekannt.
        """
        with self._lock:
            if msg.type == "control_change":
                return self._apply_cc(msg)
            elif msg.type in ("note_on", "note_off"):
                return self._apply_note(msg)
            return None

    def _apply_cc(self, msg: Any) -> dict[str, Any] | None:
        deck_name = CHANNEL_TO_DECK.get(msg.channel)
        if deck_name is None:
            return None
        cc_name = CC_MAP.get(msg.control)
        if cc_name is None:
            return None

        deck = self._decks[deck_name]
        v = msg.value
        self._event_count += 1

        if cc_name == "play":
            deck.play = cc_to_bool(v)
        elif cc_name == "cue_active":
            deck.cue_active = cc_to_bool(v)
        elif cc_name == "crossfader":
            deck.crossfader = cc_to_float(v)
        elif cc_name == "volume":
            deck.volume = cc_to_float(v)
        elif cc_name == "eq_hi":
            deck.eq_hi = cc_to_float(v, center=True)
        elif cc_name == "eq_mid":
            deck.eq_mid = cc_to_float(v, center=True)
        elif cc_name == "eq_lo":
            deck.eq_lo = cc_to_float(v, center=True)
        elif cc_name == "filter":
            deck.filter = cc_to_float(v, center=True)
        elif cc_name == "loop_active":
            deck.loop_active = cc_to_bool(v)
        elif cc_name == "sync_active":
            deck.sync_active = cc_to_bool(v)
        elif cc_name == "bpm_msb":
            deck.bpm_msb = v
        elif cc_name == "bpm_lsb":
            deck.bpm_lsb = v

        return {"kind": "cc", "deck": deck_name, "param": cc_name, "value": v}

    def _apply_note(self, msg: Any) -> dict[str, Any] | None:
        deck_name = CHANNEL_TO_DECK.get(msg.channel)
        note_name = NOTE_MAP.get(msg.note)
        if note_name == "beat_pulse" and msg.type == "note_on" and msg.velocity > 0:
            if deck_name:
                self._decks[deck_name].last_beat_ms = int(time.monotonic() * 1000)
            self._event_count += 1
            return {"kind": "beat", "deck": deck_name}
        return None

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            return {
                "decks": {d: s.to_dict() for d, s in self._decks.items()},
                "event_count": self._event_count,
                "uptime_s": round(time.monotonic() - self._created_at, 1),
            }

    def get_deck(self, deck: str) -> dict[str, Any] | None:
        with self._lock:
            if deck not in self._decks:
                return None
            return self._decks[deck].to_dict()
