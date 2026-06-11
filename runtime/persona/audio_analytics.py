"""
Audio-Analytics-Layer (Sprint E1) — deterministische Mess-Funktionen für
gebouncte Audio-Files (WAV/FLAC/AIFF).

Pure-Funcs ohne State, ohne Cubase-Eingriff. Nimmt File-Pfad, liefert
strukturierte Mess-Werte für Persona-Audit + Pre-Settings-Vorschläge.

Stack:
- soundfile  — Audio-IO (libsndfile-Wrapper)
- numpy      — Array-Operationen, Statistik
- scipy      — FFT für Spektrum-Bänder, Filter
- pyloudnorm — ITU BS.1770-konforme LUFS-Messung

Mess-Felder:
- peak_db, rms_db                        # klassisch
- lufs_integrated, lufs_short_term_max   # ITU BS.1770
- true_peak_db                           # Inter-Sample-Peak (4× Oversampling)
- dynamic_range_db                       # Crest-Factor-basiert
- spectral_balance                       # 5 Frequenz-Bänder in dB
- stereo_correlation                     # -1..+1 (mono..opposite)
- mono_compatibility                     # Bass-Phase-Check
- duration_s, sample_rate_hz, channels   # Datei-Meta

Aufruf:
    from runtime.persona.audio_analytics import analyze_audio_file
    result = analyze_audio_file('mix.wav')
"""

from __future__ import annotations

import math
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

import numpy as np
import pyloudnorm as pyln
import soundfile as sf
from scipy import signal as scipy_signal


# ---------- Spektrum-Bänder ----------
#
# Standard-5-Band-Aufteilung für Mastering-Audits. Grenzen so gewählt,
# dass typische Instrumenten-Bereiche getrennt sind:
# - sub:   < 60 Hz   (Sub-Bass, Kick-Fundamental)
# - low:   60–250    (Bass, Kick-Body, Low-Toms)
# - mid:   250–4k    (Vocals, Snare-Body, Gitarre)
# - high:  4k–10k    (Vocal-Präsenz, Snare-Crack, Hi-Hat)
# - air:   > 10k     (Schimmer, Cymbal-Sheen, Atemgeräusche)

SPECTRAL_BANDS_HZ: list[tuple[str, float, float]] = [
    ("sub", 20.0, 60.0),
    ("low", 60.0, 250.0),
    ("mid", 250.0, 4000.0),
    ("high", 4000.0, 10000.0),
    ("air", 10000.0, 22000.0),
]


# ---------- Datenklassen ----------

@dataclass
class AudioFileMeta:
    """Datei-Metadaten unabhängig vom Audio-Inhalt."""
    path: str
    duration_s: float
    sample_rate_hz: int
    channels: int
    samples_total: int


@dataclass
class LoudnessMeasurement:
    """Pegel + LUFS-Messungen."""
    peak_db: float                  # Sample-Peak (klassisch)
    rms_db: float                   # gemittelt über gesamte Datei
    lufs_integrated: float          # ITU BS.1770-3, gesamtes File
    lufs_short_term_max: float      # max LUFS-S über 3-s-Fenster
    true_peak_db: float             # Inter-Sample-Peak (4× Oversampling)
    dynamic_range_db: float         # Peak − LUFS-I als grobe DR-Approximation


@dataclass
class SpectralMeasurement:
    """Frequenz-Band-Energien in dB FS."""
    sub_db: float
    low_db: float
    mid_db: float
    high_db: float
    air_db: float


@dataclass
class StereoMeasurement:
    """Stereo-spezifische Messungen. Bei Mono-Files: korrelation=1, mono_ok=True."""
    correlation: float              # -1..+1 (Pearson L vs R)
    mono_compatibility_ok: bool     # Bass-Frequenzen unter 200 Hz mono-kompatibel
    side_to_mid_ratio_db: float     # Side-Energie vs Mid-Energie
    is_stereo: bool                 # True wenn 2-Kanal


@dataclass
class AudioAnalysis:
    """Gesamt-Bericht."""
    meta: AudioFileMeta
    loudness: LoudnessMeasurement
    spectrum: SpectralMeasurement
    stereo: StereoMeasurement

    def to_dict(self) -> dict[str, Any]:
        return {
            "meta": asdict(self.meta),
            "loudness": asdict(self.loudness),
            "spectrum": asdict(self.spectrum),
            "stereo": asdict(self.stereo),
        }


# ---------- Lade-Funktion ----------

def load_audio(path: str | Path) -> tuple[np.ndarray, int]:
    """
    Lädt eine Audio-Datei und liefert (samples, sample_rate).
    samples: shape (N,) für Mono, (N, 2) für Stereo, dtype float32.
    """
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(f"Audio-Datei nicht gefunden: {p}")
    samples, sample_rate = sf.read(str(p), dtype="float32", always_2d=False)
    return samples, sample_rate


# ---------- Pegel-Messungen ----------

def _safe_db(linear: float, floor_db: float = -200.0) -> float:
    """20·log10 mit Floor für 0-Werte. Stets float."""
    if linear <= 0 or not np.isfinite(linear):
        return floor_db
    return float(20.0 * math.log10(linear))


def measure_peak_db(samples: np.ndarray) -> float:
    """Maximaler absoluter Sample-Wert in dB FS."""
    if samples.size == 0:
        return -200.0
    peak = float(np.max(np.abs(samples)))
    return _safe_db(peak)


def measure_rms_db(samples: np.ndarray) -> float:
    """RMS über gesamte Datei in dB FS. Mono oder Stereo."""
    if samples.size == 0:
        return -200.0
    if samples.ndim == 2:
        # Stereo: RMS pro Kanal mitteln
        rms = float(np.sqrt(np.mean(samples ** 2)))
    else:
        rms = float(np.sqrt(np.mean(samples ** 2)))
    return _safe_db(rms)


def measure_true_peak_db(samples: np.ndarray, sample_rate: int) -> float:
    """
    Inter-Sample-Peak via 4× Oversampling (Standard für Streaming-Specs).
    Streaming-Plattformen messen True Peak — Sample-Peak ist nicht ausreichend.
    """
    if samples.size == 0:
        return -200.0
    # Auf Mono reduzieren für TP-Schätzung — wir wollen den globalen Worst-Case
    if samples.ndim == 2:
        mono = np.mean(samples, axis=1)
    else:
        mono = samples
    # 4× Resample via scipy.signal.resample_poly
    upsampled = scipy_signal.resample_poly(mono, 4, 1)
    true_peak = float(np.max(np.abs(upsampled)))
    return _safe_db(true_peak)


def measure_lufs(
    samples: np.ndarray,
    sample_rate: int,
) -> tuple[float, float]:
    """
    Liefert (lufs_integrated, lufs_short_term_max).
    Nutzt pyloudnorm-Implementierung (ITU BS.1770-3).
    """
    if samples.size == 0:
        return -200.0, -200.0

    meter = pyln.Meter(sample_rate)
    # pyloudnorm braucht Stereo-Format mit shape (N, 2). Mono → broadcast zu Stereo.
    if samples.ndim == 1:
        stereo = np.stack([samples, samples], axis=1)
    else:
        stereo = samples

    try:
        integrated = float(meter.integrated_loudness(stereo))
    except Exception:
        # Bei sehr kurzen Files (<400 ms) wirft pyloudnorm — Fallback
        integrated = -200.0

    # Short-Term: 3-s-Fenster, 100-ms-Hops, max nehmen
    window_samples = int(3.0 * sample_rate)
    hop_samples = int(0.1 * sample_rate)
    if stereo.shape[0] < window_samples:
        # Datei kürzer als 3 s — kein ST-Fenster machbar
        return integrated, integrated

    st_values: list[float] = []
    for start in range(0, stereo.shape[0] - window_samples, hop_samples):
        window = stereo[start:start + window_samples]
        try:
            st_values.append(float(meter.integrated_loudness(window)))
        except Exception:
            continue
    short_term_max = max(st_values) if st_values else integrated
    return integrated, short_term_max


# ---------- Spektrum-Messung ----------

def measure_spectral_bands(samples: np.ndarray, sample_rate: int) -> SpectralMeasurement:
    """
    FFT über die gesamte Datei (oder gemittelt über Fenster bei langen Files),
    Energie in den 5 Standard-Bändern in dB FS.

    Implementierung: Welch-Methode für stabile Power-Spectral-Density.
    """
    if samples.size == 0:
        floor = -200.0
        return SpectralMeasurement(floor, floor, floor, floor, floor)

    # Mono-Konvertierung für Spektrum-Analyse
    if samples.ndim == 2:
        mono = np.mean(samples, axis=1)
    else:
        mono = samples

    # Welch-PSD
    nperseg = min(8192, len(mono))
    freqs, psd = scipy_signal.welch(
        mono,
        fs=sample_rate,
        nperseg=nperseg,
        scaling="density",
    )

    band_dbs: dict[str, float] = {}
    for name, lo_hz, hi_hz in SPECTRAL_BANDS_HZ:
        mask = (freqs >= lo_hz) & (freqs < hi_hz)
        if not np.any(mask):
            band_dbs[name] = -200.0
            continue
        # Energie im Band: Integral der PSD über Frequenz
        band_energy = float(np.trapezoid(psd[mask], freqs[mask]))
        # In dB; Floor bei sehr leisem Band
        band_dbs[name] = _safe_db(math.sqrt(max(band_energy, 1e-30)))

    return SpectralMeasurement(
        sub_db=band_dbs["sub"],
        low_db=band_dbs["low"],
        mid_db=band_dbs["mid"],
        high_db=band_dbs["high"],
        air_db=band_dbs["air"],
    )


# ---------- Stereo-Messungen ----------

def measure_stereo(samples: np.ndarray, sample_rate: int) -> StereoMeasurement:
    """
    Stereo-Korrelation (Pearson L vs R), Mono-Kompatibilität (Phase-Check
    in Bass < 200 Hz), Side/Mid-Ratio.

    Mono-File: correlation=1.0, mono_ok=True, ratio=-200 dB, is_stereo=False.
    """
    if samples.ndim == 1 or (samples.ndim == 2 and samples.shape[1] == 1):
        return StereoMeasurement(
            correlation=1.0,
            mono_compatibility_ok=True,
            side_to_mid_ratio_db=-200.0,
            is_stereo=False,
        )

    left = samples[:, 0]
    right = samples[:, 1]

    # Pearson-Korrelation
    if np.std(left) > 1e-10 and np.std(right) > 1e-10:
        correlation = float(np.corrcoef(left, right)[0, 1])
    else:
        # Mindestens ein Kanal komplett still
        correlation = 1.0

    # Mid/Side
    mid = (left + right) * 0.5
    side = (left - right) * 0.5
    mid_rms = float(np.sqrt(np.mean(mid ** 2)))
    side_rms = float(np.sqrt(np.mean(side ** 2)))
    if mid_rms > 1e-10:
        side_to_mid_db = _safe_db(side_rms / mid_rms)
    else:
        side_to_mid_db = 0.0

    # Mono-Kompatibilität: Bass < 200 Hz nach Mono-Fold prüfen
    # Wenn die Bass-Energie in (L+R)/2 deutlich kleiner ist als die durchschnittliche
    # Bass-Energie in L/R einzeln, dann Phasen-Probleme.
    nyq = sample_rate * 0.5
    if nyq > 200:
        sos = scipy_signal.butter(4, 200.0 / nyq, btype="low", output="sos")
        left_bass = scipy_signal.sosfilt(sos, left)
        right_bass = scipy_signal.sosfilt(sos, right)
        mid_bass = (left_bass + right_bass) * 0.5
        rms_left = float(np.sqrt(np.mean(left_bass ** 2)))
        rms_right = float(np.sqrt(np.mean(right_bass ** 2)))
        rms_mid = float(np.sqrt(np.mean(mid_bass ** 2)))
        avg_lr = (rms_left + rms_right) * 0.5
        if avg_lr > 1e-10:
            # Wenn Mono-Fold weniger als 70% des einzelnen Pegels hält, Phase-Problem
            mono_ok = bool(rms_mid >= avg_lr * 0.7)
        else:
            mono_ok = True
    else:
        mono_ok = True

    return StereoMeasurement(
        correlation=correlation,
        mono_compatibility_ok=mono_ok,
        side_to_mid_ratio_db=side_to_mid_db,
        is_stereo=True,
    )


# ---------- Top-Level: Gesamt-Analyse ----------

@dataclass
class AudioComparison:
    """A/B-Vergleich zweier AudioAnalysis-Objekte."""
    file_a: str
    file_b: str
    deltas: dict[str, Any]   # field-by-field delta
    similarity_score: float  # 0.0 (verschieden) .. 1.0 (gleich)
    notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "file_a": self.file_a,
            "file_b": self.file_b,
            "deltas": self.deltas,
            "similarity_score": self.similarity_score,
            "notes": self.notes,
        }


def compare_analyses(
    a: "AudioAnalysis",
    b: "AudioAnalysis",
) -> AudioComparison:
    """
    Vergleicht zwei AudioAnalysis-Objekte numerisch.
    Liefert Delta-Werte pro Feld + zusammengesetzten Similarity-Score
    (basierend auf normalisierten Distanzen in Loudness, Spektrum, Stereo).
    """
    import math as _math

    def _safe_delta(va: float | None, vb: float | None) -> float | None:
        if va is None or vb is None:
            return None
        if isinstance(va, float) and (_math.isinf(va) or _math.isnan(va)):
            return None
        if isinstance(vb, float) and (_math.isinf(vb) or _math.isnan(vb)):
            return None
        return float(va) - float(vb)

    deltas = {
        "loudness": {
            "peak_db": _safe_delta(a.loudness.peak_db, b.loudness.peak_db),
            "rms_db": _safe_delta(a.loudness.rms_db, b.loudness.rms_db),
            "lufs_integrated": _safe_delta(a.loudness.lufs_integrated, b.loudness.lufs_integrated),
            "lufs_short_term_max": _safe_delta(a.loudness.lufs_short_term_max, b.loudness.lufs_short_term_max),
            "true_peak_db": _safe_delta(a.loudness.true_peak_db, b.loudness.true_peak_db),
            "dynamic_range_db": _safe_delta(a.loudness.dynamic_range_db, b.loudness.dynamic_range_db),
        },
        "spectrum": {
            "sub_db": _safe_delta(a.spectrum.sub_db, b.spectrum.sub_db),
            "low_db": _safe_delta(a.spectrum.low_db, b.spectrum.low_db),
            "mid_db": _safe_delta(a.spectrum.mid_db, b.spectrum.mid_db),
            "high_db": _safe_delta(a.spectrum.high_db, b.spectrum.high_db),
            "air_db": _safe_delta(a.spectrum.air_db, b.spectrum.air_db),
        },
        "stereo": {
            "correlation": _safe_delta(a.stereo.correlation, b.stereo.correlation),
            "side_to_mid_ratio_db": _safe_delta(a.stereo.side_to_mid_ratio_db, b.stereo.side_to_mid_ratio_db),
        },
        "duration_s_diff": _safe_delta(a.meta.duration_s, b.meta.duration_s),
    }

    # Similarity-Score: 1 - normierte Summe der Distanzen.
    # Gewichtung: Loudness 30%, Spektrum 50%, Stereo 20%.
    def _norm(d: float | None, scale: float) -> float:
        if d is None:
            return 0.0
        return min(1.0, abs(d) / scale)

    loudness_dist = (
        _norm(deltas["loudness"]["lufs_integrated"], 12.0) * 0.5
        + _norm(deltas["loudness"]["peak_db"], 12.0) * 0.25
        + _norm(deltas["loudness"]["dynamic_range_db"], 12.0) * 0.25
    )
    spectrum_dist = (
        _norm(deltas["spectrum"]["sub_db"], 30.0) * 0.2
        + _norm(deltas["spectrum"]["low_db"], 30.0) * 0.2
        + _norm(deltas["spectrum"]["mid_db"], 30.0) * 0.2
        + _norm(deltas["spectrum"]["high_db"], 30.0) * 0.2
        + _norm(deltas["spectrum"]["air_db"], 30.0) * 0.2
    )
    stereo_dist = (
        _norm(deltas["stereo"]["correlation"], 1.0) * 0.5
        + _norm(deltas["stereo"]["side_to_mid_ratio_db"], 30.0) * 0.5
    )

    total_dist = loudness_dist * 0.3 + spectrum_dist * 0.5 + stereo_dist * 0.2
    similarity = max(0.0, 1.0 - total_dist)

    # Klartext-Notizen
    notes = []
    if deltas["loudness"]["lufs_integrated"] is not None:
        d = deltas["loudness"]["lufs_integrated"]
        if abs(d) > 3:
            who_louder = "A" if d > 0 else "B"
            notes.append(f"LUFS-I-Differenz {abs(d):.1f} dB — {who_louder} ist deutlich lauter")
    if deltas["spectrum"]["low_db"] is not None and abs(deltas["spectrum"]["low_db"]) > 6:
        who = "A" if deltas["spectrum"]["low_db"] > 0 else "B"
        notes.append(f"Low-Band-Unterschied {abs(deltas['spectrum']['low_db']):.1f} dB — {who} hat mehr Bass-Body")
    if deltas["spectrum"]["air_db"] is not None and abs(deltas["spectrum"]["air_db"]) > 6:
        who = "A" if deltas["spectrum"]["air_db"] > 0 else "B"
        notes.append(f"Air-Band-Unterschied {abs(deltas['spectrum']['air_db']):.1f} dB — {who} hat mehr Höhen")
    if deltas["stereo"]["correlation"] is not None and abs(deltas["stereo"]["correlation"]) > 0.3:
        notes.append(f"Stereo-Bild deutlich anders (Korrelations-Differenz {deltas['stereo']['correlation']:+.2f})")

    return AudioComparison(
        file_a=a.meta.path,
        file_b=b.meta.path,
        deltas=deltas,
        similarity_score=round(similarity, 3),
        notes=notes,
    )


def compare_audio_files(path_a: str | Path, path_b: str | Path) -> AudioComparison:
    """High-Level: lädt + analysiert beide Files, vergleicht."""
    a = analyze_audio_file(path_a)
    b = analyze_audio_file(path_b)
    return compare_analyses(a, b)


def analyze_audio_file(path: str | Path) -> AudioAnalysis:
    """
    Vollständige Audio-Analyse einer Datei.
    Wirft FileNotFoundError wenn Datei fehlt.
    """
    samples, sr = load_audio(path)
    p = Path(path)

    duration_s = float(samples.shape[0] / sr) if samples.size else 0.0
    channels = int(samples.shape[1]) if samples.ndim == 2 else 1
    samples_total = int(samples.shape[0]) if samples.size else 0

    meta = AudioFileMeta(
        path=str(p),
        duration_s=duration_s,
        sample_rate_hz=int(sr),
        channels=channels,
        samples_total=samples_total,
    )

    peak_db = measure_peak_db(samples)
    rms_db = measure_rms_db(samples)
    true_peak_db = measure_true_peak_db(samples, sr)
    lufs_i, lufs_st_max = measure_lufs(samples, sr)
    dr_approx = peak_db - lufs_i if lufs_i > -150 else 0.0

    loudness = LoudnessMeasurement(
        peak_db=peak_db,
        rms_db=rms_db,
        lufs_integrated=lufs_i,
        lufs_short_term_max=lufs_st_max,
        true_peak_db=true_peak_db,
        dynamic_range_db=dr_approx,
    )

    spectrum = measure_spectral_bands(samples, sr)
    stereo = measure_stereo(samples, sr)

    return AudioAnalysis(
        meta=meta,
        loudness=loudness,
        spectrum=spectrum,
        stereo=stereo,
    )
