"""
Mastering-Chain-Advisor — Persona-Logik über mastering_chains.json.

Pure Funcs ohne State und ohne I/O über das Loader-Modul hinaus. Nimmt
genre_id + platform_id und liefert eine strukturierte Empfehlung mit:
  - aufgelöster Chain (generic_chain merged mit Genre-Overrides)
  - Loudness-Strategie (natural_lufs vs. platform_lufs, Empfehlung)
  - Genre- und Plattform-Metadaten (Display-Namen, Warnungen, etc.)

Nicht-Ziel: keine Audio-Analyse, kein Real-Time-Eingriff, keine
DAW-Plugin-Manipulation. Nur Wissens-basierte Strukturempfehlung.

Aufruf-Stelle: MCP-Tool nicker_suggest_mastering_chain in runtime/mcp/server.py
"""

from __future__ import annotations

from typing import Any

from runtime.persona.knowledge_loader import get_mastering_chains


def list_genres() -> list[dict[str, Any]]:
    """Liste aller Genres mit ihren Display-Namen und Natural-LUFS-Targets."""
    data = get_mastering_chains()
    return [
        {
            "genre_id": gid,
            "display_name": g["display_name"],
            "description": g.get("description", ""),
            "natural_target_lufs": g.get("natural_target_lufs"),
            "characteristic_focus": g.get("characteristic_focus", []),
        }
        for gid, g in data["genres"].items()
    ]


def list_platforms() -> list[dict[str, Any]]:
    """Liste aller Plattformen mit Target-LUFS und True-Peak-Limits."""
    data = get_mastering_chains()
    return [
        {
            "platform_id": pid,
            "display_name": p["display_name"],
            "target_lufs_integrated": p.get("target_lufs_integrated"),
            "true_peak_db": p.get("true_peak_db"),
            "normalization": p.get("normalization"),
        }
        for pid, p in data["platforms"].items()
    ]


def _resolve_chain_step(
    step: dict[str, Any],
    override: dict[str, Any] | None,
) -> dict[str, Any] | None:
    """
    Wendet ggf. einen Genre-Override auf einen Generic-Chain-Step an.
    Liefert None wenn Step deaktiviert ist (entweder default_disabled ohne
    Override-Aktivierung, oder explizit per Override deaktiviert).
    """
    is_optional = step.get("optional", False)
    default_enabled = step.get("default_enabled", not is_optional)

    if override is None:
        enabled = default_enabled
        merged_params = dict(step.get("params", {}))
        override_reason: str | None = None
    else:
        enabled = override.get("enabled", default_enabled)
        merged_params = dict(step.get("params", {}))
        merged_params.update(override.get("params", {}))
        override_reason = override.get("reason")

    if not enabled:
        return None

    return {
        "order": step["order"],
        "step_id": step["step_id"],
        "display_name": step["display_name"],
        "type": step["type"],
        "params": merged_params,
        "purpose": step["purpose"],
        "override_applied": override is not None and bool(override),
        "override_reason": override_reason,
        "warning": step.get("warning"),
    }


def _compute_loudness_strategy(
    natural_lufs: float | None,
    platform_lufs: float | None,
    platform_true_peak_db: float | None,
) -> dict[str, Any]:
    """
    Berechnet die Loudness-Strategie aus Genre-Natural und Plattform-Target.
    Liefert eine Empfehlung in Klartext + numerische Felder.
    """
    strategy: dict[str, Any] = {
        "natural_target_lufs": natural_lufs,
        "platform_target_lufs": platform_lufs,
        "true_peak_db": platform_true_peak_db,
    }

    if natural_lufs is None or platform_lufs is None:
        strategy["delta_db"] = None
        strategy["recommendation"] = (
            "LUFS-Vergleich nicht anwendbar (z. B. Vinyl-Master oder Deliverable "
            "ohne LUFS-Target). Peak-Kontrolle und genre-spezifische Constraints "
            "in den Hinweisen beachten."
        )
        return strategy

    # delta = natural - platform.
    # LUFS sind negativ; weniger negativ = lauter. Daher:
    #   delta > 0  -> Natural ist LAUTER als Platform-Target (z. B. Techno -8 vs Spotify -14: delta=+6)
    #   delta < 0  -> Natural ist LEISER als Platform-Target (z. B. Classical -18 vs Apple -16: delta=-2)
    #   delta ≈ 0  -> nahe beieinander
    delta = natural_lufs - platform_lufs
    strategy["delta_db"] = delta

    if delta > 3:
        strategy["recommendation"] = (
            f"Genre-Natural {natural_lufs:+.0f} LUFS ist {delta:.1f} dB lauter "
            f"als Plattform-Target {platform_lufs:+.0f} LUFS. Plattform-Normalisierung "
            f"regelt runter -> Dynamik-Verlust gegenüber natürlichem Genre-Sound. "
            f"Empfehlung: Limiter-Ziel zwischen den beiden Werten ansetzen "
            f"(~{(natural_lufs + platform_lufs) / 2:+.1f} LUFS) als Kompromiss."
        )
    elif delta < -1:
        strategy["recommendation"] = (
            f"Genre-Natural {natural_lufs:+.0f} LUFS ist {abs(delta):.1f} dB leiser als "
            f"Plattform-Target {platform_lufs:+.0f} LUFS. Genre-Charakter (Dynamik) "
            f"bewusst behalten — die Plattform regelt nicht hoch, nur runter."
        )
    else:
        strategy["recommendation"] = (
            f"Genre-Natural und Plattform-Target nahe beieinander "
            f"({natural_lufs:+.0f} vs {platform_lufs:+.0f} LUFS, Delta {delta:+.1f} dB). "
            f"Limiter direkt auf {platform_lufs:+.0f} LUFS, True Peak {platform_true_peak_db} dB."
        )

    return strategy


def suggest_mastering_chain(
    genre_id: str,
    platform_id: str = "spotify",
) -> dict[str, Any]:
    """
    Hauptfunktion: liefert strukturierte Mastering-Chain-Empfehlung
    für (Genre × Plattform).

    Returns dict mit:
      - ok: True/False
      - genre: aufgelöste Genre-Metadaten
      - platform: aufgelöste Plattform-Metadaten
      - chain: list[step], gemerged aus generic_chain + Genre-Overrides
      - loudness_strategy: numerische Loudness-Empfehlung
      - warnings: aggregierte Warnungen aus Genre + aktiven Steps
      - source: Verweis auf YMP-Doc

    Wenn genre_id oder platform_id unbekannt: ok=False mit available_*-Liste.
    """
    data = get_mastering_chains()

    genre = data["genres"].get(genre_id)
    if genre is None:
        return {
            "ok": False,
            "error": f"Unbekanntes Genre: {genre_id!r}",
            "available_genres": sorted(data["genres"].keys()),
        }

    platform = data["platforms"].get(platform_id)
    if platform is None:
        return {
            "ok": False,
            "error": f"Unbekannte Plattform: {platform_id!r}",
            "available_platforms": sorted(data["platforms"].keys()),
        }

    # Generic-Chain mit Genre-Overrides auflösen, geordnet nach 'order'
    overrides = genre.get("chain_overrides", {})
    chain: list[dict[str, Any]] = []
    sorted_steps = sorted(data["generic_chain"], key=lambda s: s["order"])
    for step in sorted_steps:
        resolved = _resolve_chain_step(step, overrides.get(step["step_id"]))
        if resolved is not None:
            chain.append(resolved)

    # Aggregierte Warnungen sammeln
    warnings = list(genre.get("warnings", []))
    for step in chain:
        if step.get("warning"):
            warnings.append(f"[{step['display_name']}] {step['warning']}")

    # Loudness-Strategie
    loudness = _compute_loudness_strategy(
        natural_lufs=genre.get("natural_target_lufs"),
        platform_lufs=platform.get("target_lufs_integrated"),
        platform_true_peak_db=platform.get("true_peak_db"),
    )

    return {
        "ok": True,
        "genre": {
            "id": genre_id,
            "display_name": genre["display_name"],
            "description": genre.get("description"),
            "characteristic_focus": genre.get("characteristic_focus", []),
            "priority_steps": genre.get("priority_steps", []),
            "metering_targets": genre.get("metering_targets", {}),
            "reference_artists": genre.get("reference_artists", []),
        },
        "platform": {
            "id": platform_id,
            "display_name": platform["display_name"],
            "target_lufs_integrated": platform.get("target_lufs_integrated"),
            "true_peak_db": platform.get("true_peak_db"),
            "normalization": platform.get("normalization"),
            "notes": platform.get("notes"),
        },
        "chain": chain,
        "loudness_strategy": loudness,
        "warnings": warnings,
        "version": data.get("version"),
        "source_doc": data.get("source_doc"),
    }
