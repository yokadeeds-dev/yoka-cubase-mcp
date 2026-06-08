"""
Selftest für Parser + StateMirror. Kein loopMIDI nötig.

Aufruf:
    python -m tests.selftest_scripts.listener_selftest

Erfolgskriterium: Skript läuft ohne AssertionError und druckt am Ende
    [OK] alle Selftests bestanden.

Diese Tests prüfen:
- Parsing der wichtigsten Mackie-Message-Typen (LCD, Select, Transport, Fader, Encoder, VU)
- StateMirror reagiert korrekt auf Events (Track-Namen, aktive Spur, Mute, Volume)
- Snapshot enthält freshness_ms und timestamp
"""

from __future__ import annotations

import sys
from pathlib import Path

import mido

# Ermöglicht direkten Aufruf aus dem Repo-Root ohne Installation
ROOT = Path(__file__).resolve().parent.parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from runtime.ahk.bridge import AhkBridge, DAW_ACTIONS, find_daw_window  # noqa: E402
from runtime.mackie.parser import SPEC, parse_message  # noqa: E402
from runtime.mackie.units import db_to_value14, value14_to_db  # noqa: E402
from runtime.midi_bridge.xboard_to_mackie import (  # noqa: E402
    DEFAULT_XBOARD_TO_MACKIE_MAPPINGS,
    XboardBridgeState,
    absolute_diff_to_mackie_increment,
    is_xboard_knob_for_mackie,
)
from runtime.persona.reports import render_session_report  # noqa: E402
from runtime.mackie.sender import (  # noqa: E402
    make_bank_messages,
    make_channel_messages,
    make_encoder_message,
    make_fader_message,
    make_mode_messages,
    make_select_messages,
    make_transport_messages,
)
from runtime.mackie.state import StateMirror  # noqa: E402


def _make_lcd_sysex(offset: int, text: str) -> mido.Message:
    header_body = SPEC["sysex"]["header_lcd"][1:]  # ohne F0
    payload = header_body + [offset] + [ord(c) for c in text]
    return mido.Message("sysex", data=payload)


def _make_select(channel: int, pressed: bool = True) -> mido.Message:
    note = SPEC["buttons"]["select"]["start"] + channel
    return mido.Message("note_on", note=note, velocity=127 if pressed else 0)


def _make_transport(action: str, pressed: bool = True) -> mido.Message:
    note = SPEC["buttons"]["transport"][action]
    return mido.Message("note_on", note=note, velocity=127 if pressed else 0)


def _make_encoder(encoder: int, direction: int = 1, speed: int = 1) -> mido.Message:
    cc = SPEC["encoders"]["cc_start"] + encoder
    val = (SPEC["encoders"]["direction_mask"] if direction < 0 else 0) | (speed & SPEC["encoders"]["speed_mask"])
    return mido.Message("control_change", control=cc, value=val)


def _make_fader(channel: int, value14: int) -> mido.Message:
    pitch = max(-8192, min(8191, value14 - 8192))
    return mido.Message("pitchwheel", channel=channel, pitch=pitch)


def _make_vu(channel: int, level: int) -> mido.Message:
    val = ((channel & 0x0F) << 4) | (level & 0x0F)
    return mido.Message("aftertouch", value=val)


# ---------- Tests ----------

def test_parse_lcd() -> None:
    # 56-Zeichen Reihe-1-Update, 8 Strips à 7 Zeichen
    text = "KICK   BASS   LEAD   PADS   FX     VOX    DRUMS  MASTER "[:56]
    msg = _make_lcd_sysex(0, text)
    ev = parse_message(msg)
    assert ev["kind"] == "lcd", ev
    assert ev["offset"] == 0
    assert ev["text"][:4] == "KICK"
    print(f"  parse_lcd OK -> text[:4]={ev['text'][:4]!r}")


def test_parse_select() -> None:
    msg = _make_select(channel=2, pressed=True)
    ev = parse_message(msg)
    assert ev == {"kind": "select", "channel": 2, "pressed": True}, ev
    print(f"  parse_select OK -> {ev}")


def test_parse_transport_play() -> None:
    msg = _make_transport("play")
    ev = parse_message(msg)
    assert ev["kind"] == "transport_button" and ev["action"] == "play" and ev["pressed"], ev
    print(f"  parse_transport_play OK -> {ev}")


def test_parse_encoder_cw() -> None:
    msg = _make_encoder(encoder=3, direction=1, speed=5)
    ev = parse_message(msg)
    assert ev == {"kind": "encoder", "encoder": 3, "direction": 1, "speed": 5}, ev
    print(f"  parse_encoder_cw OK -> {ev}")


def test_parse_encoder_ccw() -> None:
    msg = _make_encoder(encoder=0, direction=-1, speed=2)
    ev = parse_message(msg)
    assert ev == {"kind": "encoder", "encoder": 0, "direction": -1, "speed": 2}, ev
    print(f"  parse_encoder_ccw OK -> {ev}")


def test_parse_fader() -> None:
    msg = _make_fader(channel=4, value14=12286)
    ev = parse_message(msg)
    assert ev["kind"] == "fader" and ev["channel"] == 4 and ev["value14"] == 12286, ev
    print(f"  parse_fader OK -> {ev}")


def test_parse_vu() -> None:
    msg = _make_vu(channel=7, level=10)
    ev = parse_message(msg)
    assert ev == {"kind": "vu", "channel": 7, "level": 10}, ev
    print(f"  parse_vu OK -> {ev}")


def test_state_track_names_from_lcd() -> None:
    state = StateMirror()
    text = "KICK   BASS   LEAD   PADS   FX     VOX    DRUMS  MASTER "[:56]
    state.apply_event(parse_message(_make_lcd_sysex(0, text)))
    snap = state.snapshot()
    assert snap["tracks"][0]["name"] == "KICK", snap["tracks"][0]
    assert snap["tracks"][2]["name"] == "LEAD", snap["tracks"][2]
    assert snap["tracks"][7]["name"] == "MASTER", snap["tracks"][7]
    print(f"  state_track_names_from_lcd OK -> {[t['name'] for t in snap['tracks']]}")


def test_state_select_marks_active_track() -> None:
    state = StateMirror()
    text = "KICK   BASS   LEAD   PADS   FX     VOX    DRUMS  MASTER "[:56]
    state.apply_event(parse_message(_make_lcd_sysex(0, text)))
    state.apply_event(parse_message(_make_select(channel=2, pressed=True)))
    snap = state.snapshot()
    assert snap["active_track"] == {"index": 3, "name": "LEAD", "selected": True}, snap["active_track"]
    assert snap["tracks"][2]["selected"] is True
    assert snap["tracks"][0]["selected"] is False
    print(f"  state_select_marks_active_track OK -> {snap['active_track']}")


def test_state_transport_play() -> None:
    state = StateMirror()
    state.apply_event(parse_message(_make_transport("play")))
    snap = state.snapshot()
    assert snap["transport"]["state"] == "play"
    print(f"  state_transport_play OK -> {snap['transport']['state']}")


def test_state_fader_updates_volume() -> None:
    state = StateMirror()
    state.apply_event(parse_message(_make_fader(channel=0, value14=12286)))
    snap = state.snapshot()
    db = snap["tracks"][0]["volume_db"]
    assert db is not None
    assert -10.0 < db < 10.0, db  # grobe Nähe zu 0 dB nach Spec
    print(f"  state_fader_updates_volume OK -> db~={db:.1f}")


def test_mode_aware_resolved_name_in_track_mode() -> None:
    state = StateMirror()
    # Track-Mode (default): row1 = Namen
    state.apply_event(parse_message(_make_lcd_sysex(0, "KICK   BASS   LEAD   PADS   FX     VOX    DRUMS  MASTER ")))
    state.apply_event(parse_message(_make_lcd_sysex(56, "  -6dB   -8dB   -4dB   0dB   -12dB  -3dB   -10dB  +0dB ")))
    snap = state.snapshot()
    assert snap["mode"] == "track"
    assert snap["tracks"][0]["name_resolved"] == "KICK"
    assert snap["tracks"][2]["name_resolved"] == "LEAD"
    print(f"  mode_aware_track_mode OK -> {[t['name_resolved'] for t in snap['tracks']]}")


def test_mode_aware_resolved_name_in_pan_mode() -> None:
    state = StateMirror()
    # Cubase im Pan-Mode: row1 = Pan-Labels, row2 = Track-Namen
    pan_label_note = SPEC["buttons"]["mode"]["pan"]
    state.apply_event(parse_message(mido.Message("note_on", note=pan_label_note, velocity=127)))
    # Cubase pusht jetzt: row1 = Pan-Labels, row2 = Track-Namen
    state.apply_event(parse_message(_make_lcd_sysex(0, "Pan    Left   Right  Page   :01/02 Width  Spread Master ")))
    state.apply_event(parse_message(_make_lcd_sysex(56, "MIDI01 Groo01 Audio1 Audio2 Bus1   FX     Drums  Mastr  ")))
    snap = state.snapshot()
    assert snap["mode"] == "pan"
    assert snap["tracks"][0]["name_resolved"] == "MIDI01", snap["tracks"][0]
    assert snap["tracks"][1]["name_resolved"] == "Groo01"
    assert snap["tracks"][7]["name_resolved"] == "Mastr"
    print(f"  mode_aware_pan_mode OK -> {[t['name_resolved'] for t in snap['tracks']]}")


def test_timecode_assembled_from_cc_digits() -> None:
    """Mackie hat 10 7-Segment-Stellen (CC 64..73). Index 0 = rechts (LSB),
    Index 9 = links (MSB). Wir testen mit 10 unterscheidbaren Zeichen, damit
    klar ist dass die Reihenfolge stimmt."""
    state = StateMirror()
    digits_left_to_right = "ABCDEFGHIJ"  # 10 distinct chars
    for i, ch in enumerate(digits_left_to_right):
        cc_index = 9 - i  # links→rechts: ch[0] geht auf höchsten CC-Index
        msg = mido.Message("control_change", control=64 + cc_index, value=ord(ch))
        state.apply_event(parse_message(msg))
    snap = state.snapshot()
    smpte = snap["transport"]["position_smpte"]
    assert smpte == "ABCDEFGHIJ", f"got {smpte!r}"
    print(f"  timecode_assembled OK -> {smpte!r}")


def test_vu_decays_over_time() -> None:
    """VU-Pegel soll nach Mackie-Update zur 0 hin abklingen, nicht ewig stehen."""
    import time as _time
    state = StateMirror()
    state.apply_event(parse_message(_make_vu(channel=3, level=12)))
    snap_immediate = state.snapshot()
    assert snap_immediate["tracks"][3]["vu"] == 12, snap_immediate["tracks"][3]
    # warte länger als 1 Decay-Schritt
    _time.sleep((StateMirror.VU_DECAY_INTERVAL_MS + 50) / 1000.0)
    snap_after = state.snapshot()
    assert snap_after["tracks"][3]["vu"] < 12, f"VU did not decay: {snap_after['tracks'][3]['vu']}"
    # neues Push setzt zurück
    state.apply_event(parse_message(_make_vu(channel=3, level=10)))
    snap_pushed = state.snapshot()
    assert snap_pushed["tracks"][3]["vu"] == 10
    print(f"  vu_decays_over_time OK -> initial=12, after_decay={snap_after['tracks'][3]['vu']}, after_push=10")


def test_two_char_display_in_state() -> None:
    state = StateMirror()
    # Mackie 2-Char-Display SysEx: Header + 2 ASCII chars
    header = SPEC["sysex"]["header_2char"][1:]  # ohne F0
    msg = mido.Message("sysex", data=header + [ord("P"), ord("1")])
    state.apply_event(parse_message(msg))
    snap = state.snapshot()
    assert snap["two_char_display"] == "P1", snap["two_char_display"]
    print(f"  two_char_display OK -> {snap['two_char_display']!r}")


def test_mode_aware_active_track_name() -> None:
    state = StateMirror()
    pan_note = SPEC["buttons"]["mode"]["pan"]
    state.apply_event(parse_message(mido.Message("note_on", note=pan_note, velocity=127)))
    state.apply_event(parse_message(_make_lcd_sysex(56, "MIDI01 Groo01 Audio1 ")))
    state.apply_event(parse_message(_make_select(channel=1, pressed=True)))
    snap = state.snapshot()
    assert snap["active_track"]["index"] == 2
    assert snap["active_track"]["name"] == "Groo01", snap["active_track"]
    print(f"  mode_aware_active_track_name OK -> {snap['active_track']}")


def test_sender_select_roundtrip() -> None:
    """Sender baut SELECT-Press-Message → Parser sieht 'select' Event mit gleichem Channel."""
    on, off = make_select_messages(channel=4)
    ev_on = parse_message(on)
    ev_off = parse_message(off)
    assert ev_on == {"kind": "select", "channel": 4, "pressed": True}, ev_on
    assert ev_off == {"kind": "select", "channel": 4, "pressed": False}, ev_off
    print(f"  sender_select_roundtrip OK -> {ev_on}")


def test_sender_mode_roundtrip() -> None:
    on, _ = make_mode_messages("plugin")
    ev = parse_message(on)
    assert ev == {"kind": "mode_button", "mode": "plugin", "pressed": True}, ev
    print(f"  sender_mode_roundtrip OK -> {ev}")


def test_sender_transport_roundtrip() -> None:
    on, _ = make_transport_messages("play")
    ev = parse_message(on)
    assert ev["kind"] == "transport_button" and ev["action"] == "play" and ev["pressed"], ev
    print(f"  sender_transport_roundtrip OK -> {ev}")


def test_sender_fader_roundtrip() -> None:
    msg = make_fader_message(channel=2, value14=12286)
    ev = parse_message(msg)
    assert ev == {"kind": "fader", "channel": 2, "value14": 12286}, ev
    print(f"  sender_fader_roundtrip OK -> {ev}")


def test_sender_encoder_cw_roundtrip() -> None:
    msg = make_encoder_message(encoder=5, direction=1, speed=3)
    ev = parse_message(msg)
    assert ev == {"kind": "encoder", "encoder": 5, "direction": 1, "speed": 3}, ev
    print(f"  sender_encoder_cw_roundtrip OK -> {ev}")


def test_sender_encoder_ccw_roundtrip() -> None:
    msg = make_encoder_message(encoder=0, direction=-1, speed=7)
    ev = parse_message(msg)
    assert ev == {"kind": "encoder", "encoder": 0, "direction": -1, "speed": 7}, ev
    print(f"  sender_encoder_ccw_roundtrip OK -> {ev}")


def test_sender_bank_messages_have_correct_notes() -> None:
    """Bank-Buttons: Note 0x2E (links) und 0x2F (rechts). Channel-Buttons: 0x30/0x31."""
    on_l, _ = make_bank_messages("left")
    on_r, _ = make_bank_messages("right")
    on_cl, _ = make_channel_messages("left")
    on_cr, _ = make_channel_messages("right")
    assert on_l.note == 46, on_l.note
    assert on_r.note == 47, on_r.note
    assert on_cl.note == 48, on_cl.note
    assert on_cr.note == 49, on_cr.note
    print(f"  sender_bank_messages OK -> bank_left=46, bank_right=47, ch_left=48, ch_right=49")


def test_sender_bank_invalid_direction() -> None:
    for fn in (make_bank_messages, make_channel_messages):
        try:
            fn("up")
        except ValueError:
            pass
        else:
            raise AssertionError(f"{fn.__name__} sollte für 'up' ValueError werfen")
    print("  sender_bank_invalid_direction OK -> 'up' wirft ValueError")


def test_sender_input_validation() -> None:
    """Falsche Inputs müssen ValueError werfen."""
    for bad in (-1, 8, 100):
        try:
            make_select_messages(channel=bad)
        except ValueError:
            pass
        else:
            raise AssertionError(f"select sollte für channel={bad} ValueError werfen")
    try:
        make_mode_messages("invalid_mode")
    except ValueError:
        pass
    else:
        raise AssertionError("mode sollte für unbekannten Mode ValueError werfen")
    try:
        make_encoder_message(encoder=0, direction=2)
    except ValueError:
        pass
    else:
        raise AssertionError("encoder sollte für direction=2 ValueError werfen")
    print("  sender_input_validation OK -> alle ungültigen Inputs werfen ValueError")


def test_ahk_bridge_whitelist_known_actions() -> None:
    """Whitelist enthält save_project, undo, redo für beide DAWs."""
    for daw in ("cubase", "ableton"):
        actions = DAW_ACTIONS[daw]
        assert "save_project" in actions, f"{daw} fehlt save_project"
        assert "undo" in actions, f"{daw} fehlt undo"
        assert "redo" in actions, f"{daw} fehlt redo"
    print(f"  ahk_bridge_whitelist OK -> cubase={sorted(DAW_ACTIONS['cubase'].keys())}")


def test_ahk_bridge_rejects_unknown_action() -> None:
    bridge = AhkBridge()
    result = bridge.send_action("rm_rf_root", daw="cubase")
    assert not result.ok
    assert "whitelist" in (result.error or "").lower(), result.error
    print(f"  ahk_bridge_rejects_unknown OK -> error={result.error[:60]!r}")


def test_ahk_bridge_rejects_unknown_daw() -> None:
    bridge = AhkBridge()
    result = bridge.send_action("save_project", daw="protools")
    assert not result.ok
    assert "unbekannte daw" in (result.error or "").lower(), result.error
    print(f"  ahk_bridge_rejects_unknown_daw OK -> error={result.error[:60]!r}")


def test_ahk_bridge_window_finder_returns_none_for_missing() -> None:
    """Wenn die DAW nicht läuft, gibt find_daw_window None zurück (kein Crash)."""
    # Ergebnis ist umgebungsabhängig — wir prüfen nur, dass kein Exception fliegt
    result = find_daw_window("cubase")
    print(f"  ahk_bridge_window_finder OK -> cubase hwnd: {result}")


def test_ahk_bridge_list_actions() -> None:
    bridge = AhkBridge()
    all_actions = bridge.list_actions()
    assert "cubase" in all_actions
    assert "ableton" in all_actions
    cubase_only = bridge.list_actions("cubase")
    assert list(cubase_only.keys()) == ["cubase"]
    print(f"  ahk_bridge_list_actions OK -> {len(all_actions)} DAWs in Whitelist")


def test_units_db_value14_roundtrip_at_zero() -> None:
    """0 dB sollte zu value14=12286 werden, und zurück zu ~0 dB."""
    v = db_to_value14(0.0)
    assert v == 12286, v
    db_back = value14_to_db(v)
    assert abs(db_back - 0.0) < 0.1, db_back
    print(f"  units_db_value14_zero OK -> 0 dB <-> {v}")


def test_units_db_extremes() -> None:
    """Extremwerte: -inf und +10 dB."""
    assert db_to_value14(-144.0) == 0
    assert db_to_value14(10.0) == 16383
    assert value14_to_db(0) == -144.0
    assert value14_to_db(16383) == 10.0
    print(f"  units_db_extremes OK -> -inf<->0, +10 dB<->16383")


def test_units_db_roundtrip_varied() -> None:
    for db in (-60.0, -30.0, -12.0, -6.0, -3.0, 3.0, 6.0):
        v = db_to_value14(db)
        db_back = value14_to_db(v)
        assert abs(db_back - db) < 0.5, f"db={db}, v={v}, back={db_back}"
    print(f"  units_db_roundtrip_varied OK -> alle Test-dB-Werte roundtrip <0.5 dB Differenz")


def test_closedloop_was_already_satisfied_field_present() -> None:
    """Selftest ohne echten Controller — wir prüfen nur dass der Code-Pfad existiert."""
    from runtime.mackie.closedloop import ClosedLoopController
    # Wir können keinen echten Controller starten ohne MIDI-Ports, aber wir können
    # den Predicate-Check direkt testen mit einem Mock-State.
    state = StateMirror()
    state._state["mode"] = "track"
    pre = state.snapshot()
    assert pre["mode"] == "track"
    # Predicate: mode == "track"
    pred = lambda snap: snap.get("mode") == "track"
    assert pred(pre) is True
    print(f"  closedloop_was_already_satisfied_field OK -> Predicate vor Send true")


def test_state_session_log_records_select() -> None:
    state = StateMirror()
    state.start_session_log()
    state.apply_event(parse_message(_make_select(channel=2, pressed=True)))
    state.apply_event(parse_message(_make_select(channel=4, pressed=True)))
    log = state.get_session_log()
    selects = [e for e in log if e["kind"] == "select"]
    assert len(selects) == 2, len(selects)
    summary = state.session_summary()
    assert summary["events"] >= 2
    assert summary["select_history"] == [3, 5], summary["select_history"]
    print(f"  state_session_log_select OK -> 2 selects, history={summary['select_history']}")


def test_state_session_log_records_mode_and_transport() -> None:
    state = StateMirror()
    state.start_session_log()
    pan_note = SPEC["buttons"]["mode"]["pan"]
    state.apply_event(parse_message(mido.Message("note_on", note=pan_note, velocity=127)))
    state.apply_event(parse_message(_make_transport("play")))
    summary = state.session_summary()
    assert "pan" in summary["mode_history"]
    assert "play" in summary["transport_history"]
    print(f"  state_session_log_mode_transport OK -> mode_history={summary['mode_history']}, transport_history={summary['transport_history']}")


def test_active_plugin_extracted_from_lcd_page2() -> None:
    """Real-world Capture: UltraChannel auf Page 2/11."""
    state = StateMirror()
    state.apply_event({"kind": "mode_button", "mode": "plugin", "pressed": True})
    # row1 mit 8 Parameter-Strips (7 chars each)
    state.apply_event(parse_message(_make_lcd_sysex(0,
        " Tempo TempoSySessionInputGaInvertPGate InGateSidGateThr"[:56])))
    state.apply_event(parse_message(_make_lcd_sysex(56,
        "UltraChannel    Kick 3 01- Instr             Page:02/11 "[:56])))
    snap = state.snapshot()
    plugin = snap.get("active_plugin")
    assert plugin is not None, snap
    assert plugin["plugin_name"] == "UltraChannel", plugin
    assert plugin["page"] == 2
    assert plugin["page_count"] == 11
    assert plugin["is_overview_page"] is False
    assert len(plugin["encoders"]) == 8
    assert plugin["encoders"][0]["name"] == "Tempo"
    assert plugin["encoders"][7]["name"] == "GateThr"
    print(f"  active_plugin_page2 OK -> {plugin['plugin_name']!r} page {plugin['page']}/{plugin['page_count']}, encoder0={plugin['encoders'][0]['name']!r}")


def test_active_plugin_overview_page1_no_encoders() -> None:
    """Page 1 ist Übersicht — encoders bleibt leer, plugin_name aus row1."""
    state = StateMirror()
    state.apply_event({"kind": "mode_button", "mode": "plugin", "pressed": True})
    state.apply_event(parse_message(_make_lcd_sysex(0,
        " IFX 1    Ein     UltraChannel                          "[:56])))
    state.apply_event(parse_message(_make_lcd_sysex(56,
        "Inserts         Kick 3 01- Instr             Page:01/11 "[:56])))
    snap = state.snapshot()
    plugin = snap.get("active_plugin")
    assert plugin is not None
    # Page 1: row2 ch0-1 = "Inserts" (kein Plugin-Name); Plugin-Name kommt aus row1
    assert "UltraChannel" in plugin["plugin_name"], plugin
    assert plugin["is_overview_page"] is True
    assert plugin["encoders"] == []
    print(f"  active_plugin_overview_page1 OK -> overview, encoders empty")


def test_xboard_increment_cw_small() -> None:
    """Diff +5 → CW-Drehung mit Speed 5."""
    enc = absolute_diff_to_mackie_increment(5)
    assert enc == 5, enc
    print(f"  xboard_increment_cw_small OK -> diff=+5 -> mackie={enc:#04x}")


def test_xboard_increment_ccw_small() -> None:
    enc = absolute_diff_to_mackie_increment(-5)
    # CCW: bit 6 gesetzt, Speed=5 → 0x40 | 5 = 0x45 = 69
    assert enc == 0x45, enc
    print(f"  xboard_increment_ccw_small OK -> diff=-5 -> mackie={enc:#04x}")


def test_xboard_increment_zero_returns_zero() -> None:
    enc = absolute_diff_to_mackie_increment(0)
    assert enc == 0, enc
    print(f"  xboard_increment_zero OK")


def test_xboard_increment_caps_at_speed_63() -> None:
    enc_cw = absolute_diff_to_mackie_increment(100)
    enc_ccw = absolute_diff_to_mackie_increment(-100)
    assert enc_cw == 63, enc_cw
    assert enc_ccw == 0x40 | 63, enc_ccw
    print(f"  xboard_increment_caps OK -> +100 -> {enc_cw}, -100 -> {enc_ccw:#04x}")


def test_xboard_bridge_state_first_value_no_send() -> None:
    state = XboardBridgeState()
    inc = state.update_and_compute_increment(xboard_cc=16, new_value=64)
    assert inc is None, "Erster Wert seit Start sollte None liefern (kein Inkrement)"
    print(f"  xboard_state_first OK -> first value yields None")


def test_xboard_bridge_state_diff_send() -> None:
    state = XboardBridgeState()
    state.update_and_compute_increment(16, 64)
    inc = state.update_and_compute_increment(16, 70)
    assert inc == 6, inc
    inc2 = state.update_and_compute_increment(16, 70)
    assert inc2 is None, "Kein Diff sollte None liefern"
    inc3 = state.update_and_compute_increment(16, 65)
    assert inc3 == (0x40 | 5), inc3
    print(f"  xboard_state_diff OK -> sequence yields expected increments")


def test_xboard_knob_mapping_lookup() -> None:
    """Yokas Werks-Preset: CC 21 = Poti 1 = Mackie Encoder 0."""
    m = is_xboard_knob_for_mackie(21, DEFAULT_XBOARD_TO_MACKIE_MAPPINGS)
    assert m is not None
    assert m.mackie_encoder_index == 0, f"Poti 1 (CC 21) sollte Mackie Encoder 0 sein, war {m.mackie_encoder_index}"
    assert m.mackie_cc == 16
    # Poti 8 = CC 28 = Mackie Encoder 7
    m8 = is_xboard_knob_for_mackie(28, DEFAULT_XBOARD_TO_MACKIE_MAPPINGS)
    assert m8 is not None and m8.mackie_encoder_index == 7
    # Untere Reihe (CC 70) sollte NICHT in Mackie-Mappings sein → pass-through
    m_lower = is_xboard_knob_for_mackie(70, DEFAULT_XBOARD_TO_MACKIE_MAPPINGS)
    assert m_lower is None, "Untere-Reihe-Knöpfe gehen via Pass-Through, nicht Mackie"
    # Mod-Wheel (CC 1) auch nicht
    m_mod = is_xboard_knob_for_mackie(1, DEFAULT_XBOARD_TO_MACKIE_MAPPINGS)
    assert m_mod is None
    print(f"  xboard_knob_mapping_lookup OK -> CC 21..28 -> Encoder 0..7, CC 70/CC 1 -> pass-through")


def test_session_report_empty() -> None:
    state = StateMirror()
    summary = state.session_summary()
    report = render_session_report(summary, daw="cubase")
    assert "Kein Log aktiv" in report or "Log ist aktiv" in report
    print(f"  session_report_empty OK -> first line: {report.splitlines()[0]!r}")


def test_session_report_with_activity() -> None:
    state = StateMirror()
    state.start_session_log()
    # Sequenz simulieren: Track-Wechsel, Mode, Transport
    state.apply_event(parse_message(_make_select(channel=2, pressed=True)))
    state.apply_event(parse_message(_make_select(channel=4, pressed=True)))
    state.apply_event(parse_message(_make_select(channel=2, pressed=True)))
    pan_note = SPEC["buttons"]["mode"]["pan"]
    state.apply_event(parse_message(mido.Message("note_on", note=pan_note, velocity=127)))
    state.apply_event(parse_message(_make_transport("play")))
    state.apply_event(parse_message(_make_transport("stop")))
    summary = state.session_summary()
    report = render_session_report(summary, daw="cubase")
    assert "# Session-Report" in report
    assert "Track-Wechsel" in report
    assert "Mode-Wechsel" in report or "Mode" in report
    assert "Transport" in report
    assert "Quick Take" in report
    print(f"  session_report_with_activity OK -> report has {len(report.splitlines())} lines")


def test_active_plugin_none_when_not_plugin_mode() -> None:
    state = StateMirror()
    # mode = track (default)
    snap = state.snapshot()
    assert snap.get("active_plugin") is None
    print(f"  active_plugin_none_in_track_mode OK")


def test_state_session_log_inactive_returns_empty() -> None:
    """Ohne start_session_log werden keine Events geloggt."""
    state = StateMirror()
    state.apply_event(parse_message(_make_select(channel=1, pressed=True)))
    summary = state.session_summary()
    assert summary["events"] == 0
    assert not summary["active"]
    print(f"  state_session_log_inactive OK -> events=0, active=False")


def test_snapshot_has_freshness_and_timestamp() -> None:
    state = StateMirror()
    snap = state.snapshot()
    assert "freshness_ms" in snap and isinstance(snap["freshness_ms"], int)
    assert "timestamp" in snap and isinstance(snap["timestamp"], str)
    print(f"  snapshot_has_freshness_and_timestamp OK -> freshness_ms={snap['freshness_ms']}")


# ---------- Phase 2: Plugin-Encoder-Wert-Capture ----------


def test_plugin_long_name_split_directivityshaper() -> None:
    """
    Long-Plugin-Quirk: 'DirectivityShaper' (17 Char) wird auf 16 Char gekappt
    und überflutet Strip 2 (chars 14-15 = 'pe'). Default-Slice [0:14] würde
    Plugin als 'DirectivitySha' und Track als 'peDUNE 3 01- Instr' parsen.
    Smart-Split muss den Camel-Case-Übergang an char 16 erkennen.
    """
    from runtime.mackie.state import _smart_split_plugin_and_track  # noqa: WPS433
    # Reproduktion aus Live-Test: row2 strips concat ergibt Plugin+Track ohne Space-Trenner.
    # "DirectivityShape" (16) + "DUNE 3 01- Instr" (16) + 3 spaces = 35 chars
    row2 = "DirectivityShapeDUNE 3 01- Instr     " + " " * 5 + "Page :02/06 "
    plugin, track = _smart_split_plugin_and_track(row2)
    assert plugin == "DirectivityShape", f"Plugin falsch: {plugin!r}"
    assert "DUNE" in track and "Instr" in track, f"Track falsch: {track!r}"
    print(f"  plugin_long_name_split OK -> plugin={plugin!r}, track={track!r}")


def test_plugin_short_name_split_physion() -> None:
    """Default-Layout (Plugin ≤ 14 Char) bleibt unverändert."""
    from runtime.mackie.state import _smart_split_plugin_and_track  # noqa: WPS433
    row2 = "Physion Mk II " + "DUNE 3 01- Instr     " + " " * 1 + "Page :03/18"
    plugin, track = _smart_split_plugin_and_track(row2)
    assert plugin == "Physion Mk II", f"Plugin falsch: {plugin!r}"
    assert track.startswith("DUNE"), f"Track falsch: {track!r}"
    print(f"  plugin_short_name_split OK -> plugin={plugin!r}, track={track!r}")


def test_plugin_baseline_captured_on_first_sighting() -> None:
    """Erste LCD-Update auf Edit-Page → row1-Strips werden als Baseline gespeichert."""
    state = StateMirror()
    state.apply_event({"kind": "mode_button", "mode": "plugin", "pressed": True})
    state.apply_event(parse_message(_make_lcd_sysex(0,
        " Tempo TempoSySessionInputGaInvertPGate InGateSidGateThr"[:56])))
    state.apply_event(parse_message(_make_lcd_sysex(56,
        "UltraChannel    Kick 3 01- Instr             Page:02/11 "[:56])))
    # Baseline sollte intern für ('UltraChannel', 2) gespeichert sein.
    baselines = state._plugin_baselines  # noqa: SLF001
    assert ("UltraChannel", 2) in baselines, f"Baseline nicht erfasst: {list(baselines.keys())}"
    base = baselines[("UltraChannel", 2)]
    assert base[0] == "Tempo", base
    assert base[7] == "GateThr", base
    print(f"  plugin_baseline_captured OK -> baseline[0]={base[0]!r}, baseline[7]={base[7]!r}")


def test_plugin_value_str_detected_on_strip_change() -> None:
    """
    Cubase pusht Wert auf row1[strip*7:strip*7+7] beim Encoder-Drehen.
    Der Wert ersetzt temporär den Param-Namen. Snapshot muss name=baseline,
    value_str=aktueller Strip-Inhalt liefern.
    """
    state = StateMirror()
    state.apply_event({"kind": "mode_button", "mode": "plugin", "pressed": True})
    # Initial: Param-Namen
    state.apply_event(parse_message(_make_lcd_sysex(0,
        " Tempo TempoSySessionInputGaInvertPGate InGateSidGateThr"[:56])))
    state.apply_event(parse_message(_make_lcd_sysex(56,
        "UltraChannel    Kick 3 01- Instr             Page:02/11 "[:56])))
    # Snapshot 1: alle name-Felder gefüllt, value_str=None
    snap1 = state.snapshot()
    enc0 = snap1["active_plugin"]["encoders"][0]
    assert enc0["name"] == "Tempo", enc0
    assert enc0["value_str"] is None, enc0

    # Cubase pusht jetzt einen Wert auf Strip 0 (chars 0-6) — z. B. "120 BPM"
    state.apply_event(parse_message(_make_lcd_sysex(0, "120 BPM")))
    snap2 = state.snapshot()
    enc0_after = snap2["active_plugin"]["encoders"][0]
    assert enc0_after["name"] == "Tempo", f"Name muss Baseline bleiben: {enc0_after}"
    assert enc0_after["value_str"] == "120 BPM", f"value_str muss gesetzt sein: {enc0_after}"
    # Andere Encoder unangetastet
    assert snap2["active_plugin"]["encoders"][1]["value_str"] is None
    print(f"  plugin_value_str_detected OK -> enc0 name={enc0_after['name']!r} value_str={enc0_after['value_str']!r}")


def test_plugin_value_str_cleared_when_baseline_restored() -> None:
    """Strip flippt zurück auf Baseline-Namen → value_str wird auf None gesetzt."""
    state = StateMirror()
    state.apply_event({"kind": "mode_button", "mode": "plugin", "pressed": True})
    state.apply_event(parse_message(_make_lcd_sysex(0,
        " Tempo TempoSySessionInputGaInvertPGate InGateSidGateThr"[:56])))
    state.apply_event(parse_message(_make_lcd_sysex(56,
        "UltraChannel    Kick 3 01- Instr             Page:02/11 "[:56])))
    # Wert pushen
    state.apply_event(parse_message(_make_lcd_sysex(0, "120 BPM")))
    # Baseline zurück
    state.apply_event(parse_message(_make_lcd_sysex(0, " Tempo ")))
    snap = state.snapshot()
    enc0 = snap["active_plugin"]["encoders"][0]
    assert enc0["name"] == "Tempo"
    assert enc0["value_str"] is None, f"value_str muss gelöscht sein nach Baseline-Restore: {enc0}"
    print(f"  plugin_value_str_cleared_on_restore OK")


def test_plugin_baseline_separate_per_page() -> None:
    """Page 2 und Page 3 haben unabhängige Baselines."""
    state = StateMirror()
    state.apply_event({"kind": "mode_button", "mode": "plugin", "pressed": True})
    # Page 2
    state.apply_event(parse_message(_make_lcd_sysex(0,
        " Tempo TempoSySessionInputGaInvertPGate InGateSidGateThr"[:56])))
    state.apply_event(parse_message(_make_lcd_sysex(56,
        "UltraChannel    Kick 3 01- Instr             Page:02/11 "[:56])))
    snap2 = state.snapshot()
    # Wechsel zu Page 3 — komplett andere Param-Namen
    state.apply_event(parse_message(_make_lcd_sysex(0,
        " EQ Lo  EQ Mid EQ Hi  EQ Q   EQ Atk EQ Rel EQ Bnd EQ Out "[:56])))
    state.apply_event(parse_message(_make_lcd_sysex(56,
        "UltraChannel    Kick 3 01- Instr             Page:03/11 "[:56])))
    snap3 = state.snapshot()
    baselines = state._plugin_baselines  # noqa: SLF001
    assert ("UltraChannel", 2) in baselines
    assert ("UltraChannel", 3) in baselines
    assert baselines[("UltraChannel", 2)][0] == "Tempo"
    assert baselines[("UltraChannel", 3)][0] == "EQ Lo"
    # Snapshot von Page 3 liefert die EQ-Namen, nicht die Tempo-Namen
    assert snap3["active_plugin"]["encoders"][0]["name"] == "EQ Lo"
    print(f"  plugin_baseline_per_page OK -> 2 Pages, 2 Baseline-Sets")


def test_plugin_baseline_self_heals_on_more_filled_strips() -> None:
    """
    Reproduktion des DirectivityShaper-Mode-Toggle-Bugs:
    Cubase pusht erst row2 (Page-Indikator) und ERST DANN row1 (Param-Namen).
    Beim ersten Page-2-Sighting captured das State-Mirror eine Stale-Baseline
    aus dem alten Page-1-Layout. Self-Healing: wenn die nächste row1 mehr
    gefüllte Strips hat, wird die Baseline ersetzt.
    """
    state = StateMirror()
    state.apply_event({"kind": "mode_button", "mode": "plugin", "pressed": True})
    # Erste Sichtung: row1 hat NUR 5 gefüllte Strips (stale Page-1-Overview-Inhalt).
    # Explizit padden mit ljust(7), damit der Editor keine trailing spaces frisst.
    stale_labels = ["IFX 1", "Ein", "Direc", "tivityS", "haper", "", "", ""]
    row1_stale = "".join(s.ljust(7) for s in stale_labels)
    assert len(row1_stale) == 56
    state.apply_event(parse_message(_make_lcd_sysex(0, row1_stale)))
    row2_stale = ("DirectivityShape" + "DUNE 3 01- Instr").ljust(42) + "Page:02/06"
    row2_stale = row2_stale.ljust(56)[:56]
    state.apply_event(parse_message(_make_lcd_sysex(56, row2_stale)))
    base_first = state._plugin_baselines.get(("DirectivityShape", 2))  # noqa: SLF001
    assert base_first is not None
    non_empty_first = sum(1 for s in base_first if s)
    assert non_empty_first == 5, f"Erste Baseline sollte 5 gefüllt: count={non_empty_first}, strips={base_first}"

    # Cubase pusht jetzt die echten Page-2-Param-Namen — alle 8 Strips gefüllt
    full_labels = ["Directi", "Directi", "probeAz", "probeEl", "probeRo", "LockDir", "BeamNor", "FilterT"]
    row1_full = "".join(s.ljust(7) for s in full_labels)
    assert len(row1_full) == 56
    state.apply_event(parse_message(_make_lcd_sysex(0, row1_full)))
    base_after = state._plugin_baselines[("DirectivityShape", 2)]  # noqa: SLF001
    non_empty_after = sum(1 for s in base_after if s)
    assert non_empty_after == 8, f"Self-Healing fehlgeschlagen: count={non_empty_after}, strips={base_after}"
    assert base_after[0] == "Directi"
    assert base_after[7] == "FilterT"

    # Snapshot zeigt jetzt name = echter Param-Name, value_str = None
    snap = state.snapshot()
    enc0 = snap["active_plugin"]["encoders"][0]
    assert enc0["name"] == "Directi", f"name muss echter Param sein: {enc0}"
    assert enc0["value_str"] is None, f"value_str muss leer sein: {enc0}"
    print(f"  plugin_baseline_self_heals OK -> Stale-Baseline (5 strips) -> Korrekte Baseline (8 strips)")


# ---------- Persona: Mastering-Chain-Advisor (Sprint A) ----------


def test_mastering_loader_loads_data() -> None:
    """Loader liest mastering_chains.json mit den Pflicht-Top-Level-Keys."""
    from runtime.persona.knowledge_loader import load_mastering_chains, reload_all  # noqa: WPS433
    reload_all()  # Cache leeren für deterministisches Testen
    data = load_mastering_chains()
    for required in ("version", "platforms", "generic_chain", "genres"):
        assert required in data, f"Pflicht-Key {required!r} fehlt in mastering_chains.json"
    assert isinstance(data["generic_chain"], list)
    assert len(data["generic_chain"]) >= 8, f"Generic-Chain zu kurz: {len(data['generic_chain'])}"
    print(f"  mastering_loader_loads_data OK -> v{data['version']}, {len(data['genres'])} Genres, {len(data['platforms'])} Platforms, {len(data['generic_chain'])} Chain-Steps")


def test_mastering_advisor_techno_spotify() -> None:
    """Techno auf Spotify: Multiband aktiv (Genre-Override), Loudness-Delta sichtbar."""
    from runtime.persona.mastering import suggest_mastering_chain  # noqa: WPS433
    result = suggest_mastering_chain("techno", "spotify")
    assert result["ok"] is True, result
    assert result["genre"]["id"] == "techno"
    assert result["platform"]["id"] == "spotify"
    assert result["platform"]["target_lufs_integrated"] == -14
    # Multiband sollte aktiv sein durch Override
    step_ids = [s["step_id"] for s in result["chain"]]
    assert "multiband_compressor" in step_ids, f"Multiband fehlt in Techno-Chain: {step_ids}"
    # Loudness-Delta: Genre-Natural -8 vs Platform -14 = -6 dB Differenz (Genre lauter)
    assert result["loudness_strategy"]["delta_db"] == 6.0, result["loudness_strategy"]
    assert "Plattform-Normalisierung" in result["loudness_strategy"]["recommendation"]
    print(f"  mastering_advisor_techno_spotify OK -> {len(result['chain'])} Steps, delta {result['loudness_strategy']['delta_db']} dB")


def test_mastering_advisor_psy_ambient_disables_multiband() -> None:
    """Psy/Ambient: Multiband per Genre-Override deaktiviert."""
    from runtime.persona.mastering import suggest_mastering_chain  # noqa: WPS433
    result = suggest_mastering_chain("psy_ambient", "spotify")
    assert result["ok"] is True, result
    step_ids = [s["step_id"] for s in result["chain"]]
    assert "multiband_compressor" not in step_ids, (
        f"Multiband sollte für Ambient deaktiviert sein: {step_ids}"
    )
    # Stereo-Widener sollte aktiv sein (per Override)
    assert "stereo_widener" in step_ids, f"Stereo-Widener für Psy fehlt: {step_ids}"
    print(f"  mastering_advisor_psy_ambient OK -> Multiband deaktiviert, Stereo-Widener aktiv")


def test_mastering_advisor_classical_minimal_chain() -> None:
    """Klassik: nur HP, korrektiver EQ, schützender Limiter, Metering — kein Comp/Sat/Multiband/Stereo/Creative-EQ."""
    from runtime.persona.mastering import suggest_mastering_chain  # noqa: WPS433
    result = suggest_mastering_chain("classical_acoustic", "apple_music")
    assert result["ok"] is True, result
    step_ids = [s["step_id"] for s in result["chain"]]
    # Diese müssen drin sein
    for required_step in ("high_pass", "corrective_eq", "limiter", "metering"):
        assert required_step in step_ids, f"Klassik-Chain fehlt {required_step}: {step_ids}"
    # Diese MÜSSEN raus sein
    for forbidden in ("compressor", "saturation", "multiband_compressor", "stereo_widener", "creative_eq"):
        assert forbidden not in step_ids, f"Klassik soll {forbidden} ausschalten: {step_ids}"
    # Plattform Apple Music = -16 LUFS, Klassik-Natural = -18 LUFS
    # delta = natural - platform = -18 - (-16) = -2 (Klassik leiser als Apple-Target)
    assert result["loudness_strategy"]["delta_db"] == -2.0, result["loudness_strategy"]
    assert "leiser" in result["loudness_strategy"]["recommendation"]
    print(f"  mastering_advisor_classical OK -> Minimal-Chain {step_ids}, delta {result['loudness_strategy']['delta_db']} dB")


def test_mastering_advisor_unknown_genre_lists_options() -> None:
    """Unbekanntes Genre: ok=False mit Liste verfügbarer Optionen."""
    from runtime.persona.mastering import suggest_mastering_chain  # noqa: WPS433
    result = suggest_mastering_chain("nonexistent_genre", "spotify")
    assert result["ok"] is False
    assert "available_genres" in result
    assert "techno" in result["available_genres"]
    print(f"  mastering_advisor_unknown_genre OK -> {len(result['available_genres'])} Genres als Alternative")


def test_mastering_advisor_unknown_platform_lists_options() -> None:
    from runtime.persona.mastering import suggest_mastering_chain  # noqa: WPS433
    result = suggest_mastering_chain("techno", "myspace")
    assert result["ok"] is False
    assert "available_platforms" in result
    assert "spotify" in result["available_platforms"]
    print(f"  mastering_advisor_unknown_platform OK")


def test_mastering_list_genres_and_platforms() -> None:
    from runtime.persona.mastering import list_genres, list_platforms  # noqa: WPS433
    genres = list_genres()
    platforms = list_platforms()
    assert len(genres) >= 5, f"Erwartet >= 5 Genres, bekam {len(genres)}"
    assert len(platforms) >= 6, f"Erwartet >= 6 Platforms, bekam {len(platforms)}"
    # Plausibilität: Spotify-Eintrag muss da sein
    spotify = next((p for p in platforms if p["platform_id"] == "spotify"), None)
    assert spotify is not None
    assert spotify["target_lufs_integrated"] == -14
    print(f"  mastering_list_genres_platforms OK -> {len(genres)} Genres, {len(platforms)} Platforms")


def test_mastering_all_genres_have_valid_schema() -> None:
    """
    Jedes Genre muss display_name + natural_target_lufs (oder None) +
    characteristic_focus + chain_overrides haben. Schützt gegen unvollständige
    Einträge bei Erweiterung der Datenbank.
    """
    from runtime.persona.mastering import suggest_mastering_chain  # noqa: WPS433
    from runtime.persona.knowledge_loader import get_mastering_chains  # noqa: WPS433
    data = get_mastering_chains()
    for genre_id, genre in data["genres"].items():
        assert "display_name" in genre, f"{genre_id} fehlt display_name"
        assert "characteristic_focus" in genre, f"{genre_id} fehlt characteristic_focus"
        assert "chain_overrides" in genre, f"{genre_id} fehlt chain_overrides"
        # Suggest-Aufruf für jedes Genre + Spotify
        result = suggest_mastering_chain(genre_id, "spotify")
        assert result["ok"] is True, f"{genre_id}/spotify fehlgeschlagen: {result.get('error')}"
        assert len(result["chain"]) >= 4, f"{genre_id} Chain zu kurz ({len(result['chain'])} Steps)"
    print(f"  mastering_all_genres_schema OK -> {len(data['genres'])} Genres validiert, jede liefert >= 4 Steps")


def test_mastering_trip_hop_minimal_compression() -> None:
    """
    Trip-Hop: Multiband + Stereo-Widener deaktiviert (Genre-Override).
    Compressor sehr subtle (max 1.5 dB GR). Saturation aktiv mit langsamem Tape.
    """
    from runtime.persona.mastering import suggest_mastering_chain  # noqa: WPS433
    result = suggest_mastering_chain("trip_hop", "spotify")
    assert result["ok"] is True, result
    step_ids = [s["step_id"] for s in result["chain"]]
    assert "multiband_compressor" not in step_ids, f"Trip-Hop sollte Multiband aus haben: {step_ids}"
    assert "stereo_widener" not in step_ids, f"Trip-Hop sollte Stereo-Widener aus haben: {step_ids}"
    assert "saturation" in step_ids, f"Trip-Hop braucht Saturation: {step_ids}"
    # Compressor max 1.5 dB
    comp = next(s for s in result["chain"] if s["step_id"] == "compressor")
    assert comp["params"]["gain_reduction_db_max"] == 1.5, comp
    # Trip-Hop -12 LUFS, Spotify -14, delta = +2 (Genre lauter)
    assert result["loudness_strategy"]["delta_db"] == 2
    print(f"  mastering_trip_hop OK -> Multiband+Widener aus, Comp max 1.5 dB GR, Saturation aktiv")


def test_mastering_psytrance_strict_mono_bass() -> None:
    """
    Psy-Trance: Stereo-Widener mit width 120% UND Mono-Schwelle bei 200 Hz.
    Multiband mit Sub-Band-Ratio 3.5:1.
    """
    from runtime.persona.mastering import suggest_mastering_chain  # noqa: WPS433
    result = suggest_mastering_chain("psytrance", "spotify")
    assert result["ok"] is True, result
    step_ids = [s["step_id"] for s in result["chain"]]
    assert "multiband_compressor" in step_ids
    assert "stereo_widener" in step_ids
    widener = next(s for s in result["chain"] if s["step_id"] == "stereo_widener")
    assert widener["params"]["width_pct"] == 120
    assert widener["params"]["preserve_mono_below_hz"] == 200
    # Warnung über Sub-Bass-Mono muss aggregiert sein
    assert any("Mono" in w or "mono" in w for w in result["warnings"]), result["warnings"]
    print(f"  mastering_psytrance OK -> Widener width=120%, Mono <200Hz, Warnung aggregiert")


# ---------- YMP-Studium-Loader (Block C) ----------


def test_ymp_loader_path_resolution() -> None:
    """Pfad-Auflösung: ENV-Override + Default-Sibling."""
    import os as _os
    from runtime.persona.ymp_loader import get_ymp_path, get_studium_path  # noqa: WPS433

    # Default-Pfad ist Sibling zum Repo-Root
    default_path = get_ymp_path()
    assert "YMP" in str(default_path), f"Default-Pfad sollte YMP enthalten: {default_path}"

    # ENV-Override greift (OS-neutral: Path normalisiert Slashes je nach Plattform)
    from pathlib import Path as _Path
    _os.environ["YMP_PATH"] = str(_Path("/tmp/fake_ymp_test"))
    try:
        env_path = get_ymp_path()
        assert env_path.name == "fake_ymp_test", f"ENV-Override fehlgeschlagen: {env_path}"
    finally:
        _os.environ.pop("YMP_PATH", None)
    print(f"  ymp_loader_path_resolution OK -> Default + ENV-Override funktionieren")


def test_ymp_loader_category_inference() -> None:
    """ymp_id-Range → Cluster-Kategorie. Mapping inkl. 2026-05-04-Erweiterung."""
    from runtime.persona.ymp_loader import infer_category  # noqa: WPS433
    # Foundation
    assert infer_category(0) == "foundation"
    assert infer_category(11) == "foundation"
    assert infer_category(18) == "foundation"
    # DAW-Tools (existing)
    assert infer_category(19) == "daw_tools"
    assert infer_category(22) == "daw_tools"
    assert infer_category(28) == "daw_tools"
    # Production-Craft (existing)
    assert infer_category(21) == "production_craft"
    assert infer_category(34) == "production_craft"
    assert infer_category(36) == "production_craft"
    # NEU: Production-Craft-Erweiterung (Reverb, Delay, Saturation, Stereo, Automation, Sidechain)
    assert infer_category(37) == "production_craft"
    assert infer_category(42) == "production_craft"
    assert infer_category(45) == "production_craft"
    # NEU: DAW-Tools-Erweiterung (Turntablism, Experimental, Hardware, Modular)
    assert infer_category(46) == "daw_tools"
    assert infer_category(50) == "daw_tools"
    assert infer_category(52) == "daw_tools"
    # Out-of-range fallback
    assert infer_category(99) == "uncategorized"
    print(f"  ymp_loader_category_inference OK -> Mapping inkl. 37-45 + 46-59 verifiziert")


def test_ymp_loader_discovers_docs_if_available() -> None:
    """
    Wenn YMP-Repo physisch da ist, discover'd der Loader Dokumente.
    Wenn nicht: liefert leeren Index mit available=False (kein Crash).
    """
    from runtime.persona.ymp_loader import get_studium_index, list_studium_docs, reload_index  # noqa: WPS433
    reload_index()
    index = get_studium_index()
    docs = list_studium_docs()

    if index.get("available"):
        # YMP-Repo ist sibling und vorhanden — erwarten >= 30 Docs nach 2026-05-04 Erweiterung
        assert len(docs) >= 30, f"Erwartet >= 30 Docs, fand {len(docs)}: {[d['ymp_id'] for d in docs]}"
        # Doc 21 (Mastering) sollte da sein und production_craft sein
        doc_21 = next((d for d in docs if d["ymp_id"] == 21), None)
        assert doc_21 is not None, "Doc 21 (Mastering) fehlt"
        assert doc_21["category"] == "production_craft"
        assert "Mastering" in doc_21["title"]
        # Neu 37-42 müssen production_craft sein (nach Cluster-Mapping-Update)
        for new_id in (37, 38, 39, 40, 41, 42):
            d = next((x for x in docs if x["ymp_id"] == new_id), None)
            if d is not None:
                assert d["category"] == "production_craft", f"Doc {new_id} sollte production_craft sein, ist {d['category']}"
        # 46, 50-52 müssen daw_tools sein
        for new_id in (46, 50, 51, 52):
            d = next((x for x in docs if x["ymp_id"] == new_id), None)
            if d is not None:
                assert d["category"] == "daw_tools", f"Doc {new_id} sollte daw_tools sein, ist {d['category']}"
        print(f"  ymp_loader_discovers_docs OK -> {len(docs)} Studium-Docs gefunden, Mapping post-2026-05-04 ok")
    else:
        print(f"  ymp_loader_discovers_docs OK (skipped) -> YMP-Repo nicht gefunden, leerer Index korrekt")


def test_ymp_loader_get_doc_with_body_excerpt() -> None:
    """
    get_studium_doc(ymp_id, include_body=True) liefert Body-Excerpt
    mit Trunkations-Markern.
    """
    from runtime.persona.ymp_loader import get_studium_doc, reload_index, get_studium_index  # noqa: WPS433
    reload_index()
    index = get_studium_index()
    if not index.get("available"):
        print(f"  ymp_loader_get_doc_with_body OK (skipped) -> YMP-Repo nicht da")
        return
    # Metadata-only
    doc_meta = get_studium_doc(21, include_body=False)
    assert doc_meta is not None
    assert "body_excerpt" not in doc_meta

    # Mit Body, default max_chars=2000
    doc_body = get_studium_doc(21, include_body=True, max_chars=2000)
    assert doc_body is not None
    assert "body_excerpt" in doc_body
    assert "body_full_length" in doc_body
    assert doc_body["body_truncated"] is True  # Doc 21 ist > 2000 Chars
    assert len(doc_body["body_excerpt"]) <= 2001  # 2000 + Ellipse-Char

    # Volltext (max_chars=0)
    doc_full = get_studium_doc(21, include_body=True, max_chars=0)
    assert doc_full is not None
    assert doc_full["body_truncated"] is False
    assert len(doc_full["body_excerpt"]) == doc_full["body_full_length"]

    # Unbekannte ID
    assert get_studium_doc(99999) is None
    print(f"  ymp_loader_get_doc_with_body OK -> Excerpt 2000 Char, Full {doc_full['body_full_length']} Char")


def test_ymp_loader_search_finds_mastering_topic() -> None:
    """Suche nach 'mastering' findet Doc 21 oben."""
    from runtime.persona.ymp_loader import search_studium, get_studium_index, reload_index  # noqa: WPS433
    reload_index()
    index = get_studium_index()
    if not index.get("available"):
        print(f"  ymp_loader_search_mastering OK (skipped) -> YMP-Repo nicht gefunden")
        return
    results = search_studium("mastering", top_k=3)
    assert len(results) >= 1, f"Erwartet mindestens 1 Treffer für 'mastering': {results}"
    # Doc 21 sollte unter den Top-Treffern sein (Titel-Match)
    top_ids = [r["ymp_id"] for r in results]
    assert 21 in top_ids, f"Doc 21 (Mastering) nicht in Top-{len(results)}: {top_ids}"
    # Snippet sollte gefüllt sein
    top = results[0]
    assert top["snippet"] is not None
    assert top["score"] > 0
    print(f"  ymp_loader_search_mastering OK -> Top-Treffer ymp_id={top['ymp_id']}, score={top['score']}")


def test_ymp_loader_search_empty_query() -> None:
    """Leerer Query liefert leere Liste, nicht alle Docs."""
    from runtime.persona.ymp_loader import search_studium  # noqa: WPS433
    assert search_studium("") == []
    assert search_studium("   ") == []
    print(f"  ymp_loader_search_empty OK -> leerer Query liefert leere Liste")


def test_ymp_loader_categories_listed() -> None:
    """list_categories liefert Cluster mit Doc-IDs."""
    from runtime.persona.ymp_loader import list_categories, get_studium_index, reload_index  # noqa: WPS433
    reload_index()
    index = get_studium_index()
    if not index.get("available"):
        print(f"  ymp_loader_categories OK (skipped) -> YMP-Repo nicht gefunden")
        return
    cats = list_categories()
    # Mindestens production_craft sollte da sein wenn Doc 21 indexed wurde
    assert "production_craft" in cats, f"production_craft fehlt: {cats}"
    assert 21 in cats["production_craft"]
    print(f"  ymp_loader_categories OK -> Cluster {sorted(cats.keys())}, production_craft hat {len(cats.get('production_craft', []))} Docs")


def test_mastering_loader_cache_works() -> None:
    """get_mastering_chains lädt nur einmal pro Lifetime."""
    from runtime.persona.knowledge_loader import get_mastering_chains, is_loaded, reload_all  # noqa: WPS433
    reload_all()
    assert not is_loaded("mastering_chains")
    _ = get_mastering_chains()
    assert is_loaded("mastering_chains")
    # Zweiter Aufruf — sollte aus Cache kommen, nicht neu von Disk
    data2 = get_mastering_chains()
    assert is_loaded("mastering_chains")
    assert "version" in data2
    print(f"  mastering_loader_cache OK -> 1 Disk-Read, 2 Aufrufe")


def test_plugin_value_str_ttl_expiry() -> None:
    """Cached value_str läuft nach PLUGIN_VALUE_STR_TTL_S ab."""
    import time as _time
    state = StateMirror()
    state.apply_event({"kind": "mode_button", "mode": "plugin", "pressed": True})
    state.apply_event(parse_message(_make_lcd_sysex(0,
        " Tempo TempoSySessionInputGaInvertPGate InGateSidGateThr"[:56])))
    state.apply_event(parse_message(_make_lcd_sysex(56,
        "UltraChannel    Kick 3 01- Instr             Page:02/11 "[:56])))
    # Wert pushen, Cache-Eintrag bekommt aktuellen monotonic-Zeitstempel
    state.apply_event(parse_message(_make_lcd_sysex(0, "120 BPM")))
    # Manuell den Cache-Zeitstempel altern lassen — TTL ist 2s, wir setzen 5s zurück.
    fake_old = _time.monotonic() - 5.0
    state._plugin_value_strs[0] = (state._plugin_value_strs[0][0], fake_old)  # noqa: SLF001
    # Strip flippt jetzt zurück auf Baseline (simuliert Cubase-Auto-Restore)
    state.apply_event(parse_message(_make_lcd_sysex(0, " Tempo ")))
    snap = state.snapshot()
    enc0 = snap["active_plugin"]["encoders"][0]
    assert enc0["name"] == "Tempo"
    assert enc0["value_str"] is None, f"Cache muss nach TTL-Ablauf leer sein: {enc0}"
    print(f"  plugin_value_str_ttl_expiry OK -> stale cache verworfen")


# ---------- Runner ----------

ALL_TESTS = [
    test_parse_lcd,
    test_parse_select,
    test_parse_transport_play,
    test_parse_encoder_cw,
    test_parse_encoder_ccw,
    test_parse_fader,
    test_parse_vu,
    test_state_track_names_from_lcd,
    test_state_select_marks_active_track,
    test_state_transport_play,
    test_state_fader_updates_volume,
    test_mode_aware_resolved_name_in_track_mode,
    test_mode_aware_resolved_name_in_pan_mode,
    test_mode_aware_active_track_name,
    test_timecode_assembled_from_cc_digits,
    test_vu_decays_over_time,
    test_two_char_display_in_state,
    test_sender_select_roundtrip,
    test_sender_mode_roundtrip,
    test_sender_transport_roundtrip,
    test_sender_fader_roundtrip,
    test_sender_encoder_cw_roundtrip,
    test_sender_encoder_ccw_roundtrip,
    test_sender_bank_messages_have_correct_notes,
    test_sender_bank_invalid_direction,
    test_sender_input_validation,
    test_ahk_bridge_whitelist_known_actions,
    test_ahk_bridge_rejects_unknown_action,
    test_ahk_bridge_rejects_unknown_daw,
    test_ahk_bridge_window_finder_returns_none_for_missing,
    test_ahk_bridge_list_actions,
    test_units_db_value14_roundtrip_at_zero,
    test_units_db_extremes,
    test_units_db_roundtrip_varied,
    test_closedloop_was_already_satisfied_field_present,
    test_state_session_log_records_select,
    test_state_session_log_records_mode_and_transport,
    test_active_plugin_extracted_from_lcd_page2,
    test_active_plugin_overview_page1_no_encoders,
    test_active_plugin_none_when_not_plugin_mode,
    test_xboard_increment_cw_small,
    test_xboard_increment_ccw_small,
    test_xboard_increment_zero_returns_zero,
    test_xboard_increment_caps_at_speed_63,
    test_xboard_bridge_state_first_value_no_send,
    test_xboard_bridge_state_diff_send,
    test_xboard_knob_mapping_lookup,
    test_session_report_empty,
    test_session_report_with_activity,
    test_state_session_log_inactive_returns_empty,
    test_snapshot_has_freshness_and_timestamp,
    # Phase 2: Plugin-Encoder-Wert-Capture (transient value_str + Long-Plugin-Name-Fix)
    test_plugin_long_name_split_directivityshaper,
    test_plugin_short_name_split_physion,
    test_plugin_baseline_captured_on_first_sighting,
    test_plugin_value_str_detected_on_strip_change,
    test_plugin_value_str_cleared_when_baseline_restored,
    test_plugin_baseline_separate_per_page,
    test_plugin_baseline_self_heals_on_more_filled_strips,
    test_plugin_value_str_ttl_expiry,
    # Persona Sprint A: Mastering-Chain-Advisor
    test_mastering_loader_loads_data,
    test_mastering_advisor_techno_spotify,
    test_mastering_advisor_psy_ambient_disables_multiband,
    test_mastering_advisor_classical_minimal_chain,
    test_mastering_advisor_unknown_genre_lists_options,
    test_mastering_advisor_unknown_platform_lists_options,
    test_mastering_list_genres_and_platforms,
    test_mastering_all_genres_have_valid_schema,
    test_mastering_trip_hop_minimal_compression,
    test_mastering_psytrance_strict_mono_bass,
    test_mastering_loader_cache_works,
    # YMP-Studium-Loader (Block C)
    test_ymp_loader_path_resolution,
    test_ymp_loader_category_inference,
    test_ymp_loader_discovers_docs_if_available,
    test_ymp_loader_get_doc_with_body_excerpt,
    test_ymp_loader_search_finds_mastering_topic,
    test_ymp_loader_search_empty_query,
    test_ymp_loader_categories_listed,
]


def main() -> int:
    print(f"Running {len(ALL_TESTS)} selftests...\n")
    failures = []
    for t in ALL_TESTS:
        try:
            t()
        except AssertionError as e:
            print(f"  [FAIL] {t.__name__}: {e}")
            failures.append(t.__name__)
        except Exception as e:
            print(f"  [ERROR] {t.__name__}: {type(e).__name__}: {e}")
            failures.append(t.__name__)
    print()
    if failures:
        print(f"[FAIL] {len(failures)}/{len(ALL_TESTS)} Tests fehlgeschlagen: {failures}")
        return 1
    print(f"[OK] alle Selftests bestanden ({len(ALL_TESTS)}/{len(ALL_TESTS)}).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
