"""
Pre-Settings-Vorschlag (Sprint E1) — leitet aus Audio-Mess-Daten +
Track-Rolle + Genre konkrete Plugin-Settings als Startpunkt ab.

Yokas Erwartung (2026-05-05): Persona soll keine fertigen Master
liefern, sondern **Voreinstellungen** pro Spur als non-zero Baseline.
Yoka startet damit, hört, justiert manuell.

Track-Rollen:
- drums              (Drum-Group inkl. Kick/Snare/Perc)
- bass               (E-Bass oder Synth-Bass)
- harmonic           (Synths, Pads, Strings, "Other")
- acoustic_guitar    (Live-aufgenommene akustische Gitarre)
- vocal_lead         (Lead-Vocal, oft live)
- vocal_backing      (Backing-/Harmony-Vocals)
- master             (Stereo-Master-Bus, nach Stem-Summing)

Output: strukturierter Setting-Vorschlag mit:
- high_pass:        cutoff_hz, slope_db_oct
- corrective_eq:    list of EQ-moves (subtraktiv)
- compressor:       ratio, threshold_db, attack/release, max_gr_db
- de_esser:         frequency_hz, reduction_db (nur Vocal)
- saturation:       drive_pct, tape_speed_ips
- limiter:          ceiling_db (nur master)
- notes:            Klartext-Begründung der Wahl
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

from runtime.persona.audio_analytics import AudioAnalysis
from runtime.persona.knowledge_loader import get_mastering_chains


@dataclass
class TrackPreSettings:
    """Pro-Spur-Voreinstellungs-Vorschlag."""
    track_role: str
    genre_id: str | None
    high_pass: dict[str, Any] | None = None
    corrective_eq: list[dict[str, Any]] = field(default_factory=list)
    compressor: dict[str, Any] | None = None
    de_esser: dict[str, Any] | None = None
    saturation: dict[str, Any] | None = None
    limiter: dict[str, Any] | None = None
    notes: list[str] = field(default_factory=list)
    measurements_used: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


# ---------- Track-Rollen-Defaults ----------

# High-Pass-Cutoff pro Rolle (Hz). Standard-Mixing-Wisdom.
_HIGHPASS_CUTOFF_HZ: dict[str, float] = {
    "drums": 35.0,
    "bass": 35.0,
    "harmonic": 80.0,
    "acoustic_guitar": 80.0,
    "vocal_lead": 100.0,
    "vocal_backing": 100.0,
    "master": 30.0,
}


# Compressor-Defaults pro Rolle: (ratio, attack_ms, release_ms, target_gr_db)
_COMPRESSOR_DEFAULTS: dict[str, tuple[float, float, float, float]] = {
    "drums": (3.0, 5.0, 80.0, 3.0),          # Punchy aber kontrolliert
    "bass": (3.5, 10.0, 100.0, 3.0),         # Tight bass
    "harmonic": (2.0, 30.0, 200.0, 2.0),     # Subtle glue
    "acoustic_guitar": (2.0, 15.0, 150.0, 2.0),  # Natürlich
    "vocal_lead": (3.0, 5.0, 80.0, 4.0),     # Vocal-typisch
    "vocal_backing": (2.5, 10.0, 100.0, 3.0),
    "master": (1.5, 40.0, 300.0, 1.5),       # Glue, kein Pumpen (Default)
}


# ---------- Helfer ----------

def _round_to(value: float, ndigits: int = 1) -> float:
    return round(value, ndigits)


def _suggest_threshold_for_target_gr(
    rms_db: float,
    target_gr_db: float,
    ratio: float,
) -> float:
    """
    Heuristik: Threshold so setzen, dass über RMS-Niveau eine Ziel-GR
    erreicht wird. Ratio 3:1 + Target 3 dB GR → Threshold ≈ RMS - 3*ratio/(ratio-1).
    """
    if ratio <= 1.0:
        return rms_db
    # Über-Schwellen-Anteil = target_gr * ratio / (ratio - 1)
    over_threshold_db = target_gr_db * ratio / (ratio - 1.0)
    return _round_to(rms_db + over_threshold_db, 1)


# ---------- Genre-Modifikatoren ----------

def _apply_genre_compressor_modifiers(
    base: dict[str, Any],
    genre: dict[str, Any] | None,
) -> dict[str, Any]:
    """Trip-Hop will subtle (max 1.5 dB GR), Klassik Compressor off, etc."""
    if genre is None:
        return base
    genre_id = genre.get("display_name", "").lower()
    overrides = genre.get("chain_overrides", {})
    comp_override = overrides.get("compressor", {})

    # Genre hat compressor disabled
    if comp_override.get("enabled") is False:
        return {**base, "enabled": False, "reason": comp_override.get("reason")}

    # Genre liefert ratio_range / gain_reduction_db_max
    params = comp_override.get("params", {})
    if "gain_reduction_db_max" in params:
        # Ratio dazu ggf. anpassen
        base["target_gain_reduction_db"] = min(
            base.get("target_gain_reduction_db", 3.0),
            params["gain_reduction_db_max"],
        )
    if "ratio_range" in params:
        # Mittelwert nehmen
        ratio_min, ratio_max = params["ratio_range"]
        base["ratio"] = round((ratio_min + ratio_max) / 2.0, 1)
    if comp_override.get("reason"):
        base["genre_note"] = comp_override["reason"]
    return base


def _apply_genre_saturation(
    track_role: str,
    genre: dict[str, Any] | None,
) -> dict[str, Any] | None:
    """Trip-Hop will Tape-Saturation 7.5 ips, Klassik none, etc."""
    if genre is None:
        return None
    overrides = genre.get("chain_overrides", {})
    sat_override = overrides.get("saturation", {})
    if sat_override.get("enabled") is False:
        return None

    # Default-Saturation aus Generic-Chain
    data = get_mastering_chains()
    generic_sat = next(
        (s for s in data["generic_chain"] if s["step_id"] == "saturation"),
        None,
    )
    if not generic_sat:
        return None
    params = dict(generic_sat["params"])
    params.update(sat_override.get("params", {}))

    # Vocal/Harmonic kriegen weniger Drive als Drums/Bass
    drive_range = params.get("drive_pct_range", [10, 20])
    if track_role in ("vocal_lead", "vocal_backing", "harmonic", "acoustic_guitar"):
        drive_pct = round((drive_range[0] + drive_range[0]) / 2.0, 0)  # untere Grenze
    else:
        drive_pct = round((drive_range[0] + drive_range[1]) / 2.0, 0)

    return {
        "drive_pct": int(drive_pct),
        "tape_speed_ips": params.get("tape_speed_ips", 15),
        "type": params.get("type_options", ["tape"])[0],
    }


# ---------- Mess-basierte Anpassungen ----------

def _suggest_corrective_eq(
    analysis: AudioAnalysis,
    track_role: str,
) -> list[dict[str, Any]]:
    """
    Basierend auf Spektrum-Imbalances: subtraktive EQ-Moves vorschlagen.
    Nicht aggressiv — nur bei klaren Auffälligkeiten.
    """
    moves: list[dict[str, Any]] = []
    spec = analysis.spectrum

    # Boxiness: low_db deutlich höher als sub und mid → 250 Hz cut
    if spec.low_db > spec.mid_db - 3 and spec.low_db > spec.sub_db + 6:
        moves.append({
            "freq_hz": 250,
            "gain_db": -1.5,
            "q": 0.8,
            "purpose": "Boxiness reduzieren",
        })

    # Harshness: high_db deutlich über mid → 6-8 kHz cut
    if spec.high_db > spec.mid_db + 3:
        moves.append({
            "freq_hz": 7000,
            "gain_db": -1.5,
            "q": 0.7,
            "purpose": "Harshness zähmen",
        })

    # Vocal-spezifisch: Nasalität bei 1-2 kHz
    if track_role in ("vocal_lead", "vocal_backing"):
        # Nur als Hinweis, ohne konkreten Wert weil vom Sänger abhängig
        pass

    return moves


def _suggest_de_esser(
    analysis: AudioAnalysis,
    track_role: str,
) -> dict[str, Any] | None:
    """De-Esser nur für Vocals, basierend auf High-Band-Pegel."""
    if track_role not in ("vocal_lead", "vocal_backing"):
        return None
    spec = analysis.spectrum
    # Wenn high relativ stark gegenüber mid → De-Esser vorschlagen
    if spec.high_db > spec.mid_db - 6:
        return {
            "frequency_hz": 7000,
            "reduction_db_max": 4.0,
            "threshold_strategy": "auto_listen",
            "note": "Sweep im 5-9 kHz-Bereich, finden des Sibilanz-Peaks pro Sängerin",
        }
    return None


# ---------- Top-Level: Pre-Settings ableiten ----------

def suggest_track_pre_settings(
    analysis: AudioAnalysis,
    track_role: str,
    genre_id: str | None = None,
    platform_id: str = "spotify",
) -> TrackPreSettings:
    """
    Hauptfunktion: leitet aus Audio-Analyse + Track-Rolle + Genre konkrete
    Plugin-Setting-Vorschläge ab. NICHT zum direkten Drücken — Yoka prüft
    und justiert.
    """
    if track_role not in _HIGHPASS_CUTOFF_HZ:
        # Unbekannte Rolle — Default 'harmonic' verwenden
        track_role = "harmonic"

    settings = TrackPreSettings(track_role=track_role, genre_id=genre_id)

    # Genre laden falls vorhanden
    data = get_mastering_chains()
    genre = data["genres"].get(genre_id) if genre_id else None

    # ---- High-Pass ----
    hp_cutoff = _HIGHPASS_CUTOFF_HZ[track_role]
    settings.high_pass = {
        "cutoff_hz": hp_cutoff,
        "slope_db_oct": 24,
        "purpose": f"Subsonisches Rauschen + Spillover entfernen (Standard {hp_cutoff} Hz für '{track_role}')",
    }

    # ---- Corrective EQ ----
    settings.corrective_eq = _suggest_corrective_eq(analysis, track_role)

    # ---- Compressor ----
    if track_role != "master":
        # Track-Level Compressor
        ratio_default, attack_ms, release_ms, target_gr = _COMPRESSOR_DEFAULTS[track_role]
        threshold_db = _suggest_threshold_for_target_gr(
            analysis.loudness.rms_db, target_gr, ratio_default
        )
        comp_base = {
            "enabled": True,
            "ratio": ratio_default,
            "threshold_db": threshold_db,
            "attack_ms": attack_ms,
            "release_ms": release_ms,
            "target_gain_reduction_db": target_gr,
            "knee": "soft",
        }
        settings.compressor = comp_base
    else:
        # Master-Bus Compressor
        ratio_default, attack_ms, release_ms, target_gr = _COMPRESSOR_DEFAULTS["master"]
        comp_base = {
            "enabled": True,
            "ratio": ratio_default,
            "threshold_db": _suggest_threshold_for_target_gr(
                analysis.loudness.rms_db, target_gr, ratio_default
            ),
            "attack_ms": attack_ms,
            "release_ms": release_ms,
            "target_gain_reduction_db": target_gr,
            "knee": "soft",
        }
        comp_base = _apply_genre_compressor_modifiers(comp_base, genre)
        settings.compressor = comp_base

    # ---- De-Esser (nur Vocals) ----
    settings.de_esser = _suggest_de_esser(analysis, track_role)

    # ---- Saturation (genre-abhängig) ----
    settings.saturation = _apply_genre_saturation(track_role, genre)

    # ---- Limiter (nur master) ----
    if track_role == "master":
        platform = data["platforms"].get(platform_id)
        if platform:
            tp = platform.get("true_peak_db", -1.0)
            target_lufs = platform.get("target_lufs_integrated")
            settings.limiter = {
                "ceiling_db": tp,
                "release": "auto",
                "oversampling_factor": 4,
                "target_lufs": target_lufs,
                "platform": platform.get("display_name"),
            }

    # ---- Notes ----
    notes = []
    if genre:
        notes.append(
            f"Genre '{genre['display_name']}': {genre.get('description', '')}"
        )
        focus = genre.get("characteristic_focus", [])
        if focus:
            notes.append(f"Charakter-Fokus: {', '.join(focus)}")

    notes.append(
        f"Audio-Mess-Baseline: Peak {analysis.loudness.peak_db:+.1f} dB, "
        f"RMS {analysis.loudness.rms_db:+.1f} dB, "
        f"LUFS-I {analysis.loudness.lufs_integrated:+.1f}"
    )

    # Mono-Probleme aufgreifen
    if analysis.stereo.is_stereo and not analysis.stereo.mono_compatibility_ok:
        notes.append(
            "⚠️ Mono-Inkompatibilität im Bass-Bereich — Stereo-Imager-Setting prüfen, "
            "Bass strikt mono unter 200 Hz."
        )

    settings.notes = notes
    settings.measurements_used = {
        "peak_db": analysis.loudness.peak_db,
        "rms_db": analysis.loudness.rms_db,
        "spectrum_low_db": analysis.spectrum.low_db,
        "spectrum_mid_db": analysis.spectrum.mid_db,
        "spectrum_high_db": analysis.spectrum.high_db,
    }

    return settings


# ---------- Helpers für Tools ----------

def list_track_roles() -> list[dict[str, Any]]:
    """Liste der unterstützten Track-Rollen mit Default-Cutoffs."""
    return [
        {
            "role_id": role,
            "default_high_pass_hz": cutoff,
            "compressor_default_ratio": _COMPRESSOR_DEFAULTS[role][0],
        }
        for role, cutoff in _HIGHPASS_CUTOFF_HZ.items()
    ]
