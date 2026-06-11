"""
Persona-Wissens-Loader.

Lädt strukturierte Wissensbasis-Dateien (JSON) und liefert sie als getypte
Dicts an die Persona-Tools. Module-Level-Cache verhindert mehrfaches Lesen
während eines Server-Lifetime.

Phase 1 (jetzt): statisches JSON-Loading, keine Embeddings, kein Hot-Reload
außer via expliziter `reload_all()`-Aufruf.

Phase 2 (geplant): Vector-RAG (mem0-mcp oder ChromaDB) für die YMP/Studium/-
Markdown-Dokumente. Dann strukturierte Daten (mastering_chains.json) und
freier Volltext nebeneinander.

Datenpfad-Konvention:
    runtime/persona/knowledge/<dataset>.json

Schema-Validierung ist absichtlich light: Pflicht-Top-Level-Keys werden
geprüft, alles andere bleibt offen für inkrementelle Erweiterung durch Yoka.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


_KNOWLEDGE_DIR = Path(__file__).resolve().parent / "knowledge"

# Pflicht-Top-Level-Keys pro Dataset — minimale Plausibilitätsprüfung.
# Erweiterbar wenn Datasets reifer werden.
_REQUIRED_KEYS: dict[str, tuple[str, ...]] = {
    "mastering_chains": ("version", "platforms", "generic_chain", "genres"),
}


class KnowledgeLoadError(Exception):
    """Wirft der Loader bei fehlenden/kaputten Wissensbasis-Files."""


def _read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        raise KnowledgeLoadError(f"Wissensbasis-Datei nicht gefunden: {path}")
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        raise KnowledgeLoadError(f"Ungültiges JSON in {path.name}: {e}") from e


def _validate_required_keys(data: dict[str, Any], dataset_name: str) -> None:
    required = _REQUIRED_KEYS.get(dataset_name, ())
    for key in required:
        if key not in data:
            raise KnowledgeLoadError(
                f"Wissensbasis '{dataset_name}' fehlt Pflicht-Key: {key!r}"
            )


def load_mastering_chains() -> dict[str, Any]:
    """
    Lädt mastering_chains.json — Plattform-Targets, generic_chain (geordnet
    nach 'order'-Feld), genres mit chain_overrides, deliverable_formats.

    Wirft KnowledgeLoadError wenn Datei fehlt oder ungültiges JSON.
    """
    data = _read_json(_KNOWLEDGE_DIR / "mastering_chains.json")
    _validate_required_keys(data, "mastering_chains")
    return data


# ---------- Module-Level-Cache ----------
#
# Singleton-Cache: einmal pro Server-Lifetime laden. Bei Bedarf via
# reload_all() leeren — z. B. nach dem User die JSON manuell editiert hat.

_cache: dict[str, Any] = {}


def get_mastering_chains() -> dict[str, Any]:
    """Cached accessor — Loader läuft nur beim ersten Aufruf."""
    if "mastering_chains" not in _cache:
        _cache["mastering_chains"] = load_mastering_chains()
    return _cache["mastering_chains"]


def reload_all() -> None:
    """
    Cache leeren — der nächste Accessor-Aufruf lädt frisch von Disk.
    Genutzt vom Tool nicker_reload_knowledge() (Phase 1.x, optional).
    """
    _cache.clear()


def is_loaded(dataset: str) -> bool:
    """Diagnose: ist ein Dataset aktuell im Cache?"""
    return dataset in _cache
