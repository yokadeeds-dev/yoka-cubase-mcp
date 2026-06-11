"""
Traktor-Bridge Selftests — kein MIDI-Hardware nötig.
Testet Mapping, State-Logik und Observer-Parsing mit synthetischen mido-Messages.
"""

from __future__ import annotations

import time
from unittest.mock import MagicMock

import mido

from runtime.traktor.mapping import (
    DECK_CHANNELS, CHANNEL_TO_DECK, CC_MAP, CC_REVERSE,
    cc_to_bool, cc_to_float, bpm_from_msb_lsb,
)
from runtime.traktor.state import TraktorMirror, DeckState


# ---------- Helpers ----------

def cc(channel: int, control: int, value: int) -> mido.Message:
    return mido.Message("control_change", channel=channel, control=control, value=value)

def note_on(channel: int, note: int, velocity: int = 127) -> mido.Message:
    return mido.Message("note_on", channel=channel, note=note, velocity=velocity)

def ok(name: str, result: str) -> None:
    print(f"  {name} OK -> {result}")

def fail(name: str, msg: str) -> None:
    raise AssertionError(f"FAIL [{name}]: {msg}")


# ---------- Tests ----------

def test_deck_channels():
    assert DECK_CHANNELS["A"] == 0
    assert DECK_CHANNELS["B"] == 1
    assert CHANNEL_TO_DECK[0] == "A"
    assert CHANNEL_TO_DECK[3] == "D"
    ok("deck_channels", f"A=CH{DECK_CHANNELS['A']+1}, D=CH{DECK_CHANNELS['D']+1}")

def test_cc_map():
    assert CC_MAP[1] == "play"
    assert CC_MAP[3] == "crossfader"
    assert CC_REVERSE["volume"] == 4
    ok("cc_map", f"play=CC{CC_REVERSE['play']}, volume=CC{CC_REVERSE['volume']}")

def test_cc_to_bool():
    assert cc_to_bool(0) is False
    assert cc_to_bool(63) is False
    assert cc_to_bool(64) is True
    assert cc_to_bool(127) is True
    ok("cc_to_bool", "0→False, 64→True, 127→True")

def test_cc_to_float():
    assert abs(cc_to_float(0) - 0.0) < 0.01
    assert abs(cc_to_float(127) - 1.0) < 0.01
    assert abs(cc_to_float(64, center=True) - 0.0) < 0.02
    assert abs(cc_to_float(127, center=True) - 1.0) < 0.02
    ok("cc_to_float", "0→0.0, 127→1.0, center: 64→0.0")

def test_bpm_from_msb_lsb():
    # MSB=68 → 68+60=128, LSB=50 → 128.50 BPM
    bpm = bpm_from_msb_lsb(68, 50)
    assert abs(bpm - 128.5) < 0.01
    ok("bpm_from_msb_lsb", f"MSB=68(+60), LSB=50 → {bpm:.2f} BPM")

def test_mirror_play_stop():
    m = TraktorMirror()
    m.apply_message(cc(0, 1, 127))  # Deck A play
    assert m.get_deck("A")["play"] is True
    m.apply_message(cc(0, 1, 0))    # Deck A stop
    assert m.get_deck("A")["play"] is False
    ok("mirror_play_stop", "Deck A: 127→play, 0→stop")

def test_mirror_deck_isolation():
    m = TraktorMirror()
    m.apply_message(cc(0, 1, 127))  # Deck A play
    m.apply_message(cc(1, 1, 0))    # Deck B stop
    assert m.get_deck("A")["play"] is True
    assert m.get_deck("B")["play"] is False
    ok("mirror_deck_isolation", "Deck A play, Deck B stop — unabhängig")

def test_mirror_volume():
    m = TraktorMirror()
    m.apply_message(cc(0, 4, 127))  # Deck A volume max
    vol = m.get_deck("A")["volume"]
    assert abs(vol - 1.0) < 0.01
    m.apply_message(cc(0, 4, 0))
    vol = m.get_deck("A")["volume"]
    assert abs(vol - 0.0) < 0.01
    ok("mirror_volume", "127→1.0, 0→0.0")

def test_mirror_eq():
    m = TraktorMirror()
    m.apply_message(cc(0, 5, 64))   # EQ Hi center
    m.apply_message(cc(0, 6, 0))    # EQ Mid min
    m.apply_message(cc(0, 7, 127))  # EQ Lo max
    deck = m.get_deck("A")
    assert abs(deck["eq_hi"] - 0.0) < 0.02    # center
    assert deck["eq_mid"] < -0.9              # min
    assert deck["eq_lo"] > 0.9               # max
    ok("mirror_eq", f"hi={deck['eq_hi']:.2f}, mid={deck['eq_mid']:.2f}, lo={deck['eq_lo']:.2f}")

def test_mirror_crossfader():
    m = TraktorMirror()
    m.apply_message(cc(0, 3, 0))    # crossfader links
    assert m.get_deck("A")["crossfader"] < 0.01
    m.apply_message(cc(0, 3, 64))   # crossfader mitte
    assert abs(m.get_deck("A")["crossfader"] - 0.5) < 0.02
    ok("mirror_crossfader", "0→0.0, 64→~0.5")

def test_mirror_bpm():
    m = TraktorMirror()
    # 128 BPM: MSB = 128-60 = 68, LSB = 50 → 128.50
    m.apply_message(cc(0, 11, 68))
    m.apply_message(cc(0, 12, 50))
    bpm = m.get_deck("A")["bpm"]
    assert abs(bpm - 128.5) < 0.01
    ok("mirror_bpm", f"MSB=68(+60=128), LSB=50 → {bpm:.2f} BPM")

def test_mirror_beat_pulse():
    m = TraktorMirror()
    before = m.get_deck("A")["last_beat_ms"]
    m.apply_message(note_on(0, 0, 127))
    after = m.get_deck("A")["last_beat_ms"]
    assert after > before
    ok("mirror_beat_pulse", f"beat_ms updated: {before}→{after}")

def test_mirror_unknown_cc_ignored():
    m = TraktorMirror()
    result = m.apply_message(cc(0, 99, 64))  # unbekannter CC
    assert result is None
    ok("mirror_unknown_cc_ignored", "CC99 → None")

def test_mirror_unknown_channel_ignored():
    m = TraktorMirror()
    result = m.apply_message(cc(7, 1, 127))  # CH8 = kein Deck
    assert result is None
    ok("mirror_unknown_channel_ignored", "CH8 → None")

def test_mirror_snapshot_structure():
    m = TraktorMirror()
    snap = m.snapshot()
    assert "decks" in snap
    assert set(snap["decks"].keys()) == {"A", "B", "C", "D"}
    assert "event_count" in snap
    assert "uptime_s" in snap
    ok("mirror_snapshot_structure", f"keys={sorted(snap['decks'].keys())}")

def test_mirror_event_count():
    m = TraktorMirror()
    m.apply_message(cc(0, 1, 127))
    m.apply_message(cc(1, 4, 64))
    m.apply_message(note_on(0, 0))
    assert m.snapshot()["event_count"] == 3
    ok("mirror_event_count", "3 Events gezählt")

def test_deck_state_to_dict():
    d = DeckState("A")
    d.play = True
    d.bpm_msb = 80   # 80+60 = 140 BPM
    d.bpm_lsb = 25   # → 140.25
    dct = d.to_dict()
    assert dct["play"] is True
    assert abs(dct["bpm"] - 140.25) < 0.01
    ok("deck_state_to_dict", f"play=True, bpm={dct['bpm']}")


# ---------- Runner ----------

TESTS = [
    test_deck_channels,
    test_cc_map,
    test_cc_to_bool,
    test_cc_to_float,
    test_bpm_from_msb_lsb,
    test_mirror_play_stop,
    test_mirror_deck_isolation,
    test_mirror_volume,
    test_mirror_eq,
    test_mirror_crossfader,
    test_mirror_bpm,
    test_mirror_beat_pulse,
    test_mirror_unknown_cc_ignored,
    test_mirror_unknown_channel_ignored,
    test_mirror_snapshot_structure,
    test_mirror_event_count,
    test_deck_state_to_dict,
]

if __name__ == "__main__":
    print(f"Running {len(TESTS)} Traktor-Bridge-Selftests...\n")
    failed = []
    for t in TESTS:
        try:
            t()
        except Exception as e:
            print(f"  {t.__name__} FAIL -> {e}")
            failed.append(t.__name__)
    print()
    if failed:
        print(f"[FAIL] {len(failed)}/{len(TESTS)} fehlgeschlagen: {failed}")
        raise SystemExit(1)
    else:
        print(f"[OK] alle {len(TESTS)} Traktor-Bridge-Selftests bestanden.")
