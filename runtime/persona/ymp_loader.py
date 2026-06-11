"""
YMP-Studium-Loader — Phase-1-Implementierung der Wissensbasis-Anbindung.

Liest die Markdown-Dokumente aus dem YMP-Repo (sibling-Verzeichnis zum
KI-Studio-Repo) und stellt sie als indexierte Wissensbasis für Persona
Nicker bereit.

Phase-1-Funktionen (jetzt):
- Auto-Discovery aller `Studium/*.md`-Dateien
- Metadaten-Extraktion: ymp_id (aus Dateinamen), Titel (aus erster #-Zeile
  oder Frontmatter), Kategorie (per ymp_id-Range inferiert), Tags
- Keyword-Suche mit gewichteter Treffer-Score (Titel > Tags > Body)
- Singleton-Cache für Index, Body-Cache pro Dokument

Phase-2 (geplant):
- Frontmatter-Parsing (wenn Yoka es ergänzt)
- Vector-RAG via mem0-mcp / ChromaDB
- Hot-Reload bei File-Change

Pfad-Konvention:
- ENV-Var `YMP_PATH` als expliziter Override (z. B. für Tests)
- Default: `../YMP` relativ zum Repo-Root, also Sibling
- Fallback: Persona schreit nicht, sondern liefert leeren Index +
  Fehler-Status — Tools die D2 (Wissensbasis-Vorrang) brauchen, können
  das transparent melden.

Aufruf-Stellen:
- `nicker_explain(topic)` (geplant) ruft `search_studium(topic)`
- `nicker_list_studium_docs()` (geplant) ruft `get_studium_index()`
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


# ---------- Pfad-Resolution ----------

_REPO_ROOT = Path(__file__).resolve().parent.parent.parent  # KI-Studio-Repo-Root
_DEFAULT_YMP_RELATIVE = _REPO_ROOT.parent / "YMP"           # Sibling-Verzeichnis


def get_ymp_path() -> Path:
    """
    Liefert den Pfad zum YMP-Repo. Reihenfolge:
    1. ENV `YMP_PATH` falls gesetzt
    2. Default: `<KI-Studio-parent>/YMP`
    """
    env = os.environ.get("YMP_PATH")
    if env:
        return Path(env)
    return _DEFAULT_YMP_RELATIVE


def get_studium_path() -> Path:
    """Pfad zum Studium-Verzeichnis innerhalb YMP."""
    return get_ymp_path() / "Studium"


# ---------- Kategorie-Inferenz (per ymp_id-Range) ----------
#
# Cluster-Mapping (Stand 2026-05-04, Erweiterung um Docs 37-42, 46, 50-52):
# - 0-18         → foundation (theoretischer Hintergrund)
# - 19-20, 22-26, 28, 46-59 → daw_tools (Werkzeuge, Live-Perf, Hardware, Synthese)
# - 21, 27, 29-45            → production_craft (Mastering, Mixing, FX, Automation)
#
# Die ID-Ranges sind bewusst leicht großzügiger als der aktuelle Bestand,
# damit künftige Docs (43-45, 47-49, 53+) automatisch einsortiert werden.
# Bei Fehlsortierung: explizite Liste anpassen.

_FOUNDATION_IDS = set(range(0, 19))                # 0-18
_DAW_TOOL_IDS = ({19, 20} | set(range(22, 27))     # 22-26
                 | {28}
                 | set(range(46, 60)))             # 46-59
_PRODUCTION_IDS = {21, 27} | set(range(29, 46))    # 21, 27, 29-45


def infer_category(ymp_id: int) -> str:
    """Liefert Themen-Cluster für eine ymp_id."""
    if ymp_id in _FOUNDATION_IDS:
        return "foundation"
    if ymp_id in _DAW_TOOL_IDS:
        return "daw_tools"
    if ymp_id in _PRODUCTION_IDS:
        return "production_craft"
    return "uncategorized"


# ---------- Datenstruktur ----------

@dataclass
class StudiumDoc:
    """Metadaten + (lazy geladener) Body-Inhalt eines YMP-Studium-Dokuments."""

    ymp_id: int
    title: str
    category: str
    tags: list[str]
    path: Path
    size_bytes: int
    _body_cache: str | None = field(default=None, repr=False)

    def to_dict(self) -> dict[str, Any]:
        """Serialisierbares Dict für MCP-Tool-Returns."""
        return {
            "ymp_id": self.ymp_id,
            "title": self.title,
            "category": self.category,
            "tags": self.tags,
            "path": self.path.name,
            "size_bytes": self.size_bytes,
        }

    def body(self) -> str:
        """Lädt den Body-Text, cached pro Doc-Instanz."""
        if self._body_cache is None:
            self._body_cache = self.path.read_text(encoding="utf-8")
        return self._body_cache


# ---------- Filename- + Body-Parser ----------

_FILENAME_PATTERN = re.compile(r"^(\d{1,3})_(.+)\.md$")
_FIRST_HEADING_PATTERN = re.compile(r"^#\s+(.+?)\s*$", re.MULTILINE)
_FRONTMATTER_PATTERN = re.compile(r"^---\s*\n(.*?)\n---\s*\n", re.DOTALL)


# Stop-Words für Tag-Extraction aus Filenamen — irrelevante Bindewörter
_TAG_STOPWORDS = {
    "der", "die", "das", "des", "und", "von", "im", "in", "fuer", "mit",
    "des", "dem", "den", "ein", "eine", "einer", "eines", "auf", "an",
}


def _extract_title_from_body(body: str, fallback: str) -> str:
    """
    Erste `# Heading`-Zeile als Titel. Falls keine vorhanden, Fallback nutzen.
    Frontmatter-`title:`-Feld wird in Phase 2 vorrangig respektiert.
    """
    m = _FIRST_HEADING_PATTERN.search(body)
    if m:
        title = m.group(1).strip()
        # "21 – Mastering & Finalizing" → "Mastering & Finalizing"
        title = re.sub(r"^\d+\s*[–\-]\s*", "", title)
        return title
    return fallback


def _extract_tags_from_filename(filename_part: str) -> list[str]:
    """Aus dem Underscore-getrennten Teil eines Filenamens Tags ableiten."""
    tokens = filename_part.lower().split("_")
    tags = [t for t in tokens if t and t not in _TAG_STOPWORDS and not t.isdigit()]
    return tags


def _parse_doc_metadata(path: Path) -> StudiumDoc | None:
    """Parst eine einzelne .md-Datei. Liefert None bei Filename-Mismatch."""
    m = _FILENAME_PATTERN.match(path.name)
    if not m:
        return None
    ymp_id = int(m.group(1))
    filename_part = m.group(2)

    # Body lesen für Titel-Extraktion (Body wird auch gecached)
    body = path.read_text(encoding="utf-8")
    fallback_title = filename_part.replace("_", " ")
    title = _extract_title_from_body(body, fallback_title)

    tags = _extract_tags_from_filename(filename_part)
    category = infer_category(ymp_id)

    doc = StudiumDoc(
        ymp_id=ymp_id,
        title=title,
        category=category,
        tags=tags,
        path=path,
        size_bytes=len(body.encode("utf-8")),
    )
    doc._body_cache = body  # Body schon geladen, in Cache stellen
    return doc


# ---------- Index-Aufbau + Cache ----------

_index_cache: dict[str, Any] = {}


def _build_index() -> dict[str, Any]:
    """
    Scannt Studium/, baut Index-Dictionaries auf:
    - by_id: ymp_id -> StudiumDoc
    - by_category: category -> list[ymp_id]
    - by_tag: tag -> list[ymp_id]
    """
    studium_path = get_studium_path()
    if not studium_path.exists() or not studium_path.is_dir():
        return {
            "by_id": {},
            "by_category": {},
            "by_tag": {},
            "studium_path": str(studium_path),
            "available": False,
            "error": f"YMP/Studium nicht gefunden unter {studium_path}",
        }

    by_id: dict[int, StudiumDoc] = {}
    by_category: dict[str, list[int]] = {}
    by_tag: dict[str, list[int]] = {}

    for path in sorted(studium_path.glob("*.md")):
        doc = _parse_doc_metadata(path)
        if doc is None:
            continue
        by_id[doc.ymp_id] = doc
        by_category.setdefault(doc.category, []).append(doc.ymp_id)
        for tag in doc.tags:
            by_tag.setdefault(tag, []).append(doc.ymp_id)

    return {
        "by_id": by_id,
        "by_category": by_category,
        "by_tag": by_tag,
        "studium_path": str(studium_path),
        "available": True,
    }


def get_studium_index() -> dict[str, Any]:
    """Cached Index-Accessor."""
    if "studium" not in _index_cache:
        _index_cache["studium"] = _build_index()
    return _index_cache["studium"]


def reload_index() -> None:
    """Cache leeren — Re-Scan von Disk beim nächsten Accessor-Aufruf."""
    _index_cache.clear()


# ---------- Public API: Listing + Lookup ----------

def list_studium_docs() -> list[dict[str, Any]]:
    """Liste aller Studium-Dokumente, nach ymp_id sortiert."""
    index = get_studium_index()
    if not index.get("available"):
        return []
    docs = sorted(index["by_id"].values(), key=lambda d: d.ymp_id)
    return [d.to_dict() for d in docs]


def get_studium_doc(
    ymp_id: int,
    include_body: bool = False,
    max_chars: int = 2000,
) -> dict[str, Any] | None:
    """
    Einzelnes Doc per ymp_id.

    Wenn include_body=True wird der Body-Text mit eingehängt.
    max_chars=0 bedeutet kompletter Body, sonst Excerpt mit Trunkations-Marker.
    Default 2000 Char ≈ erste 1-2 Sektionen — gut für Persona-Antworten,
    ohne Token-Budget zu sprengen.
    """
    index = get_studium_index()
    doc = index["by_id"].get(ymp_id) if index.get("available") else None
    if doc is None:
        return None
    result = doc.to_dict()
    if include_body:
        body = doc.body()
        body_len = len(body)
        result["body_full_length"] = body_len
        if max_chars > 0 and body_len > max_chars:
            result["body_excerpt"] = body[:max_chars] + "…"
            result["body_truncated"] = True
        else:
            result["body_excerpt"] = body
            result["body_truncated"] = False
    return result


def list_categories() -> dict[str, list[int]]:
    """category-Name -> list of ymp_ids in dieser Kategorie."""
    index = get_studium_index()
    return dict(index.get("by_category", {}))


def list_tags() -> dict[str, list[int]]:
    """tag-Name -> list of ymp_ids mit diesem Tag."""
    index = get_studium_index()
    return dict(index.get("by_tag", {}))


# ---------- Keyword-Suche ----------

# Treffer-Gewichtung: Titel-Match wiegt zehnfach, Tag-Match fünffach,
# Body-Match einfach. Damit landen direkte Themen-Treffer oben.
_WEIGHT_TITLE = 10
_WEIGHT_TAG = 5
_WEIGHT_BODY = 1


def _tokenize_query(query: str) -> list[str]:
    """Lowercase-Split mit minimaler Bereinigung."""
    return [t for t in re.split(r"\s+", query.lower().strip()) if t]


def _count_occurrences(text: str, term: str) -> int:
    """Anzahl Vorkommen von term (case-insensitive) in text."""
    if not term:
        return 0
    return len(re.findall(re.escape(term), text, flags=re.IGNORECASE))


def _extract_snippet(body: str, term: str, context_chars: int = 80) -> str | None:
    """
    Findet ersten Treffer von term im body, returnt umliegenden Snippet
    mit `…` als Ellipse. None wenn term nicht gefunden.
    """
    m = re.search(re.escape(term), body, flags=re.IGNORECASE)
    if m is None:
        return None
    start = max(0, m.start() - context_chars)
    end = min(len(body), m.end() + context_chars)
    snippet = body[start:end].strip()
    # Newlines als Spaces, mehrfache Spaces collapse
    snippet = re.sub(r"\s+", " ", snippet)
    if start > 0:
        snippet = "…" + snippet
    if end < len(body):
        snippet = snippet + "…"
    return snippet


def search_studium(query: str, top_k: int = 5) -> list[dict[str, Any]]:
    """
    Keyword-Suche über alle Studium-Dokumente.

    Score-Formel: für jeden Query-Token zählt jeder Treffer in:
      - title (×10)
      - tags (×5)
      - body (×1)

    Liefert top_k Dokumente sortiert nach Gesamtscore, jeweils mit
    erstem Snippet (Body-Kontext um den Treffer herum).
    """
    index = get_studium_index()
    if not index.get("available"):
        return []
    tokens = _tokenize_query(query)
    if not tokens:
        return []

    scored: list[tuple[int, StudiumDoc, dict[str, Any]]] = []

    for doc in index["by_id"].values():
        score = 0
        snippet: str | None = None
        body = doc.body()
        title_lower = doc.title.lower()
        tags_lower = [t.lower() for t in doc.tags]

        for token in tokens:
            score += _count_occurrences(title_lower, token) * _WEIGHT_TITLE
            score += sum(_count_occurrences(tag, token) for tag in tags_lower) * _WEIGHT_TAG
            score += _count_occurrences(body, token) * _WEIGHT_BODY

            if snippet is None:
                snippet = _extract_snippet(body, token)

        if score > 0:
            scored.append((score, doc, {"snippet": snippet}))

    scored.sort(key=lambda x: x[0], reverse=True)

    return [
        {
            **doc.to_dict(),
            "score": score,
            "snippet": meta["snippet"],
        }
        for score, doc, meta in scored[:top_k]
    ]
