"""
Selftest fuer runtime/persona/plugin_control.py.

Testet:
- Bus-zu-Kanal-Mapping
- Value-zu-CC-Konvertierung (linear, log, discrete, threshold_64)
- Layout-Lookup (CC + Range pro Param)
- Preset-Laden + Anwenden (mit Port-Fail = OK weil kein MIDI im Test)

Sendet KEINE echten MIDI-Events (Port-Open scheitert sicher).

Aufruf:
    python -m tests.selftests.plugin_control_selftest
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from runtime.persona.plugin_control import (  # noqa: E402
    _lookup_cc,
    apply_preset,
    bus_to_channel,
    cubase_channel_to_mido,
    list_presets,
    reload,
    set_pro_c2,
    set_pro_q3_band,
    value_to_cc,
)


# ---------- Bus-Kanal-Konvention ----------

def test_bus_to_channel_known() -> None:
    assert bus_to_channel("bass") == 1
    assert bus_to_channel("drums") == 2
    assert bus_to_channel("synth") == 3
    assert bus_to_channel("vocals") == 4
    assert bus_to_channel("master") == 16
    print("  bus_to_channel_known OK -> Konvention 1=Bass...16=Master")


def test_bus_to_channel_unknown_raises() -> None:
    try:
        bus_to_channel("flarp")
        assert False, "Should have raised ValueError"
    except ValueError as e:
        assert "flarp" in str(e)
    print("  bus_to_channel_unknown_raises OK")


def test_cubase_channel_to_mido() -> None:
    assert cubase_channel_to_mido(1) == 0
    assert cubase_channel_to_mido(16) == 15
    assert cubase_channel_to_mido(2) == 1
    print("  cubase_channel_to_mido OK")


def test_cubase_channel_out_of_range() -> None:
    for invalid in [0, 17, -1]:
        try:
            cubase_channel_to_mido(invalid)
            assert False, f"Should have raised for {invalid}"
        except ValueError:
            pass
    print("  cubase_channel_out_of_range OK")


# ---------- Value-zu-CC ----------

def test_value_to_cc_linear_threshold() -> None:
    """Threshold-Mapping -60 bis 0 dB. -18 dB -> ~89."""
    cc = value_to_cc(-18.0, range_min=-60.0, range_max=0.0, mapping_type="linear")
    assert 87 <= cc <= 91, f"Erwartet 87-91, bekam {cc}"
    print(f"  value_to_cc_linear_threshold OK -> -18 dB = CC {cc}")


def test_value_to_cc_linear_gain() -> None:
    """Gain-Mapping -30..+30. 0 dB -> 64."""
    cc = value_to_cc(0.0, range_min=-30.0, range_max=30.0, mapping_type="linear")
    assert 63 <= cc <= 65, f"Erwartet 64, bekam {cc}"
    print(f"  value_to_cc_linear_gain OK -> 0 dB = CC {cc}")


def test_value_to_cc_log_frequency() -> None:
    """30 Hz in log [10, 30000] -> ungefaehr CC 17."""
    cc = value_to_cc(30.0, range_min=10.0, range_max=30000.0, mapping_type="log")
    assert 14 <= cc <= 20, f"Erwartet ~17, bekam {cc}"
    print(f"  value_to_cc_log_frequency OK -> 30 Hz = CC {cc}")


def test_value_to_cc_log_1khz() -> None:
    """1000 Hz in log [10, 30000] -> ungefaehr CC 73."""
    cc = value_to_cc(1000.0, range_min=10.0, range_max=30000.0, mapping_type="log")
    assert 70 <= cc <= 76, f"Erwartet ~73, bekam {cc}"
    print(f"  value_to_cc_log_1khz OK -> 1000 Hz = CC {cc}")


def test_value_to_cc_threshold_64_bool() -> None:
    assert value_to_cc(True, mapping_type="threshold_64") == 127
    assert value_to_cc(False, mapping_type="threshold_64") == 0
    print("  value_to_cc_threshold_64_bool OK")


def test_value_to_cc_discrete_string() -> None:
    """discrete_9 mit Filter-Type-String."""
    values = ["Bell", "Low Cut", "Low Shelf", "Notch", "High Cut", "High Shelf", "Band Pass", "Tilt Shelf", "Flat Tilt"]
    cc = value_to_cc("Bell", mapping_type="discrete_9", values_list=values)
    # Bell ist Position 0 -> Mitte des Bin 0 -> CC ~7
    assert 0 <= cc <= 14, f"Erwartet 0-14 fuer Bell, bekam {cc}"
    print(f"  value_to_cc_discrete_string OK -> Bell = CC {cc}")


def test_value_to_cc_discrete_string_invalid() -> None:
    values = ["Bell", "Low Cut"]
    try:
        value_to_cc("Unknown Filter", mapping_type="discrete_9", values_list=values)
        assert False, "Should have raised"
    except ValueError:
        pass
    print("  value_to_cc_discrete_string_invalid OK")


def test_value_to_cc_clamped() -> None:
    """Out-of-range Values clamping."""
    # Sehr negativer Wert -> CC 0
    cc = value_to_cc(-100.0, range_min=-30.0, range_max=30.0, mapping_type="linear")
    assert cc == 0
    # Sehr positiver Wert -> CC 127
    cc = value_to_cc(100.0, range_min=-30.0, range_max=30.0, mapping_type="linear")
    assert cc == 127
    print("  value_to_cc_clamped OK")


# ---------- Layout-Lookup ----------

def test_lookup_cc_pro_q3_band1_freq() -> None:
    """CC20 = Band 1 Frequency in Pro-Q3."""
    reload()
    cc, spec = _lookup_cc("bass", "fabfilter_pro_q3", "Band 1 Frequency")
    assert cc == 20
    assert spec["range_min"] == 10.0
    assert spec["range_max"] == 30000.0
    assert spec["mapping_type"] == "log"
    print(f"  lookup_cc_pro_q3_band1_freq OK -> CC {cc}")


def test_lookup_cc_pro_c2_threshold() -> None:
    """CC48 = Threshold in Pro-C 2."""
    cc, spec = _lookup_cc("drums", "fabfilter_pro_c2", "Threshold")
    assert cc == 48
    assert spec["range_min"] == -60.0
    assert spec["range_max"] == 0.0
    print(f"  lookup_cc_pro_c2_threshold OK -> CC {cc}")


def test_lookup_cc_unknown_plugin() -> None:
    try:
        _lookup_cc("bass", "unknown_plugin", "Threshold")
        assert False, "Should have raised"
    except ValueError as e:
        assert "unknown_plugin" in str(e)
    print("  lookup_cc_unknown_plugin OK")


# ---------- Set-Funktionen (kein MIDI-Erwartung) ----------

def test_set_pro_q3_band_logic() -> None:
    """Pro-Q3 set — Port-Open schlaegt fehl (kein loopMIDI im Test), aber
    Range-Mapping muss durchlaufen sein. Plus alle Params landen in result."""
    result = set_pro_q3_band(
        bus="bass",
        band_num=1,
        freq_hz=30.0,
        gain_db=-2.0,
        q=1.0,
        enabled=True,
        port="nonexistent_port_for_test",
    )
    assert result.plugin == "fabfilter_pro_q3"
    assert result.bus == "bass"
    assert result.channel == 1
    # 4 Params angefragt -> 4 ParamResults
    assert len(result.params) == 4
    # Alle haben cc_value != None (Konvertierung war erfolgreich)
    for p in result.params:
        assert p.cc_value is not None, f"Param {p.param} hat keinen cc_value"
    # all_ok ist False weil Port-Open scheitert
    assert result.all_ok is False
    print(f"  set_pro_q3_band_logic OK -> {len(result.params)} Params konvertiert")


def test_set_pro_q3_band_only_enabled() -> None:
    """Nur enabled=True gesetzt -> nur 1 ParamResult."""
    result = set_pro_q3_band(
        bus="drums", band_num=2, enabled=True, port="nonexistent",
    )
    assert len(result.params) == 1
    assert result.params[0].param == "Band 2 Enabled"
    assert result.params[0].cc_sent == 27  # Band 2 Enabled in Layout
    print(f"  set_pro_q3_band_only_enabled OK -> 1 Param, CC {result.params[0].cc_sent}")


def test_set_pro_q3_band_unknown_bus() -> None:
    try:
        set_pro_q3_band(bus="flarp", band_num=1, freq_hz=30.0)
        assert False, "Should have raised"
    except ValueError:
        pass
    print("  set_pro_q3_band_unknown_bus OK")


def test_set_pro_c2_logic() -> None:
    """Pro-C 2 set — alle 4 Standard-Params."""
    result = set_pro_c2(
        bus="drums",
        threshold_db=-18.0,
        ratio=4.0,
        attack_ms=10.0,
        release_ms=100.0,
        port="nonexistent",
    )
    assert result.plugin == "fabfilter_pro_c2"
    assert result.bus == "drums"
    assert result.channel == 2
    assert len(result.params) == 4
    # CC-Nummern korrekt
    cc_nums = {p.param: p.cc_sent for p in result.params}
    assert cc_nums["Threshold"] == 48
    assert cc_nums["Ratio"] == 49
    assert cc_nums["Attack"] == 50
    assert cc_nums["Release"] == 51
    print(f"  set_pro_c2_logic OK -> 4 Params korrekt gemappt")


# ---------- Preset-System ----------

def test_list_presets_no_filter() -> None:
    presets = list_presets()
    ids = {p["preset_id"] for p in presets}
    assert "triphop_bass_default" in ids
    assert "vocal_lead_classic" in ids
    assert "master_bus_streaming" in ids
    assert len(presets) >= 8, f"Erwartet >=8 Presets, bekam {len(presets)}"
    print(f"  list_presets_no_filter OK -> {len(presets)} Presets")


def test_list_presets_category_filter() -> None:
    bass_presets = list_presets(category="bass")
    assert all(p["category"] == "bass" for p in bass_presets)
    assert len(bass_presets) >= 1
    print(f"  list_presets_category_filter OK -> {len(bass_presets)} Bass-Presets")


def test_apply_preset_unknown() -> None:
    result = apply_preset("nonexistent_preset")
    assert result["ok"] is False
    assert "available_presets" in result
    print("  apply_preset_unknown OK")


def test_apply_preset_triphop_bass() -> None:
    """Preset anwenden — Port-Open scheitert, aber Logic muss durchlaufen."""
    result = apply_preset("triphop_bass_default")
    # ok ist False weil Port nicht da, aber Plugin-Results muessen existieren
    assert "plugin_results" in result
    assert len(result["plugin_results"]) >= 1
    # Erstes Plugin-Result hat Params
    first = result["plugin_results"][0]
    assert "params" in first
    assert len(first["params"]) >= 4  # Band hat 4-6 Params
    print(f"  apply_preset_triphop_bass OK -> {len(result['plugin_results'])} Plugin-Aktionen")


# ---------- discrete_N Domain-Wert vs. Index (Task #17 Fix, 2026-05-21) ----------

def test_value_to_cc_discrete_domain_int() -> None:
    """Slope-Spec hat values_list ['6','12','18','24',...]. Preset gibt 24 als int -> Domain-Match auf '24' = Index 3."""
    # Mitte von Bin 3 = (3 + 0.5) * 127/8 / 127 * 127 = round(55.6) = 56
    cc = value_to_cc(24, mapping_type="discrete_8", values_list=["6", "12", "18", "24", "36", "48", "72", "96"])
    assert cc == 56, f"Slope 24 dB/oct sollte CC 56 ergeben (Bin 3 von 8), got {cc}"
    print(f"  value_to_cc_discrete_domain_int OK -> Slope 24 dB/oct = CC {cc} (Bin 3 von 8)")


def test_value_to_cc_discrete_index_fallback() -> None:
    """Wenn int kein Domain-Wert ist, aber gueltiger Index, dann Index-Fallback."""
    # 0 ist kein Domain-Wert in ['6','12',...] aber gueltiger Index -> wird zu Bin 0
    cc = value_to_cc(0, mapping_type="discrete_8", values_list=["6", "12", "18", "24", "36", "48", "72", "96"])
    assert cc == 8, f"Index 0 sollte CC 8 ergeben (Mitte Bin 0 von 8), got {cc}"
    print(f"  value_to_cc_discrete_index_fallback OK -> Index 0 = CC {cc}")


def test_value_to_cc_discrete_invalid_raises() -> None:
    """Wert der weder Domain-Match noch gueltiger Index ist -> ValueError."""
    try:
        value_to_cc(99, mapping_type="discrete_8", values_list=["6", "12", "18", "24", "36", "48", "72", "96"])
        assert False, "Should have raised"
    except ValueError as e:
        assert "weder" in str(e) or "ausserhalb" in str(e)
    print("  value_to_cc_discrete_invalid_raises OK")


def test_apply_preset_triphop_bass_slope_fix() -> None:
    """Task #17: triphop_bass_default Band-1 Slope=24 muss jetzt grun durchgehen."""
    result = apply_preset("triphop_bass_default", bus="bass", port="nonexistent-port", dry_run=True)
    assert result["dry_run"] is True
    # Suche das Band-1-Slope-Result
    found_slope = False
    for pr in result["plugin_results"]:
        for p in pr["params"]:
            if "Band 1 Slope" in p["param"]:
                found_slope = True
                assert p["ok"] is True, f"Band 1 Slope sollte ok=True sein, got error={p['error']}"
                assert p["cc_value"] is not None
                break
    assert found_slope, "Band 1 Slope nicht im Preset gefunden"
    # Plus: alle 4 plugin_results sollten all_ok=True haben (Task #17 ist gefixt)
    for pr in result["plugin_results"]:
        assert pr["all_ok"], f"plugin_result hat all_ok=False: {pr['plugin']} — {[p for p in pr['params'] if not p['ok']]}"
    print(f"  apply_preset_triphop_bass_slope_fix OK -> alle 4 Plugin-Aktionen all_ok=True")


# ---------- STC dry_run (Suggest-then-Confirm-Pattern, ADR 2026-05-21) ----------

def test_set_pro_q3_band_dry_run() -> None:
    """dry_run=True berechnet CCs, sendet aber nichts (kein Port-Touch)."""
    result = set_pro_q3_band(
        bus="bass", band_num=1, freq_hz=30.0, gain_db=0.0, shape="Low Cut",
        port="definitely-not-existing-port", dry_run=True,
    )
    # Wenn dry_run wirklich greift, sollte trotz nicht-existierendem Port alles "ok" sein
    assert result.dry_run is True
    assert result.all_ok is True
    assert len(result.params) == 3  # Shape + Frequency + Gain
    # Alle Params haben berechnete CC-Werte, kein Send-Versuch
    assert all(p.cc_sent is not None for p in result.params)
    assert all(p.cc_value is not None for p in result.params)
    assert all(p.ok for p in result.params)
    assert all(p.error is None for p in result.params)
    print(f"  set_pro_q3_band_dry_run OK -> dry_run=True, 3 Params berechnet ohne Send")


def test_set_pro_c2_dry_run() -> None:
    """dry_run=True für Pro-C 2."""
    result = set_pro_c2(
        bus="drums", threshold_db=-18.0, ratio=4.0, attack_ms=10.0,
        port="definitely-not-existing-port", dry_run=True,
    )
    assert result.dry_run is True
    assert result.all_ok is True
    assert len(result.params) == 3
    assert all(p.ok for p in result.params)
    print(f"  set_pro_c2_dry_run OK -> dry_run=True, 3 Params ohne Send")


def test_apply_preset_dry_run() -> None:
    """apply_preset(dry_run=True) leitet dry_run an alle Plugin-Calls weiter."""
    result = apply_preset(
        "triphop_bass_default", bus="bass",
        port="definitely-not-existing-port", dry_run=True,
    )
    assert result["dry_run"] is True
    # Auch wenn ok=False wegen Layout-Bug (Slope-Mapping, Task #17), müssen alle
    # plugin_results dry_run=True propagiert haben
    assert all(pr["dry_run"] for pr in result["plugin_results"])
    print(f"  apply_preset_dry_run OK -> dry_run an {len(result['plugin_results'])} Plugin-Calls propagiert")


def test_dry_run_default_is_false() -> None:
    """Backward-compat: ohne expliziten dry_run-Param ist dry_run=False (= apply)."""
    # Wir nutzen einen nonexistent port um zu erkennen dass send_cc versucht wurde
    result = set_pro_q3_band(
        bus="bass", band_num=1, freq_hz=30.0, port="definitely-not-existing-port",
        # KEIN dry_run-Param
    )
    assert result.dry_run is False
    # Send-Versuch sollte ok=False produzieren (Port existiert nicht)
    assert not result.all_ok
    print(f"  dry_run_default_is_false OK -> ohne Param wird gesendet (mit Port-Fail)")


# ---------- Runner ----------

ALL_TESTS = [
    test_bus_to_channel_known,
    test_bus_to_channel_unknown_raises,
    test_cubase_channel_to_mido,
    test_cubase_channel_out_of_range,
    test_value_to_cc_linear_threshold,
    test_value_to_cc_linear_gain,
    test_value_to_cc_log_frequency,
    test_value_to_cc_log_1khz,
    test_value_to_cc_threshold_64_bool,
    test_value_to_cc_discrete_string,
    test_value_to_cc_discrete_string_invalid,
    test_value_to_cc_clamped,
    test_lookup_cc_pro_q3_band1_freq,
    test_lookup_cc_pro_c2_threshold,
    test_lookup_cc_unknown_plugin,
    test_set_pro_q3_band_logic,
    test_set_pro_q3_band_only_enabled,
    test_set_pro_q3_band_unknown_bus,
    test_set_pro_c2_logic,
    test_list_presets_no_filter,
    test_list_presets_category_filter,
    test_apply_preset_unknown,
    test_apply_preset_triphop_bass,
    # discrete_N Domain-Wert Fix (Task #17)
    test_value_to_cc_discrete_domain_int,
    test_value_to_cc_discrete_index_fallback,
    test_value_to_cc_discrete_invalid_raises,
    test_apply_preset_triphop_bass_slope_fix,
    # STC-Pattern Tests (ADR 2026-05-21)
    test_set_pro_q3_band_dry_run,
    test_set_pro_c2_dry_run,
    test_apply_preset_dry_run,
    test_dry_run_default_is_false,
]


def main() -> int:
    print(f"Running {len(ALL_TESTS)} plugin-control selftests...\n")
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
        print(f"[FAIL] {len(failures)}/{len(ALL_TESTS)}: {failures}")
        return 1
    print(f"[OK] alle plugin-control-Selftests bestanden ({len(ALL_TESTS)}/{len(ALL_TESTS)}).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
