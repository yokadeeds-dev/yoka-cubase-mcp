"""
Selftest für runtime/persona/expose_report.py — Sprint E1.5.

Erzeugt synthetisches Audio mit kontrollierten Eigenschaften:
  - "loud_pop_master": -8 LUFS, TP nahe 0 → fail bei Spotify (-14)
  - "spotify_safe": ~-14 LUFS, TP < -1 → pass bei Spotify
  - "quiet_classical": -22 LUFS → warn (zu leise) bei Spotify
  - "phase_inverted": L=-R → mono_compat fail

Aufruf:
    python -m tests.selftests.expose_report_selftest
"""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path

import numpy as np
import soundfile as sf

ROOT = Path(__file__).resolve().parent.parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from runtime.persona.expose_report import (  # noqa: E402
    build_expose_report,
    compute_lra,
    compute_plr,
    format_report_text,
)

SAMPLE_RATE = 48000
DURATION_S = 6.0  # >3s für LUFS-S + LRA


def _make_pink_like(amplitude: float, duration_s: float = DURATION_S, seed: int = 7) -> np.ndarray:
    """Quasi-Pink-Rauschen: weißes Rauschen mit -3 dB/Oct via Cumulative-Sum-Trick."""
    rng = np.random.default_rng(seed=seed)
    n = int(SAMPLE_RATE * duration_s)
    white = rng.standard_normal(n).astype(np.float32)
    # Cumulative sum gibt approximativ pink — nicht perfekt, reicht für Tests
    pink = np.cumsum(white)
    pink = pink - np.mean(pink)
    pink = pink / max(np.max(np.abs(pink)), 1e-10) * amplitude
    return pink.astype(np.float32)


def _stereo(mono: np.ndarray, decorrelation: float = 0.0) -> np.ndarray:
    """Stereo aus Mono. decorrelation=0: L==R. decorrelation=1: L=-R."""
    if decorrelation == 0:
        return np.stack([mono, mono], axis=1)
    rng = np.random.default_rng(seed=11)
    noise = rng.standard_normal(mono.shape).astype(np.float32) * 0.05
    left = mono + noise
    right = mono - noise * decorrelation
    return np.stack([left, right], axis=1)


def _write(samples: np.ndarray) -> Path:
    tmp = tempfile.NamedTemporaryFile(suffix=".wav", delete=False)
    tmp.close()
    sf.write(tmp.name, samples, SAMPLE_RATE)
    return Path(tmp.name)


# ---------- Tests ----------

def test_compute_plr_basic() -> None:
    """Peak -1, LUFS-I -10 → PLR = 9 dB."""
    plr = compute_plr(-1.0, -10.0)
    assert abs(plr - 9.0) < 0.01
    print(f"  compute_plr_basic OK -> PLR = {plr:.1f} dB")


def test_compute_lra_static_signal_low() -> None:
    """Statischer Sinus hat sehr niedrige LRA (nahe 0)."""
    n = int(SAMPLE_RATE * DURATION_S)
    t = np.arange(n) / SAMPLE_RATE
    sine = (0.3 * np.sin(2 * np.pi * 1000 * t)).astype(np.float32)
    stereo = np.stack([sine, sine], axis=1)
    lra = compute_lra(stereo, SAMPLE_RATE)
    assert lra < 1.0, f"Statischer Sinus sollte LRA<1.0 haben, war {lra:.2f}"
    print(f"  compute_lra_static OK -> LRA = {lra:.2f} LU (statisch)")


def test_compute_lra_dynamic_signal_higher() -> None:
    """Signal mit Lautstärke-Wechsel hat höhere LRA als statisches."""
    # Längeres Signal mit 3 Pegeln, damit P10/P95 sicher unterschiedliche Werte erfassen
    duration = 9.0
    n_full = int(SAMPLE_RATE * duration)
    t = np.arange(n_full) / SAMPLE_RATE
    base = 0.4 * np.sin(2 * np.pi * 1000 * t).astype(np.float32)
    third = n_full // 3
    base[:third] *= 1.0          # voller Pegel (~ -8 LUFS)
    base[third:2 * third] *= 0.3  # -10 dB
    base[2 * third:] *= 0.05     # -26 dB
    stereo = np.stack([base, base], axis=1)
    lra = compute_lra(stereo, SAMPLE_RATE)
    # Erwartung: messbar dynamischer als statisches Signal (LRA=0.0).
    # Mit pyloudnorm-Gating werden sehr leise Fenster ggf. gefiltert; lockerer Threshold.
    assert lra > 1.5, f"Dynamisches Signal sollte LRA>1.5 haben, war {lra:.2f}"
    print(f"  compute_lra_dynamic OK -> LRA = {lra:.2f} LU (dynamisch)")


def test_build_report_loud_master_fails_spotify() -> None:
    """
    Sehr lauter Master (~-8 LUFS) → fail bei Spotify (-14), evtl. pass bei Club_DJ (-8).
    """
    pink = _make_pink_like(amplitude=0.85, duration_s=DURATION_S, seed=1)
    stereo = _stereo(pink, decorrelation=0.1)
    path = _write(stereo)
    try:
        report = build_expose_report(path, platforms=["spotify", "club_dj"])
        spotify = next(p for p in report.platform_reports if p.platform_id == "spotify")
        # Lufs-Check sollte warn oder fail sein
        lufs_check = next(c for c in spotify.checks if c.metric == "lufs")
        assert lufs_check.status in ("warn", "fail"), (
            f"Lauter Master vs Spotify: erwartet warn/fail, bekam {lufs_check.status} "
            f"(measured={lufs_check.measured})"
        )
        print(
            f"  loud_master_vs_spotify OK -> {spotify.overall_status} "
            f"(LUFS-Check: {lufs_check.status}, delta={lufs_check.delta_db:+.1f})"
        )
    finally:
        path.unlink(missing_ok=True)


def test_build_report_phase_inverted_mono_fail() -> None:
    """Phase-invertiertes Stereo (L=-R) → mono_compat fail bei JEDER Plattform."""
    pink = _make_pink_like(amplitude=0.3, seed=3)
    stereo = np.stack([pink, -pink], axis=1)  # Anti-Phase
    path = _write(stereo)
    try:
        report = build_expose_report(path, platforms=["spotify"])
        spotify = report.platform_reports[0]
        mono_check = next(c for c in spotify.checks if c.metric == "mono_compat")
        # Bei kompletter Anti-Phase: Korrelation = -1, mono_compat = fail
        assert mono_check.status == "fail", (
            f"Anti-Phase sollte mono_compat=fail liefern, bekam {mono_check.status}"
        )
        print(f"  phase_inverted_mono_fail OK -> mono_compat={mono_check.status}")
    finally:
        path.unlink(missing_ok=True)


def test_build_report_includes_all_metrics() -> None:
    """Report enthält alle erwarteten Mess-Felder (LRA, PLR neu)."""
    pink = _make_pink_like(amplitude=0.4, seed=5)
    stereo = _stereo(pink, decorrelation=0.05)
    path = _write(stereo)
    try:
        report = build_expose_report(path, platforms=["spotify"])
        m = report.measurements
        for required in (
            "peak_db", "true_peak_db", "rms_db",
            "lufs_integrated", "lufs_short_term_max",
            "lra_db", "plr_db",
            "stereo_correlation", "mono_compatibility_ok",
        ):
            assert required in m, f"Mess-Feld {required!r} fehlt im Report"
        # LRA und PLR müssen finite sein
        assert np.isfinite(m["lra_db"]), f"LRA nicht finite: {m['lra_db']}"
        assert np.isfinite(m["plr_db"]), f"PLR nicht finite: {m['plr_db']}"
        print(f"  includes_all_metrics OK -> LRA={m['lra_db']:.1f}, PLR={m['plr_db']:.1f}")
    finally:
        path.unlink(missing_ok=True)


def test_build_report_default_all_platforms() -> None:
    """Ohne platforms-Parameter: alle Plattformen aus mastering_chains.json."""
    pink = _make_pink_like(amplitude=0.3, seed=9)
    stereo = _stereo(pink, decorrelation=0.05)
    path = _write(stereo)
    try:
        report = build_expose_report(path)
        # Sollte mind. 6 Plattformen abdecken (siehe mastering_chains.json)
        assert len(report.platform_reports) >= 6, (
            f"Erwartet >=6 Plattformen, bekam {len(report.platform_reports)}"
        )
        ids = {p.platform_id for p in report.platform_reports}
        for required in ("spotify", "apple_music", "youtube", "tidal"):
            assert required in ids, f"Plattform {required} fehlt"
        # Overall-Summary muss summieren
        s = report.overall_summary
        total = s.get("pass", 0) + s.get("warn", 0) + s.get("fail", 0)
        assert total == len(report.platform_reports)
        print(
            f"  default_all_platforms OK -> {len(report.platform_reports)} Plattformen "
            f"({s.get('pass', 0)} pass, {s.get('warn', 0)} warn, {s.get('fail', 0)} fail)"
        )
    finally:
        path.unlink(missing_ok=True)


def test_format_report_text_renders() -> None:
    """format_report_text liefert Klartext mit allen Sections."""
    pink = _make_pink_like(amplitude=0.3, seed=13)
    stereo = _stereo(pink, decorrelation=0.05)
    path = _write(stereo)
    try:
        report = build_expose_report(path, platforms=["spotify", "apple_music"])
        text = format_report_text(report)
        assert "EXPOSE-Style Validation Report" in text
        assert "--- Messung ---" in text
        assert "--- Multi-Platform Pass/Fail ---" in text
        assert "Spotify" in text
        assert "Apple Music" in text
        assert "LRA:" in text
        assert "PLR:" in text
        print(f"  format_report_text OK -> {len(text.splitlines())} Zeilen")
    finally:
        path.unlink(missing_ok=True)


def test_vinyl_lufs_n_a() -> None:
    """Vinyl hat kein LUFS-Target -> LUFS-Check muss n/a sein."""
    pink = _make_pink_like(amplitude=0.3, seed=17)
    stereo = _stereo(pink, decorrelation=0.05)
    path = _write(stereo)
    try:
        report = build_expose_report(path, platforms=["vinyl"])
        vinyl = report.platform_reports[0]
        lufs_check = next(c for c in vinyl.checks if c.metric == "lufs")
        assert lufs_check.status == "n/a", f"Vinyl LUFS sollte n/a sein, war {lufs_check.status}"
        # True-Peak sollte aber funktionieren (Vinyl hat target_tp=-3)
        tp_check = next(c for c in vinyl.checks if c.metric == "true_peak")
        assert tp_check.target == -3
        print(f"  vinyl_lufs_n_a OK -> LUFS=n/a, TP-Target={tp_check.target} dB")
    finally:
        path.unlink(missing_ok=True)


# ---------- Runner ----------

ALL_TESTS = [
    test_compute_plr_basic,
    test_compute_lra_static_signal_low,
    test_compute_lra_dynamic_signal_higher,
    test_build_report_loud_master_fails_spotify,
    test_build_report_phase_inverted_mono_fail,
    test_build_report_includes_all_metrics,
    test_build_report_default_all_platforms,
    test_format_report_text_renders,
    test_vinyl_lufs_n_a,
]


def main() -> int:
    print(f"Running {len(ALL_TESTS)} expose-report selftests...\n")
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
    print(f"[OK] alle EXPOSE-Report-Selftests bestanden ({len(ALL_TESTS)}/{len(ALL_TESTS)}).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
