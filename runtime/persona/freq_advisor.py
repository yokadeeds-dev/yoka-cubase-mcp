"""
Frequenz-Advisor (Sprint B) — Pro Track-Rolle Frequenz-Bereich-Empfehlungen
mit Cuts/Boosts/Problem-Zonen und Masking-Konflikten.

Quelle: YMP/Studium/35_EQ_Frequency_Management.md, strukturiert in
runtime/persona/knowledge/frequency_advice.json. Yoka erweitert fachlich.

Pure-Funcs ohne State, nutzt knowledge_loader-Pattern wie Mastering-Chain.

Ziel: Persona kann auf Anfrage *"wie EQe ich meinen Kick?"* eine
strukturierte Antwort geben mit Frequenz-Bereichen, typischen Eingriffen,
Problem-Zonen und Masking-Konflikten zu anderen Tracks.

Aufruf-Pattern:
    from runtime.persona.freq_advisor import get_freq_advice
    advice = get_freq_advice("kick")
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


_KNOWLEDGE_DIR = Path(__file__).resolve().parent / "knowledge"


_cache: dict[str, Any] = {}


def _load_freq_data() -> dict[str, Any]:
    """Lädt frequency_advice.json (cached)."""
    if "freq_advice" not in _cache:
        path = _KNOWLEDGE_DIR / "frequency_advice.json"
        if not path.exists():
            raise FileNotFoundError(f"frequency_advice.json fehlt: {path}")
        _cache["freq_advice"] = json.loads(path.read_text(encoding="utf-8"))
    return _cache["freq_advice"]


def reload() -> None:
    """Cache leeren — bei expliziter Yoka-Edit-Aktion."""
    _cache.clear()


def list_track_roles() -> list[dict[str, Any]]:
    """Liste aller Track-Rollen mit Display-Namen + Anzahl Core/Problem-Zonen."""
    data = _load_freq_data()
    roles = data.get("track_roles", {})
    return [
        {
            "role_id": rid,
            "display_name": role.get("display_name", rid),
            "core_zone_count": len(role.get("core_zones", [])),
            "problem_zone_count": len(role.get("problem_zones", [])),
            "has_masking_conflicts": bool(role.get("masking_conflicts", [])),
        }
        for rid, role in roles.items()
    ]


def list_frequency_bands() -> dict[str, Any]:
    """Liefert die definierten Frequenz-Bänder mit Beschreibungen."""
    data = _load_freq_data()
    return data.get("frequency_bands", {})


def get_freq_advice(track_role: str) -> dict[str, Any]:
    """
    Hauptfunktion: liefert strukturierte Frequenz-Empfehlung für eine Track-Rolle.

    Returns dict mit:
      - role_id, display_name
      - core_zones: list[zone] mit purpose, freq_hz, action, amount_db_range, q, notes
      - problem_zones: list[zone] mit issue + Lösung
      - high_pass_hz: empfohlener HP-Cutoff (oder None)
      - masking_conflicts: list[role_id] der Tracks die mit dieser konfligieren
      - complementary_eq_hint: optional Klartext-Hinweis
      - critical_listening_rules: globale Hör-Regeln (Solo vs Context, Loudness)
      - sweep_technique: Anleitung zum Problem-Frequenzen-Finden

    Wenn track_role unbekannt: ok=False mit available_roles.
    """
    data = _load_freq_data()
    role = data["track_roles"].get(track_role)
    if role is None:
        return {
            "ok": False,
            "error": f"Unbekannte Track-Rolle: {track_role!r}",
            "available_roles": sorted(data["track_roles"].keys()),
        }

    return {
        "ok": True,
        "role_id": track_role,
        "display_name": role.get("display_name", track_role),
        "core_zones": role.get("core_zones", []),
        "problem_zones": role.get("problem_zones", []),
        "high_pass_hz": role.get("high_pass_hz"),
        "masking_conflicts": role.get("masking_conflicts", []),
        "complementary_eq_hint": role.get("complementary_eq_hint"),
        "notes": role.get("notes"),
        "global_rules": {
            "solo_vs_context": data.get("critical_listening_rules", {}).get("solo_vs_context"),
            "reference_loudness_db_spl": data.get("critical_listening_rules", {}).get("reference_loudness_db_spl"),
            "fletcher_munson_warning": data.get("critical_listening_rules", {}).get("fletcher_munson_warning"),
        },
        "sweep_technique": data.get("sweep_technique_for_problem_freqs"),
        "version": data.get("version"),
        "source_doc": data.get("source_doc"),
    }


def find_masking_conflicts(track_role: str) -> dict[str, Any]:
    """
    Liefert die Tracks mit denen track_role konfligiert + Lösungs-Strategien.
    """
    data = _load_freq_data()
    role = data["track_roles"].get(track_role)
    if role is None:
        return {"ok": False, "error": f"Unbekannte Track-Rolle: {track_role!r}"}

    conflicts = role.get("masking_conflicts", [])
    # Gegen-Liste: welche Rollen haben track_role als Konflikt?
    reverse_conflicts = [
        other_id
        for other_id, other in data["track_roles"].items()
        if track_role in other.get("masking_conflicts", []) and other_id != track_role
    ]
    all_conflicts = sorted(set(conflicts + reverse_conflicts))

    return {
        "ok": True,
        "track_role": track_role,
        "conflicts_with": all_conflicts,
        "conflict_count": len(all_conflicts),
        "resolution_strategies": data.get("masking_resolution_strategies", {}),
        "complementary_eq_hint": role.get("complementary_eq_hint"),
    }
