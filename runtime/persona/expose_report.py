"""
EXPOSE-Style Validation Report (Sprint E1.5).

EXPOSE.exe (Mastering The Mix) ist GUI-only — kein dokumentiertes CLI.
Statt einen Wrapper zu bauen, liefert dieses Modul einen vergleichbaren
Validierungs-Bericht aus unseren bereits existierenden Mess-Funktionen
(audio_analytics) plus zusätzlicher Metriken die EXPOSE prominent zeigt:

  - PLR (Peak-to-Loudness-Ratio) — Peak − LUFS-I
  - LRA (Loudness Range, EBU R128) — 95th − 10th Percentile der ST-LUFS
  - Multi-Platform Pass/Fail-Matrix (Spotify, Apple, Tidal, YouTube, etc.)

Output ist eine Pass/Fail-Matrix wie EXPOSE sie zeigt — Yoka kann seinen
Master gegen alle Streaming-Targets gleichzeitig prüfen.

Pure Func, kein State, baut auf audio_analytics + knowledge_loader auf.

Aufruf:
    from runtime.persona.expose_report import build_expose_report
    report = build_expose_report("master.wav")
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

import numpy as np

from runtime.persona.audio_analytics import (
    AudioAnalysis,
    analyze_audio_file,
    load_audio,
)
from runtime.persona.knowledge_loader import get_mastering_chains


# ---------- Erweiterte Metriken (EXPOSE-spezifisch) ----------


def compute_plr(peak_db: float, lufs_integrated: float) -> float:
    """
    Peak-to-Loudness-Ratio = Peak − LUFS-I (in dB).
    Maß für Dynamik. Streaming-typisch:
      - Pop/EDM gemastered: PLR 5-9 dB (sehr komprimiert)
      - Trip-Hop / Indie: PLR 9-13 dB (mittel)
      - Klassik / Jazz: PLR 14+ dB (offen, dynamisch)
    """
    if not np.isfinite(peak_db) or not np.isfinite(lufs_integrated):
        return float("nan")
    return peak_db - lufs_integrated


def compute_lra(samples: np.ndarray, sample_rate: int) -> float:
    """
    Loudness Range nach EBU R128 — vereinfachte Implementierung:
    95th Percentile minus 10th Percentile der Short-Term-LUFS-Werte.

    Window 3s, hop 100ms. Bei Files <3s: nicht anwendbar -> 0.0.
    """
    import pyloudnorm as pyln

    if samples.size == 0:
        return 0.0

    # Stereo-Form für pyloudnorm
    if samples.ndim == 1:
        stereo = np.stack([samples, samples], axis=1)
    else:
        stereo = samples

    window_samples = int(3.0 * sample_rate)
    hop_samples = int(0.1 * sample_rate)
    if stereo.shape[0] < window_samples:
        return 0.0

    meter = pyln.Meter(sample_rate)
    st_values: list[float] = []
    for start in range(0, stereo.shape[0] - window_samples, hop_samples):
        window = stereo[start:start + window_samples]
        try:
            val = float(meter.integrated_loudness(window))
            if np.isfinite(val):
                st_values.append(val)
        except Exception:
            continue

    if len(st_values) < 2:
        return 0.0

    arr = np.array(st_values)
    p95 = float(np.percentile(arr, 95))
    p10 = float(np.percentile(arr, 10))
    return p95 - p10


# ---------- Pass/Fail-Logik ----------

@dataclass
class PlatformCheck:
    """Eine einzelne Pass/Fail-Zeile pro Plattform."""
    platform_id: str
    display_name: str
    metric: str               # 'lufs' | 'true_peak' | 'lra' | 'mono_compat'
    measured: float | None
    target: float | None
    status: str               # 'pass' | 'warn' | 'fail' | 'n/a'
    delta_db: float | None
    note: str


@dataclass
class PlatformReport:
    """Pro Plattform: alle Checks aggregiert."""
    platform_id: str
    display_name: str
    target_lufs: float | None
    target_true_peak: float | None
    checks: list[PlatformCheck] = field(default_factory=list)
    overall_status: str = "pass"  # 'pass' | 'warn' | 'fail'

    def update_overall(self) -> None:
        # fail dominiert warn dominiert pass
        if any(c.status == "fail" for c in self.checks):
            self.overall_status = "fail"
        elif any(c.status == "warn" for c in self.checks):
            self.overall_status = "warn"
        else:
            self.overall_status = "pass"


@dataclass
class ExposeReport:
    """Gesamt-Bericht: Datei-Meta + Mess-Werte + Multi-Platform-Matrix."""
    file_path: str
    measurements: dict[str, Any]
    platform_reports: list[PlatformReport] = field(default_factory=list)
    overall_summary: dict[str, int] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "file_path": self.file_path,
            "measurements": self.measurements,
            "platforms": [
                {
                    "platform_id": p.platform_id,
                    "display_name": p.display_name,
                    "target_lufs": p.target_lufs,
                    "target_true_peak": p.target_true_peak,
                    "overall_status": p.overall_status,
                    "checks": [asdict(c) for c in p.checks],
                }
                for p in self.platform_reports
            ],
            "overall_summary": self.overall_summary,
        }


# ---------- Check-Funktionen ----------

# Toleranzen — zwischen pass und warn
_LUFS_WARN_OVER_DB = 1.0     # bis 1 dB über Target = warn
_LUFS_WARN_UNDER_DB = 3.0    # bis 3 dB unter Target = warn (sonst pass mit 'leiser' Note)
_TP_WARN_HEADROOM = 0.2      # bis 0.2 dB unter TP-Limit = warn (knapp)


def _check_lufs(
    measured_lufs: float,
    target_lufs: float | None,
    platform_id: str,
    display_name: str,
) -> PlatformCheck:
    if target_lufs is None or not np.isfinite(measured_lufs):
        return PlatformCheck(
            platform_id=platform_id,
            display_name=display_name,
            metric="lufs",
            measured=None if not np.isfinite(measured_lufs) else measured_lufs,
            target=target_lufs,
            status="n/a",
            delta_db=None,
            note="LUFS-Target nicht definiert für diese Plattform (z. B. Vinyl).",
        )

    delta = measured_lufs - target_lufs
    if delta > _LUFS_WARN_OVER_DB:
        status = "fail" if delta > 3.0 else "warn"
        note = (
            f"LUFS-I ist {delta:+.1f} dB über Target {target_lufs:+.0f} — "
            f"Plattform regelt runter, Dynamik-Verlust droht."
        )
    elif delta < -_LUFS_WARN_UNDER_DB:
        status = "warn"
        note = (
            f"LUFS-I ist {abs(delta):.1f} dB leiser als Target — "
            f"falls Genre-Charakter ok, sonst Limiter-Ziel anheben."
        )
    else:
        status = "pass"
        note = f"LUFS-I {measured_lufs:+.1f} dB im Toleranz-Fenster zu {target_lufs:+.0f}."

    return PlatformCheck(
        platform_id=platform_id,
        display_name=display_name,
        metric="lufs",
        measured=float(measured_lufs),
        target=float(target_lufs),
        status=status,
        delta_db=float(delta),
        note=note,
    )


def _check_true_peak(
    measured_tp: float,
    target_tp: float | None,
    platform_id: str,
    display_name: str,
) -> PlatformCheck:
    if target_tp is None or not np.isfinite(measured_tp):
        return PlatformCheck(
            platform_id=platform_id,
            display_name=display_name,
            metric="true_peak",
            measured=None if not np.isfinite(measured_tp) else measured_tp,
            target=target_tp,
            status="n/a",
            delta_db=None,
            note="True-Peak-Target nicht definiert.",
        )

    delta = measured_tp - target_tp
    if delta > 0:
        status = "fail"
        note = (
            f"True-Peak überschreitet Limit um {delta:+.2f} dB — "
            f"Limiter-Ceiling auf {target_tp - 0.2:+.1f} dB setzen."
        )
    elif delta > -_TP_WARN_HEADROOM:
        status = "warn"
        note = (
            f"True-Peak {measured_tp:+.2f} dB nur {abs(delta):.2f} dB unter Limit — "
            f"knapp, kein Sicherheits-Headroom."
        )
    else:
        status = "pass"
        note = f"True-Peak {measured_tp:+.2f} dB sicher unter Limit {target_tp:+.1f}."

    return PlatformCheck(
        platform_id=platform_id,
        display_name=display_name,
        metric="true_peak",
        measured=float(measured_tp),
        target=float(target_tp),
        status=status,
        delta_db=float(delta),
        note=note,
    )


def _check_mono_compat(
    is_stereo: bool,
    mono_ok: bool,
    correlation: float,
    platform_id: str,
    display_name: str,
) -> PlatformCheck:
    if not is_stereo:
        return PlatformCheck(
            platform_id=platform_id,
            display_name=display_name,
            metric="mono_compat",
            measured=None,
            target=None,
            status="n/a",
            delta_db=None,
            note="Mono-Datei — Mono-Kompatibilität trivial.",
        )

    if not mono_ok:
        status = "fail"
        note = (
            "Mono-Inkompatibilität im Bass <200 Hz — Phase-Auslöschung beim Mono-Fold. "
            "Bass-Spuren auf Mono-Imager prüfen."
        )
    elif correlation < 0.3:
        status = "warn"
        note = (
            f"Stereo-Korrelation {correlation:.2f} sehr niedrig — Mix wirkt diffus. "
            f"Mono-Fold dürfte funktionieren, aber Phase pro Spur prüfen."
        )
    else:
        status = "pass"
        note = f"Mono-Fold ok, Korrelation {correlation:.2f}."

    return PlatformCheck(
        platform_id=platform_id,
        display_name=display_name,
        metric="mono_compat",
        measured=float(correlation),
        target=0.7,
        status=status,
        delta_db=None,
        note=note,
    )


# ---------- Top-Level: Report-Builder ----------

def build_expose_report(
    audio_path: str | Path,
    platforms: list[str] | None = None,
) -> ExposeReport:
    """
    Hauptfunktion: liefert vollständigen EXPOSE-Style-Validation-Bericht.

    Args:
      audio_path: Pfad zur Audio-Datei (WAV/FLAC/AIFF)
      platforms: optional Whitelist von platform_ids aus mastering_chains.json.
                 Wenn None: alle Plattformen werden geprüft.

    Returns:
      ExposeReport mit measurements + platform_reports + overall_summary
    """
    # 1) Vollanalyse über existierende audio_analytics
    analysis: AudioAnalysis = analyze_audio_file(audio_path)

    # 2) LRA berechnen — eigene Funktion (audio_analytics hat das nicht)
    samples, sr = load_audio(audio_path)
    lra = compute_lra(samples, sr)

    # 3) PLR
    plr = compute_plr(analysis.loudness.peak_db, analysis.loudness.lufs_integrated)

    # 4) Measurements zusammenstellen
    measurements: dict[str, Any] = {
        "peak_db": analysis.loudness.peak_db,
        "rms_db": analysis.loudness.rms_db,
        "lufs_integrated": analysis.loudness.lufs_integrated,
        "lufs_short_term_max": analysis.loudness.lufs_short_term_max,
        "true_peak_db": analysis.loudness.true_peak_db,
        "dynamic_range_db": analysis.loudness.dynamic_range_db,
        "lra_db": lra,
        "plr_db": plr,
        "stereo_correlation": analysis.stereo.correlation,
        "is_stereo": analysis.stereo.is_stereo,
        "mono_compatibility_ok": analysis.stereo.mono_compatibility_ok,
        "duration_s": analysis.meta.duration_s,
        "sample_rate_hz": analysis.meta.sample_rate_hz,
        "channels": analysis.meta.channels,
    }

    # 5) Pro Plattform Pass/Fail-Matrix
    chains_data = get_mastering_chains()
    all_platforms = chains_data.get("platforms", {})
    if platforms:
        plat_items = [
            (pid, all_platforms[pid])
            for pid in platforms
            if pid in all_platforms
        ]
    else:
        plat_items = list(all_platforms.items())

    platform_reports: list[PlatformReport] = []
    for pid, plat in plat_items:
        target_lufs = plat.get("target_lufs_integrated")
        target_tp = plat.get("true_peak_db")
        prep = PlatformReport(
            platform_id=pid,
            display_name=plat.get("display_name", pid),
            target_lufs=target_lufs,
            target_true_peak=target_tp,
        )
        prep.checks.append(_check_lufs(
            analysis.loudness.lufs_integrated, target_lufs, pid, prep.display_name,
        ))
        prep.checks.append(_check_true_peak(
            analysis.loudness.true_peak_db, target_tp, pid, prep.display_name,
        ))
        prep.checks.append(_check_mono_compat(
            analysis.stereo.is_stereo,
            analysis.stereo.mono_compatibility_ok,
            analysis.stereo.correlation,
            pid,
            prep.display_name,
        ))
        prep.update_overall()
        platform_reports.append(prep)

    # 6) Overall-Summary
    overall = {"pass": 0, "warn": 0, "fail": 0}
    for p in platform_reports:
        overall[p.overall_status] = overall.get(p.overall_status, 0) + 1

    return ExposeReport(
        file_path=str(audio_path),
        measurements=measurements,
        platform_reports=platform_reports,
        overall_summary=overall,
    )


def format_report_text(report: ExposeReport) -> str:
    """
    Liefert einen menschen-lesbaren Klartext-Report — fürs Console-Output
    oder zum direkten Einbau in Persona-Antworten.
    """
    m = report.measurements
    lines = [
        f"=== EXPOSE-Style Validation Report ===",
        f"Datei: {report.file_path}",
        f"Dauer: {m['duration_s']:.1f}s, {m['sample_rate_hz']} Hz, {m['channels']} ch",
        "",
        f"--- Messung ---",
        f"  Peak:           {m['peak_db']:+.2f} dB FS",
        f"  True Peak:      {m['true_peak_db']:+.2f} dB FS",
        f"  RMS:            {m['rms_db']:+.2f} dB FS",
        f"  LUFS-I:         {m['lufs_integrated']:+.2f} LUFS",
        f"  LUFS-S Max:     {m['lufs_short_term_max']:+.2f} LUFS",
        f"  LRA:            {m['lra_db']:.1f} LU",
        f"  PLR:            {m['plr_db']:.1f} dB",
        f"  Stereo-Korr.:   {m['stereo_correlation']:+.2f}",
        f"  Mono-Compat:    {'OK' if m['mono_compatibility_ok'] else 'FAIL'}",
        "",
        f"--- Multi-Platform Pass/Fail ---",
    ]
    for p in report.platform_reports:
        marker = {"pass": "[OK]", "warn": "[!]", "fail": "[X]"}.get(p.overall_status, "[?]")
        lines.append(f"  {marker} {p.display_name:20s}  ({p.overall_status.upper()})")
        for c in p.checks:
            if c.status == "n/a":
                continue
            sub_marker = {"pass": "+", "warn": "!", "fail": "x"}.get(c.status, "?")
            lines.append(f"      {sub_marker} {c.metric:14s} {c.note}")
    lines.append("")
    s = report.overall_summary
    lines.append(
        f"--- Gesamt: {s.get('pass', 0)} pass, {s.get('warn', 0)} warn, {s.get('fail', 0)} fail ---"
    )
    return "\n".join(lines)
