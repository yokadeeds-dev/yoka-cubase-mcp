"""Plugin-Registry mit Lookup-Layer fuer Nicker.

Joined zwei Datenquellen:
- runtime/persona/knowledge/yoka_plugins.json    — Cubase-Plugin-Report (344 Plugins, Roh)
- runtime/persona/knowledge/plugin_tags.json     — KI-relevante Anreicherung (Sound-Tags,
                                                    Use-Cases, CC-Mapping-Refs, Lizenz-Status)

Loest das Context-Window-Problem aus dem Markt-Scan 2026-05-21:
Statt alle 344 Plugins im System-Prompt zu listen, ruft Nicker gezielt
`lookup_plugin(query)` und bekommt 3-10 relevante Treffer.

Inkrementell erweiterbar: neue Plugins ohne Tags fallen aus dem getaggten
Lookup raus, sind aber via Name-Match noch findbar.

Aufruf:
    from runtime.persona.plugin_registry import lookup_plugin, list_untagged

    # Free-text + Filter
    results = lookup_plugin(
        query="warm bass compressor",
        category=None,                  # optional: "Dynamics" / "EQ" / ...
        manufacturer=None,              # optional
        use_case=None,                  # optional: "bass_glue"
        sound_tag=None,                 # optional: "warm"
        with_cc_mapping_only=False,
        license_active_only=True,
        limit=10,
    )
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

_KNOWLEDGE_DIR = Path(__file__).resolve().parent / "knowledge"
_PLUGINS_FILE = _KNOWLEDGE_DIR / "yoka_plugins.json"
_TAGS_FILE = _KNOWLEDGE_DIR / "plugin_tags.json"


# ---------- Cache ----------

_cache: dict[str, Any] = {}


def _load_yoka_plugins() -> dict[str, Any]:
    if "yoka_plugins" not in _cache:
        if not _PLUGINS_FILE.exists():
            # Das Plugin-Inventar ist user-spezifisch (jeder hat ein anderes Cubase-Setup)
            # und wird NICHT mitgeliefert. Scanne dein eigenes mit:
            #   python -m runtime.persona.cubase_plugin_sync --apply
            # Bis dahin: leere Registry, damit der Server lauffähig bleibt.
            _cache["yoka_plugins"] = {"plugins": [], "_missing": True}
        else:
            _cache["yoka_plugins"] = json.loads(_PLUGINS_FILE.read_text(encoding="utf-8"))
    return _cache["yoka_plugins"]


def _load_tags() -> dict[str, Any]:
    if "tags" not in _cache:
        if not _TAGS_FILE.exists():
            raise FileNotFoundError(f"Plugin-Tags fehlen: {_TAGS_FILE}")
        _cache["tags"] = json.loads(_TAGS_FILE.read_text(encoding="utf-8"))
    return _cache["tags"]


def _build_index() -> dict[str, dict[str, Any]]:
    """Joined-Index: Plugin-Name -> kombiniertes Dict aus Roh + Tags."""
    if "index" in _cache:
        return _cache["index"]

    raw = _load_yoka_plugins()
    tags = _load_tags()

    # Tags-Lookup nach name
    tag_by_name = {t["name"]: t for t in tags.get("plugins", [])}

    index: dict[str, dict[str, Any]] = {}
    for p in raw.get("plugins", []):
        name = p["name"]
        merged = {
            "name": name,
            "vendor": p.get("vendor"),
            "type": p.get("type"),
            "version": p.get("version"),
            "vst_format": p.get("vst_format"),
            "is_instrument": p.get("type", "").startswith("Instrument"),
            # Tags-Anreicherung (kann fehlen, wenn ungetagged)
            "tags": [],
            "use_cases": [],
            "license_status": "unknown",
            "cc_mapping": None,
            "ki_role": "untagged",
            "notes": "",
            "tagged": False,
        }
        tag_entry = tag_by_name.get(name)
        if tag_entry:
            merged.update({
                "tags": tag_entry.get("tags", []),
                "use_cases": tag_entry.get("use_cases", []),
                "license_status": tag_entry.get("license_status", "unknown"),
                "cc_mapping": tag_entry.get("cc_mapping"),
                "ki_role": tag_entry.get("ki_role", "untagged"),
                "notes": tag_entry.get("notes", ""),
                "tagged": True,
            })
        index[name] = merged

    # Apply license_notes (z.B. Antares Demo-expired)
    license_notes = tags.get("license_notes", {})
    for note in license_notes.values():
        if note.get("status") == "demo_expired":
            for affected_name in note.get("affected_plugins", []):
                if affected_name in index:
                    index[affected_name]["license_status"] = "demo_expired"
                    if not index[affected_name]["notes"]:
                        index[affected_name]["notes"] = note.get("note", "")

    _cache["index"] = index
    return index


def reload() -> None:
    """Cache verwerfen — fuer Tests oder bei Hot-Reload."""
    _cache.clear()


# ---------- Lookup ----------

@dataclass
class LookupResult:
    """Strukturiertes Lookup-Ergebnis."""
    matches: list[dict[str, Any]] = field(default_factory=list)
    total_matches: int = 0
    query_summary: dict[str, Any] = field(default_factory=dict)
    search_strategy: str = "fuzzy_score"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _score_match(
    plugin: dict[str, Any],
    query: str | None,
    category: str | None,
    manufacturer: str | None,
    use_case: str | None,
    sound_tag: str | None,
) -> float:
    """Score 0..100. Filter-Misses geben 0 (= raus). Free-text addiert Punkte."""
    # Hart-Filter (alle muessen passen, sonst score=0)
    if manufacturer:
        vendor = (plugin.get("vendor") or "").lower()
        if manufacturer.lower() not in vendor:
            return 0.0
    if category:
        ptype = (plugin.get("type") or "").lower()
        if category.lower() not in ptype:
            return 0.0
    if use_case:
        if use_case not in plugin.get("use_cases", []):
            return 0.0
    if sound_tag:
        if sound_tag not in plugin.get("tags", []):
            return 0.0

    # Soft-Score
    score = 0.0
    if not query:
        # Kein query: Filter-Match alleine reicht, gib hoher Baseline-Score
        return 50.0

    q = query.lower()
    name = (plugin.get("name") or "").lower()
    vendor = (plugin.get("vendor") or "").lower()
    notes = (plugin.get("notes") or "").lower()
    tags_str = " ".join(plugin.get("tags", [])).lower()
    use_cases_str = " ".join(plugin.get("use_cases", [])).lower()

    # Exact-Name-Hit = top
    if q == name:
        return 100.0
    # Name-Substring = sehr stark
    if q in name:
        score += 60
    # Vendor-Hit
    if q in vendor:
        score += 20
    # Tag-Match
    for tok in q.split():
        if tok in tags_str:
            score += 15
        if tok in use_cases_str:
            score += 15
        if tok in notes:
            score += 5

    return score


def lookup_plugin(
    query: str | None = None,
    category: str | None = None,
    manufacturer: str | None = None,
    use_case: str | None = None,
    sound_tag: str | None = None,
    with_cc_mapping_only: bool = False,
    license_active_only: bool = True,
    limit: int = 10,
) -> LookupResult:
    """Sucht in der Plugin-Registry.

    Args:
        query: free-text (matched gegen Name/Vendor/Tags/UseCases/Notes).
        category: Cubase-Klassifikation (case-insensitive Substring): "EQ", "Dynamics", "Reverb", ...
        manufacturer: Vendor-Substring (case-insensitive): "FabFilter", "iZotope", ...
        use_case: Tag-Match: "bass_glue", "vocal_compression", "master_limiter", ...
        sound_tag: Tag-Match: "warm", "vintage", "transparent", ...
        with_cc_mapping_only: True = nur Plugins die via MIDI-CC steuerbar sind.
        license_active_only: True (default) = blockiert demo_expired-Plugins.
        limit: max. Anzahl Treffer (Default 10).

    Returns:
        LookupResult mit matches (sortiert nach Score absteigend).
    """
    index = _build_index()
    candidates = list(index.values())

    if with_cc_mapping_only:
        candidates = [c for c in candidates if c.get("cc_mapping")]

    if license_active_only:
        candidates = [
            c for c in candidates
            if c.get("license_status") not in ("demo_expired",)
        ]

    scored = []
    for c in candidates:
        s = _score_match(c, query, category, manufacturer, use_case, sound_tag)
        if s > 0:
            scored.append((s, c))

    scored.sort(key=lambda x: (-x[0], x[1]["name"]))

    matches = [c for _, c in scored[:limit]]

    return LookupResult(
        matches=matches,
        total_matches=len(scored),
        query_summary={
            "query": query,
            "category": category,
            "manufacturer": manufacturer,
            "use_case": use_case,
            "sound_tag": sound_tag,
            "with_cc_mapping_only": with_cc_mapping_only,
            "license_active_only": license_active_only,
            "limit": limit,
        },
        search_strategy="fuzzy_score (name>=60, vendor=20, tag/use_case=15, notes=5)",
    )


def get_plugin_details(name: str) -> dict[str, Any] | None:
    """Voll-Datensatz fuer ein bekanntes Plugin (Name muss exact matchen)."""
    return _build_index().get(name)


def list_untagged(limit: int | None = None) -> list[dict[str, Any]]:
    """Plugins die im Roh-Inventar sind, aber noch keine Tags haben.

    Hilfreich um inkrementell die Tag-DB zu erweitern.
    """
    index = _build_index()
    untagged = [
        {
            "name": p["name"],
            "vendor": p["vendor"],
            "type": p["type"],
        }
        for p in index.values() if not p.get("tagged")
    ]
    untagged.sort(key=lambda x: (x["vendor"], x["name"]))
    if limit:
        return untagged[:limit]
    return untagged


def registry_stats() -> dict[str, Any]:
    """Aggregierte Stats fuer Sanity-Check."""
    index = _build_index()
    tagged = [p for p in index.values() if p.get("tagged")]
    untagged = [p for p in index.values() if not p.get("tagged")]
    with_cc = [p for p in index.values() if p.get("cc_mapping")]
    license_buckets: dict[str, int] = {}
    role_buckets: dict[str, int] = {}
    for p in index.values():
        license_buckets[p.get("license_status", "unknown")] = (
            license_buckets.get(p.get("license_status", "unknown"), 0) + 1
        )
        role_buckets[p.get("ki_role", "untagged")] = (
            role_buckets.get(p.get("ki_role", "untagged"), 0) + 1
        )
    return {
        "total_plugins_in_inventory": len(index),
        "tagged": len(tagged),
        "untagged": len(untagged),
        "with_cc_mapping": len(with_cc),
        "by_license_status": license_buckets,
        "by_ki_role": role_buckets,
    }
