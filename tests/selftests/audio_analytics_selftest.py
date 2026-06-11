"""
Selftest für runtime/persona/audio_analytics.py — Sprint E1.

Komplett autonom: erzeugt synthetisches Audio (Sinus, Rauschen, Stereo
mit bekannter Korrelation), schreibt temporäre WAV-Dateien, läuft alle
Mess-Funktionen drüber und prüft die Ergebnisse gegen erwartete Werte.

Aufruf:
    python -m tests.selftests.audio_analytics_selftest

Ohne externe Audio-Files. Zeigt die Funktion des Audio-Analytics-Layers.
"""

from __future__ import annotations

import math
import sys
import tempfile
from pathlib import Path

import numpy as np
import soundfile as sf

ROOT = Path(__file__).resolve().parent.parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from runtime.persona.audio_analytics import (  # noqa: E402
    analyze_audio_file,
    load_audio,
    measure_lufs,
    measure_peak_db,
    measure_rms_db,
    measure_spectral_bands,
    measure_stereo,
    measure_true_peak_db,
)


SAMPLE_RATE = 48000
DURATION_S = 5.0
N_SAMPLES = int(SAMPLE_RATE * DURATION_S)


# ---------- Synthese-Helfer ----------

def make_sine(freq_hz: float, amplitude: float = 0.5, duration_s: float = DURATION_S) -> np.ndarray:
    """Mono-Sinus mit definierter Amplitude (linear, 0-1)."""
    n = int(SAMPLE_RATE * duration_s)
    t = np.arange(n, dtype=np.float32) / SAMPLE_RATE
    return amplitude * np.sin(2 * np.pi * freq_hz * t).astype(np.float32)


def make_white_noise(amplitude: float = 0.3, duration_s: float = DURATION_S) -> np.ndarray:
    """Mono-White-Noise."""
    rng = np.random.default_rng(seed=42)
    n = int(SAMPLE_RATE * duration_s)
    return (amplitude * rng.standard_normal(n)).astype(np.float32)


def make_stereo_correlated(mono: np.ndarray) -> np.ndarray:
    """L=R → Korrelation +1.0."""
    return np.stack([mono, mono], axis=1)


def make_stereo_opposite(mono: np.ndarray) -> np.ndarray:
    """L=−R → Korrelation -1.0, mono-fold = 0 (Phase-Auslöschung)."""
    return np.stack([mono, -mono], axis=1)


def write_temp_wav(samples: np.ndarray, suffix: str = ".wav") -> Path:
    """Schreibt Samples in temp-File, returnt Pfad."""
    tmp = tempfile.NamedTemporaryFile(suffix=suffix, delete=False)
    tmp.close()
    sf.write(tmp.name, samples, SAMPLE_RATE)
    return Path(tmp.name)


# ---------- Tests ----------

def test_load_audio_mono() -> None:
    sine = make_sine(1000.0, amplitude=0.5)
    path = write_temp_wav(sine)
    try:
        samples, sr = load_audio(path)
        assert sr == SAMPLE_RATE, sr
        assert samples.shape == (N_SAMPLES,), samples.shape
        assert samples.dtype == np.float32
        print(f"  load_audio_mono OK -> {samples.shape}, sr={sr}")
    finally:
        path.unlink(missing_ok=True)


def test_load_audio_stereo() -> None:
    mono = make_sine(440.0, amplitude=0.4)
    stereo = make_stereo_correlated(mono)
    path = write_temp_wav(stereo)
    try:
        samples, sr = load_audio(path)
        assert sr == SAMPLE_RATE
        assert samples.shape == (N_SAMPLES, 2), samples.shape
        print(f"  load_audio_stereo OK -> {samples.shape}, sr={sr}")
    finally:
        path.unlink(missing_ok=True)


def test_peak_db_matches_amplitude() -> None:
    """Sinus mit Amplitude 0.5 → Peak ≈ 20·log10(0.5) ≈ -6.02 dB."""
    sine = make_sine(1000.0, amplitude=0.5)
    peak_db = measure_peak_db(sine)
    expected = 20.0 * math.log10(0.5)
    assert abs(peak_db - expected) < 0.1, f"Peak {peak_db} dB vs erwartet {expected:.2f}"
    print(f"  peak_db_matches_amplitude OK -> Sinus 0.5 -> {peak_db:.2f} dB (erwartet {expected:.2f})")


def test_rms_db_sine_is_3db_below_peak() -> None:
    """Sinus: RMS = Peak / sqrt(2) → -3.01 dB unter Peak."""
    sine = make_sine(1000.0, amplitude=0.5)
    peak_db = measure_peak_db(sine)
    rms_db = measure_rms_db(sine)
    diff = peak_db - rms_db
    assert abs(diff - 3.01) < 0.2, f"Peak-RMS-Diff {diff:.2f} dB, erwartet ~3.01"
    print(f"  rms_db_sine_3db OK -> Peak {peak_db:.2f}, RMS {rms_db:.2f}, Diff {diff:.2f} dB")


def test_true_peak_above_sample_peak() -> None:
    """True-Peak (4× Oversampling) muss >= Sample-Peak sein."""
    sine = make_sine(1000.0, amplitude=0.7)
    peak_db = measure_peak_db(sine)
    tp_db = measure_true_peak_db(sine, SAMPLE_RATE)
    assert tp_db >= peak_db - 0.5, f"TP {tp_db:.2f} sollte >= Peak {peak_db:.2f} sein"
    print(f"  true_peak_above_sample OK -> Sample-Peak {peak_db:.2f}, True-Peak {tp_db:.2f} dB")


def test_lufs_in_expected_range() -> None:
    """Sinus mit -6 dB Peak → ungefähr -9 LUFS."""
    sine = make_sine(1000.0, amplitude=0.5, duration_s=10.0)  # >3s für ST-Window
    integrated, st_max = measure_lufs(sine, SAMPLE_RATE)
    # 1 kHz Sinus mit -6 dB Peak → LUFS-I ≈ -9 LUFS (K-Weighting bei 1k ≈ 0 dB)
    assert -12 < integrated < -6, f"LUFS-I {integrated} ausserhalb erwartetem Range -12..-6"
    print(f"  lufs_in_expected_range OK -> LUFS-I {integrated:.1f}, ST-max {st_max:.1f}")


def test_spectrum_sine_in_correct_band() -> None:
    """1 kHz Sinus → 'mid'-Band (250-4000) dominiert."""
    sine = make_sine(1000.0, amplitude=0.5)
    spec = measure_spectral_bands(sine, SAMPLE_RATE)
    # Mid muss klar dominieren über andere
    assert spec.mid_db > spec.sub_db + 30, f"mid {spec.mid_db} vs sub {spec.sub_db}"
    assert spec.mid_db > spec.low_db + 30, f"mid {spec.mid_db} vs low {spec.low_db}"
    assert spec.mid_db > spec.high_db + 30, f"mid {spec.mid_db} vs high {spec.high_db}"
    assert spec.mid_db > spec.air_db + 30, f"mid {spec.mid_db} vs air {spec.air_db}"
    print(f"  spectrum_sine_band OK -> mid={spec.mid_db:.1f}, sub={spec.sub_db:.1f}, low={spec.low_db:.1f}, high={spec.high_db:.1f}, air={spec.air_db:.1f}")


def test_spectrum_50hz_sine_in_sub_band() -> None:
    """50 Hz Sinus → 'sub'-Band dominiert."""
    sine = make_sine(50.0, amplitude=0.5)
    spec = measure_spectral_bands(sine, SAMPLE_RATE)
    assert spec.sub_db > spec.mid_db + 20, f"sub {spec.sub_db} vs mid {spec.mid_db}"
    print(f"  spectrum_50hz_in_sub OK -> sub={spec.sub_db:.1f}, mid={spec.mid_db:.1f}")


def test_stereo_correlated_full_correlation() -> None:
    """L=R → Korrelation = 1.0, mono_ok=True."""
    sine = make_sine(440.0, amplitude=0.5)
    stereo = make_stereo_correlated(sine)
    s = measure_stereo(stereo, SAMPLE_RATE)
    assert abs(s.correlation - 1.0) < 0.01, f"correlation {s.correlation}"
    assert s.is_stereo is True
    assert s.mono_compatibility_ok is True
    print(f"  stereo_correlated_full OK -> corr={s.correlation:.3f}, mono_ok={s.mono_compatibility_ok}")


def test_stereo_opposite_phase_breaks_mono() -> None:
    """L=−R (180°) → corr ≈ -1, mono-fold = 0 → mono_ok=False."""
    sine = make_sine(80.0, amplitude=0.5)  # Bass-Frequenz < 200 Hz
    stereo = make_stereo_opposite(sine)
    s = measure_stereo(stereo, SAMPLE_RATE)
    assert s.correlation < -0.95, f"correlation {s.correlation}, sollte ≈ -1"
    assert s.mono_compatibility_ok is False, "Mono-Fold sollte fehlschlagen"
    print(f"  stereo_opposite_breaks_mono OK -> corr={s.correlation:.3f}, mono_ok={s.mono_compatibility_ok}")


def test_analyze_audio_file_full_pipeline() -> None:
    """End-to-End: temp WAV schreiben, analyze_audio_file aufrufen, Schema prüfen."""
    sine = make_sine(440.0, amplitude=0.4)
    stereo = make_stereo_correlated(sine)
    path = write_temp_wav(stereo)
    try:
        result = analyze_audio_file(path)
        d = result.to_dict()
        assert "meta" in d and "loudness" in d and "spectrum" in d and "stereo" in d
        assert d["meta"]["channels"] == 2
        assert d["meta"]["sample_rate_hz"] == SAMPLE_RATE
        assert abs(d["meta"]["duration_s"] - DURATION_S) < 0.01
        assert d["loudness"]["peak_db"] < 0  # negativ in dB FS
        print(f"  analyze_audio_file_full_pipeline OK ->")
        print(f"    meta: {d['meta']['channels']}ch @ {d['meta']['sample_rate_hz']}Hz, {d['meta']['duration_s']:.1f}s")
        print(f"    loudness: peak={d['loudness']['peak_db']:.1f}, rms={d['loudness']['rms_db']:.1f}, LUFS-I={d['loudness']['lufs_integrated']:.1f}, TP={d['loudness']['true_peak_db']:.1f}")
        print(f"    spectrum: sub={d['spectrum']['sub_db']:.1f}, low={d['spectrum']['low_db']:.1f}, mid={d['spectrum']['mid_db']:.1f}, high={d['spectrum']['high_db']:.1f}, air={d['spectrum']['air_db']:.1f}")
        print(f"    stereo: corr={d['stereo']['correlation']:.3f}, mono_ok={d['stereo']['mono_compatibility_ok']}, side/mid={d['stereo']['side_to_mid_ratio_db']:.1f}")
    finally:
        path.unlink(missing_ok=True)


def test_analyze_silence_file_safe() -> None:
    """Silent file darf nicht crashen — Floor-Werte zurückgeben."""
    silence = np.zeros(N_SAMPLES, dtype=np.float32)
    path = write_temp_wav(silence)
    try:
        result = analyze_audio_file(path)
        assert result.loudness.peak_db <= -150, f"peak {result.loudness.peak_db}"
        print(f"  analyze_silence_safe OK -> peak={result.loudness.peak_db:.1f}, LUFS-I={result.loudness.lufs_integrated:.1f}")
    finally:
        path.unlink(missing_ok=True)


def test_file_not_found_raises() -> None:
    try:
        analyze_audio_file("/nonexistent/file.wav")
    except FileNotFoundError:
        print(f"  file_not_found_raises OK")
        return
    raise AssertionError("Erwartet FileNotFoundError")


# ---------- Mastering-Audit Tests ----------


def test_audit_detects_clipping_critical() -> None:
    """Audio mit Peak ~0 dB → Audit liefert critical-Finding für Headroom."""
    from runtime.persona.mastering_audit import audit_audio_analysis  # noqa: WPS433
    sine = make_sine(1000.0, amplitude=0.99)  # ~0 dB Peak
    path = write_temp_wav(sine)
    try:
        analysis = analyze_audio_file(path)
        report = audit_audio_analysis(analysis, genre_id="trip_hop", platform_id="spotify")
        crit_findings = [f for f in report.findings if f.severity == "critical"]
        headroom_findings = [f for f in crit_findings if f.field == "headroom"]
        assert len(headroom_findings) > 0, f"Headroom-Critical fehlt: {report.findings}"
        print(f"  audit_detects_clipping OK -> {len(crit_findings)} critical findings")
    finally:
        path.unlink(missing_ok=True)


def test_audit_detects_mono_phase_problem() -> None:
    """L=−R → mono_compatibility=False → Audit liefert critical-Finding."""
    from runtime.persona.mastering_audit import audit_audio_analysis  # noqa: WPS433
    sine = make_sine(80.0, amplitude=0.5)
    stereo = make_stereo_opposite(sine)
    path = write_temp_wav(stereo)
    try:
        analysis = analyze_audio_file(path)
        report = audit_audio_analysis(analysis, genre_id="trip_hop", platform_id="spotify")
        mono_findings = [f for f in report.findings if f.field == "stereo.mono"]
        assert len(mono_findings) == 1, f"Mono-Critical fehlt: {report.findings}"
        assert mono_findings[0].severity == "critical"
        print(f"  audit_detects_mono_phase OK -> {mono_findings[0].message[:60]}...")
    finally:
        path.unlink(missing_ok=True)


def test_audit_lufs_vs_spotify_target() -> None:
    """LUFS-I ~-6 (sehr laut) → suggestive Finding gegenüber Spotify -14."""
    from runtime.persona.mastering_audit import audit_audio_analysis  # noqa: WPS433
    sine = make_sine(1000.0, amplitude=0.5, duration_s=10.0)
    path = write_temp_wav(sine)
    try:
        analysis = analyze_audio_file(path)
        report = audit_audio_analysis(analysis, genre_id="trip_hop", platform_id="spotify")
        lufs_findings = [f for f in report.findings if f.field == "lufs"]
        assert len(lufs_findings) == 1, f"LUFS-Finding fehlt: {report.findings}"
        # Sinus -6 LUFS-I vs Spotify -14 → +8 dB lauter → suggestive
        assert lufs_findings[0].severity == "suggestive"
        print(f"  audit_lufs_spotify OK -> {lufs_findings[0].message[:80]}...")
    finally:
        path.unlink(missing_ok=True)


def test_audit_to_dict_serializable() -> None:
    """Audit-Bericht muss JSON-tauglich sein (keine -inf/NaN-Bombs)."""
    from runtime.persona.mastering_audit import audit_audio_analysis  # noqa: WPS433
    import json as _json
    silence = np.zeros(N_SAMPLES, dtype=np.float32)
    path = write_temp_wav(silence)
    try:
        analysis = analyze_audio_file(path)
        report = audit_audio_analysis(analysis, genre_id="trip_hop", platform_id="spotify")
        d = report.to_dict()
        # Muss serializierbar sein
        s = _json.dumps(d, indent=2, allow_nan=False)
        assert "inf" not in s.replace("\"", "").lower() or '"-inf"' in s, "inf-Werte müssen als String"
        print(f"  audit_to_dict_serializable OK -> {len(s)} char JSON, {len(report.findings)} findings")
    finally:
        path.unlink(missing_ok=True)


# ---------- Pre-Settings Tests ----------


def test_pre_settings_drums_role() -> None:
    """Drums-Rolle: HP 35 Hz, Compressor 3:1, GR 3 dB."""
    from runtime.persona.pre_settings import suggest_track_pre_settings  # noqa: WPS433
    noise = make_white_noise(amplitude=0.3, duration_s=4.0)
    path = write_temp_wav(noise)
    try:
        analysis = analyze_audio_file(path)
        s = suggest_track_pre_settings(analysis, track_role="drums", genre_id="trip_hop")
        assert s.high_pass["cutoff_hz"] == 35
        assert s.compressor["ratio"] == 3.0
        assert s.compressor["target_gain_reduction_db"] == 3.0
        assert s.de_esser is None  # kein de-esser für drums
        assert s.limiter is None   # kein limiter ausser master
        print(f"  pre_settings_drums OK -> HP 35Hz, Comp 3:1, GR 3dB, Sat={s.saturation}")
    finally:
        path.unlink(missing_ok=True)


def test_pre_settings_vocal_lead_role() -> None:
    """Vocal-Lead: HP 100 Hz, Compressor 3:1 + 4 dB GR, De-Esser bei high-band-Pegel."""
    from runtime.persona.pre_settings import suggest_track_pre_settings  # noqa: WPS433
    # Simuliere Vocal mit präsenten Höhen: 1 kHz Sinus + 7 kHz Sinus
    base = make_sine(1000.0, amplitude=0.4, duration_s=4.0)
    high = make_sine(7000.0, amplitude=0.3, duration_s=4.0)
    mixed = base + high
    path = write_temp_wav(mixed)
    try:
        analysis = analyze_audio_file(path)
        s = suggest_track_pre_settings(analysis, track_role="vocal_lead", genre_id="trip_hop")
        assert s.high_pass["cutoff_hz"] == 100
        assert s.compressor["target_gain_reduction_db"] == 4.0
        # De-Esser sollte bei dem Material aktiv vorgeschlagen werden
        assert s.de_esser is not None
        assert s.de_esser["frequency_hz"] == 7000
        print(f"  pre_settings_vocal_lead OK -> HP 100Hz, GR 4dB, De-Esser @ {s.de_esser['frequency_hz']} Hz")
    finally:
        path.unlink(missing_ok=True)


def test_pre_settings_master_role_with_limiter() -> None:
    """Master-Rolle: Trip-Hop Genre → subtle compression (max 1.5 GR), Limiter mit Spotify-Target."""
    from runtime.persona.pre_settings import suggest_track_pre_settings  # noqa: WPS433
    sine = make_sine(440.0, amplitude=0.4, duration_s=5.0)
    path = write_temp_wav(make_stereo_correlated(sine))
    try:
        analysis = analyze_audio_file(path)
        s = suggest_track_pre_settings(analysis, track_role="master", genre_id="trip_hop", platform_id="spotify")
        # Trip-Hop Override: max 1.5 dB GR
        assert s.compressor["target_gain_reduction_db"] == 1.5, s.compressor
        # Saturation aktiv (Trip-Hop-Pflicht)
        assert s.saturation is not None
        assert s.saturation["tape_speed_ips"] == 7.5  # Trip-Hop Override
        # Limiter mit Spotify-Target
        assert s.limiter is not None
        assert s.limiter["ceiling_db"] == -1
        assert s.limiter["target_lufs"] == -14
        print(f"  pre_settings_master_trip_hop OK -> Comp 1.5 GR (Trip-Hop subtle), Sat 7.5ips, Limiter -1dB TP @ -14 LUFS")
    finally:
        path.unlink(missing_ok=True)


def test_compare_audio_files_identical() -> None:
    """Identische Files → similarity 1.0, keine Deltas signifikant."""
    from runtime.persona.audio_analytics import compare_audio_files  # noqa: WPS433
    sine = make_sine(440.0, amplitude=0.4, duration_s=4.0)
    path_a = write_temp_wav(sine)
    path_b = write_temp_wav(sine)  # gleiche Daten, andere Datei
    try:
        result = compare_audio_files(path_a, path_b)
        d = result.to_dict()
        assert d["similarity_score"] >= 0.99, f"Identisch sollte ~1.0 sein: {d['similarity_score']}"
        # Loudness-Deltas alle nahe 0
        assert abs(d["deltas"]["loudness"]["peak_db"]) < 0.1
        print(f"  compare_audio_files_identical OK -> similarity={d['similarity_score']}")
    finally:
        path_a.unlink(missing_ok=True)
        path_b.unlink(missing_ok=True)


def test_compare_audio_files_loudness_difference() -> None:
    """A 3 dB lauter als B → similarity < 1.0, Klartext-Note."""
    from runtime.persona.audio_analytics import compare_audio_files  # noqa: WPS433
    loud = make_sine(440.0, amplitude=0.5, duration_s=4.0)   # ~-6 dB peak
    quiet = make_sine(440.0, amplitude=0.1, duration_s=4.0)  # ~-20 dB peak
    path_a = write_temp_wav(loud)
    path_b = write_temp_wav(quiet)
    try:
        result = compare_audio_files(path_a, path_b)
        d = result.to_dict()
        # Peak-Delta substanziell positiv (A lauter)
        assert d["deltas"]["loudness"]["peak_db"] > 10
        # LUFS-Note sollte da sein
        assert any("lauter" in n.lower() for n in d["notes"])
        print(f"  compare_audio_files_loudness_diff OK -> similarity={d['similarity_score']}, {len(d['notes'])} notes")
    finally:
        path_a.unlink(missing_ok=True)
        path_b.unlink(missing_ok=True)


def test_compare_audio_files_spectrum_difference() -> None:
    """50 Hz Sinus vs 5000 Hz Sinus → unterschiedliche Spektrum-Bänder, similarity < 0.7."""
    from runtime.persona.audio_analytics import compare_audio_files  # noqa: WPS433
    sub = make_sine(50.0, amplitude=0.4, duration_s=4.0)
    high = make_sine(5000.0, amplitude=0.4, duration_s=4.0)
    path_a = write_temp_wav(sub)
    path_b = write_temp_wav(high)
    try:
        result = compare_audio_files(path_a, path_b)
        d = result.to_dict()
        # A hat sub-Energie, B hat keine
        assert d["deltas"]["spectrum"]["sub_db"] > 30  # A viel mehr Sub
        # B hat high-Energie, A keine
        assert d["deltas"]["spectrum"]["high_db"] < -30  # A viel weniger High
        assert d["similarity_score"] < 0.7
        print(f"  compare_audio_files_spectrum_diff OK -> similarity={d['similarity_score']}")
    finally:
        path_a.unlink(missing_ok=True)
        path_b.unlink(missing_ok=True)


def test_pre_settings_classical_disables_compressor() -> None:
    """Klassik: Genre-Override deaktiviert Compressor komplett."""
    from runtime.persona.pre_settings import suggest_track_pre_settings  # noqa: WPS433
    sine = make_sine(440.0, amplitude=0.4, duration_s=5.0)
    path = write_temp_wav(make_stereo_correlated(sine))
    try:
        analysis = analyze_audio_file(path)
        s = suggest_track_pre_settings(analysis, track_role="master", genre_id="classical_acoustic")
        assert s.compressor.get("enabled") is False, s.compressor
        # Saturation auch aus für Klassik
        assert s.saturation is None
        print(f"  pre_settings_classical_no_comp OK -> Compressor enabled=False")
    finally:
        path.unlink(missing_ok=True)


# ---------- Runner ----------

ALL_TESTS = [
    test_load_audio_mono,
    test_load_audio_stereo,
    test_peak_db_matches_amplitude,
    test_rms_db_sine_is_3db_below_peak,
    test_true_peak_above_sample_peak,
    test_lufs_in_expected_range,
    test_spectrum_sine_in_correct_band,
    test_spectrum_50hz_sine_in_sub_band,
    test_stereo_correlated_full_correlation,
    test_stereo_opposite_phase_breaks_mono,
    test_analyze_audio_file_full_pipeline,
    test_analyze_silence_file_safe,
    test_file_not_found_raises,
    # Mastering-Audit
    test_audit_detects_clipping_critical,
    test_audit_detects_mono_phase_problem,
    test_audit_lufs_vs_spotify_target,
    test_audit_to_dict_serializable,
    # Pre-Settings
    test_pre_settings_drums_role,
    test_pre_settings_vocal_lead_role,
    test_pre_settings_master_role_with_limiter,
    test_pre_settings_classical_disables_compressor,
    # Sprint F — Reference-Compare
    test_compare_audio_files_identical,
    test_compare_audio_files_loudness_difference,
    test_compare_audio_files_spectrum_difference,
]


def main() -> int:
    print(f"Running {len(ALL_TESTS)} audio-analytics selftests...\n")
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
    print(f"[OK] alle Audio-Analytics-Selftests bestanden ({len(ALL_TESTS)}/{len(ALL_TESTS)}).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
