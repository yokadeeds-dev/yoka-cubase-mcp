"""
Mastering-Audit (Sprint E1) — vergleicht Audio-Analyse-Werte gegen
YMP-Genre/Platform-Targets aus mastering_chains.json.

Nimmt eine AudioAnalysis (siehe audio_analytics.py) und einen Genre/Plattform-
Kontext, liefert eine strukturierte Bewertung mit Kritisch/Suggestiv/
Beobachtung-Klassen (siehe Persona-Spec § 2.2 Empfehlungs-Klassen).

Pure-Func, kein State, keine I/O über audio_analytics + knowledge_loader hinaus.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from runtime.persona.audio_analytics import AudioAnalysis
from runtime.persona.knowledge_loader import get_mastering_chains


# Pre-Master-Headroom-Target aus YMP/Studium/21 § 2.1
_HEADROOM_TARGET_DB = -3.0
_HEADROOM_WARNING_DB = -1.0   # ab -1 dB ist es kritisch


@dataclass
class AuditFinding:
    """Eine einzelne Beobachtung/Empfehlung im Audit."""
    severity: str       # 'critical' | 'suggestive' | 'observation'
    field: str          # z. B. 'headroom', 'lufs', 'spectrum.low', 'stereo.mono'
    message: str        # Klartext-Aussage
    measured: Any = None
    target: Any = None
    suggestion: str | None = None


@dataclass
class MasteringAuditReport:
    """Gesamt-Audit-Bericht."""
    genre_id: str | None
    platform_id: str | None
    findings: list[AuditFinding] = field(default_factory=list)
    measurements_summary: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        # Aggregate counts
        counts = {"critical": 0, "suggestive": 0, "observation": 0}
        for f in self.findings:
            counts[f.severity] = counts.get(f.severity, 0) + 1
        return {
            "genre_id": self.genre_id,
            "platform_id": self.platform_id,
            "findings": [
                {
                    "severity": f.severity,
                    "field": f.field,
                    "message": f.message,
                    "measured": _serialize_value(f.measured),
                    "target": _serialize_value(f.target),
                    "suggestion": f.suggestion,
                }
                for f in self.findings
            ],
            "counts": counts,
            "measurements_summary": self.measurements_summary,
        }


def _serialize_value(v: Any) -> Any:
    """JSON-safe: -inf / +inf / NaN → Strings."""
    import math as _math
    if isinstance(v, float):
        if _math.isinf(v):
            return "-inf" if v < 0 else "+inf"
        if _math.isnan(v):
            return "nan"
    return v


# ---------- Audit-Regeln ----------

def _check_headroom(analysis: AudioAnalysis, findings: list[AuditFinding]) -> None:
    """Pre-Master-Headroom (-3 dB Standard, -1 dB hart-kritisch)."""
    peak = analysis.loudness.peak_db
    if peak >= _HEADROOM_WARNING_DB:
        findings.append(AuditFinding(
            severity="critical",
            field="headroom",
            message=f"Peak {peak:+.1f} dB FS — Clipping-Risiko bzw. nahe an Vollausschlag.",
            measured=peak,
            target=_HEADROOM_TARGET_DB,
            suggestion=f"Track-Fader um {peak - _HEADROOM_TARGET_DB:+.1f} dB ziehen oder gain-staging im Mix prüfen.",
        ))
    elif peak > _HEADROOM_TARGET_DB:
        findings.append(AuditFinding(
            severity="suggestive",
            field="headroom",
            message=f"Peak {peak:+.1f} dB FS — über Pre-Master-Target {_HEADROOM_TARGET_DB:+.1f} dB.",
            measured=peak,
            target=_HEADROOM_TARGET_DB,
            suggestion=f"Fader um {peak - _HEADROOM_TARGET_DB:+.1f} dB runter für Mastering-Headroom.",
        ))


def _check_loudness_vs_platform(
    analysis: AudioAnalysis,
    platform: dict[str, Any],
    findings: list[AuditFinding],
) -> None:
    """Liefert LUFS-I gegen Platform-Target (z. B. Spotify -14)."""
    target = platform.get("target_lufs_integrated")
    if target is None:
        return  # z. B. Vinyl: kein LUFS-Target

    measured = analysis.loudness.lufs_integrated
    import math as _math
    if _math.isinf(measured):
        return  # Stille Datei → kein sinnvoller Vergleich

    delta = measured - target
    if delta > 1.0:
        findings.append(AuditFinding(
            severity="suggestive",
            field="lufs",
            message=f"LUFS-I {measured:+.1f} ist {delta:+.1f} dB lauter als {platform.get('display_name', '?')}-Target {target:+.1f}.",
            measured=measured,
            target=target,
            suggestion=f"Plattform regelt runter — Limiter-Ziel um ~{delta:.1f} dB senken oder bewusst akzeptieren.",
        ))
    elif delta < -3.0:
        findings.append(AuditFinding(
            severity="observation",
            field="lufs",
            message=f"LUFS-I {measured:+.1f} ist {abs(delta):.1f} dB leiser als Plattform-Target {target:+.1f}.",
            measured=measured,
            target=target,
            suggestion="Wenn beabsichtigt (Genre-Charakter) OK, sonst Limiter-Ziel anheben.",
        ))


def _check_true_peak(analysis: AudioAnalysis, platform: dict[str, Any], findings: list[AuditFinding]) -> None:
    """True-Peak gegen Platform-Limit (typisch -1 dB)."""
    target_tp = platform.get("true_peak_db")
    if target_tp is None:
        return
    measured = analysis.loudness.true_peak_db
    if measured > target_tp:
        findings.append(AuditFinding(
            severity="critical",
            field="true_peak",
            message=f"True-Peak {measured:+.1f} dB überschreitet {platform.get('display_name', '?')}-Limit {target_tp:+.1f} dB.",
            measured=measured,
            target=target_tp,
            suggestion=f"Limiter-Ceiling um {measured - target_tp:.1f} dB strenger setzen ({target_tp - 0.2:+.1f} dB als Sicherheit).",
        ))


def _check_stereo(analysis: AudioAnalysis, findings: list[AuditFinding]) -> None:
    """Mono-Kompatibilität: Bass darf in Mono nicht verschwinden."""
    if not analysis.stereo.is_stereo:
        return
    if not analysis.stereo.mono_compatibility_ok:
        findings.append(AuditFinding(
            severity="critical",
            field="stereo.mono",
            message="Mono-Inkompatibilität im Bass-Bereich (<200 Hz) — Phase-Auslöschung beim Mono-Fold.",
            measured=analysis.stereo.correlation,
            target="≥0.7 (Bass-Mono-Kompatibel)",
            suggestion="Stereo-Imager auf Bass: Mono unter 150-200 Hz erzwingen. Ggf. Bass-Spur auf reine Mono-Aufnahme prüfen.",
        ))
    if analysis.stereo.correlation < 0.3:
        findings.append(AuditFinding(
            severity="suggestive",
            field="stereo.correlation",
            message=f"Stereo-Korrelation {analysis.stereo.correlation:.2f} sehr niedrig — Mix wirkt vermutlich diffus.",
            measured=analysis.stereo.correlation,
            target="0.5-0.95",
            suggestion="Phase-Korrelations-Meter pro Spur prüfen.",
        ))


def _check_spectrum_vs_genre(
    analysis: AudioAnalysis,
    genre: dict[str, Any],
    findings: list[AuditFinding],
) -> None:
    """
    Genre-spezifische Spektrum-Erwartungen.
    Heuristisch — bei Trip-Hop ist mid_bass_weight Pflicht etc.
    """
    spec = analysis.spectrum
    focus = set(genre.get("characteristic_focus", []))

    if "mid_bass_weight" in focus or "sub_bass" in focus:
        # Trip-Hop, HipHop, D&B: Low-Band sollte stark sein
        if spec.low_db < spec.mid_db - 12:
            findings.append(AuditFinding(
                severity="suggestive",
                field="spectrum.low",
                message=f"Low-Band ({spec.low_db:+.1f} dB) deutlich schwächer als Mid ({spec.mid_db:+.1f} dB) — für Genre {genre.get('display_name')} oft mehr Bass-Body erwartet.",
                measured=spec.low_db,
                target=f"~{spec.mid_db - 8:+.1f} dB",
                suggestion="Low-Shelf +1-2 dB @ 80-100 Hz oder Bass-Stem-Pegel anheben.",
            ))

    if "club_bass" in focus or "punch" in focus:
        # Sub muss substantiell sein
        if spec.sub_db < spec.low_db - 6:
            findings.append(AuditFinding(
                severity="suggestive",
                field="spectrum.sub",
                message=f"Sub-Band ({spec.sub_db:+.1f} dB) schwach gegenüber Low ({spec.low_db:+.1f} dB) — Club-Sound braucht Sub-Foundation.",
                measured=spec.sub_db,
                target=f"~{spec.low_db - 3:+.1f} dB",
                suggestion="Sub-Bass-Layer prüfen (Layer mit Sinus oder LFO-Bass) oder Multiband-Compressor bass-band sanft.",
            ))

    if "vocal_intimacy" in focus or "vocal_clarity" in focus:
        # Mid-Band sollte präsent sein für Vocal
        if spec.mid_db < spec.low_db - 3:
            findings.append(AuditFinding(
                severity="observation",
                field="spectrum.mid",
                message=f"Mid-Band ({spec.mid_db:+.1f} dB) eher zurückhaltend — falls Vocal-Track, evtl. zu leise im Mix.",
                measured=spec.mid_db,
            ))

    if "atmosphere" in focus or "stereo_space" in focus:
        # High/Air sollte da sein für Atmosphäre
        if spec.air_db < spec.high_db - 12:
            findings.append(AuditFinding(
                severity="observation",
                field="spectrum.air",
                message=f"Air-Band ({spec.air_db:+.1f} dB) sehr leise — atmosphärische Höhen fehlen.",
                measured=spec.air_db,
                suggestion="Creative-EQ High-Shelf +1-2 dB @ 12-15 kHz oder Reverb-/Air-Plugin.",
            ))


# ---------- Top-Level: Audit ----------

def audit_audio_analysis(
    analysis: AudioAnalysis,
    genre_id: str | None = None,
    platform_id: str | None = "spotify",
) -> MasteringAuditReport:
    """
    Hauptfunktion: liefert strukturierten Audit-Bericht.

    genre_id und platform_id müssen in mastering_chains.json existieren,
    sonst wird die jeweilige Sektion übersprungen (kein Crash).
    """
    report = MasteringAuditReport(
        genre_id=genre_id,
        platform_id=platform_id,
    )

    # Measurements-Summary für Anzeige
    report.measurements_summary = {
        "peak_db": analysis.loudness.peak_db,
        "rms_db": analysis.loudness.rms_db,
        "lufs_integrated": _serialize_value(analysis.loudness.lufs_integrated),
        "true_peak_db": analysis.loudness.true_peak_db,
        "dynamic_range_db": analysis.loudness.dynamic_range_db,
        "stereo_correlation": analysis.stereo.correlation,
        "mono_ok": analysis.stereo.mono_compatibility_ok,
        "channels": analysis.meta.channels,
        "duration_s": analysis.meta.duration_s,
    }

    # Headroom (immer prüfen, genre-/platform-unabhängig)
    _check_headroom(analysis, report.findings)
    _check_stereo(analysis, report.findings)

    # Genre/Platform-spezifisch nur wenn IDs gültig
    data = get_mastering_chains()
    platform = data["platforms"].get(platform_id) if platform_id else None
    genre = data["genres"].get(genre_id) if genre_id else None

    if platform:
        _check_loudness_vs_platform(analysis, platform, report.findings)
        _check_true_peak(analysis, platform, report.findings)

    if genre:
        _check_spectrum_vs_genre(analysis, genre, report.findings)

    return report
