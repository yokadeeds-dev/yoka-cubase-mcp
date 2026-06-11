"""
Reaction-Tagging-Layer (Sprint G MVP) — Yoka als Feedback-Geber.

Yokas Konzept (2026-05-05): Yoka ist die Kalibrierungs-Quelle für sein
personalisiertes Hör-Modell. Während Hör-Sessions schnelles Tagging:
*kribbelt / Gänsehaut / abstoßend / neutral / langweilig* + (für Live-
Performances) *tanzfläche_ausgerastet / gejubelt / mitgesungen / pause /
verlassen*. Tag wird mit DAW-State-Snapshot + optional Audio-Position +
Notiz koppelt.

Phase 1 (jetzt): JSONL-Append-Persistenz, MCP-Tools für Logging +
Auswertungs-Summary. Hotkey-Empfänger (AHK-Erweiterung) folgt später.

Persistenz-Pfad:
    runtime/state/reactions.jsonl

Ein Eintrag pro Zeile, JSON-strukturiert für späteres Re-Parsing /
Aggregation. Append-only, kein In-Place-Edit.
"""

from __future__ import annotations

import json
import time
from collections import Counter, defaultdict
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any


_REPO_ROOT = Path(__file__).resolve().parent.parent.parent
_DEFAULT_LOG_PATH = _REPO_ROOT / "runtime" / "state" / "reactions.jsonl"


# Erlaubte Tag-Vokabulare (erweiterbar in einer YAML später, hier hardcoded
# für MVP). Personal-Mode + Crowd-Mode getrennt klassifiziert damit später
# auswertbar ist welche Sessions Solo-Listening und welche Live-Performances
# waren.

PERSONAL_TAGS: set[str] = {
    "g",  # Gänsehaut
    "k",  # kribbelt
    "a",  # abstoßend
    "n",  # neutral
    "l",  # langweilig
    "t",  # Träne / emotional bewegt
    "e",  # euphorisch
    "f",  # Flow / im Sound aufgehen
    "u",  # ungeduldig / will weiter
    "z",  # Zorn / aggressiv-getriggert
}

CROWD_TAGS: set[str] = {
    "tanzflaeche_ausgerastet",
    "gejubelt",
    "mitgesungen",
    "pause_genutzt",
    "verlassen",
    "stillgestanden",
    "tanzpaare_gebildet",
}

# Tag-Display-Namen für Reports
TAG_DISPLAY: dict[str, str] = {
    "g": "Gänsehaut",
    "k": "kribbelt",
    "a": "abstoßend",
    "n": "neutral",
    "l": "langweilig",
    "t": "Träne / emotional bewegt",
    "e": "euphorisch",
    "f": "Flow",
    "u": "ungeduldig",
    "z": "Zorn / aggressiv-getriggert",
}


@dataclass
class ReactionEntry:
    """Ein Reaction-Tag-Eintrag mit Kontext."""
    tag: str
    timestamp: str           # ISO 8601 mit Timezone
    monotonic_ms: int        # für Audio-Position-Korrelation
    mode: str                # "personal" | "crowd"
    note: str | None = None
    audio_position_s: float | None = None
    track_name: str | None = None
    daw_state_snapshot: dict[str, Any] | None = None
    session_id: str | None = None     # falls in laufender Session
    person_id: str = "P01"            # Yoka als Default

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _now_iso() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime()) + time.strftime("%z")


def _classify_mode(tag: str) -> str:
    if tag in PERSONAL_TAGS:
        return "personal"
    if tag in CROWD_TAGS:
        return "crowd"
    return "unknown"


def _ensure_log_path(path: Path) -> Path:
    """Stellt sicher dass das Verzeichnis existiert."""
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def log_reaction(
    tag: str,
    note: str | None = None,
    audio_position_s: float | None = None,
    track_name: str | None = None,
    daw_state_snapshot: dict[str, Any] | None = None,
    session_id: str | None = None,
    person_id: str = "P01",
    log_path: Path | None = None,
) -> dict[str, Any]:
    """
    Logged einen Reaction-Tag mit Timestamp + optional Kontext-Snapshot.

    tag: aus PERSONAL_TAGS oder CROWD_TAGS — Mode wird auto-klassifiziert.
         Unbekannte Tags werden auch akzeptiert (mode='unknown') für
         Vokabular-Erweiterung; können später in PERSONAL/CROWD migriert
         werden.

    Liefert das gespeicherte Entry-Dict.
    """
    mode = _classify_mode(tag)
    entry = ReactionEntry(
        tag=tag,
        timestamp=_now_iso(),
        monotonic_ms=int(time.monotonic() * 1000),
        mode=mode,
        note=note,
        audio_position_s=audio_position_s,
        track_name=track_name,
        daw_state_snapshot=daw_state_snapshot,
        session_id=session_id,
        person_id=person_id,
    )
    p = _ensure_log_path(log_path or _DEFAULT_LOG_PATH)
    line = json.dumps(entry.to_dict(), ensure_ascii=False, default=str)
    with open(p, "a", encoding="utf-8") as f:
        f.write(line + "\n")
    return entry.to_dict()


def read_reactions(
    log_path: Path | None = None,
    person_id: str | None = None,
    mode: str | None = None,
    session_id: str | None = None,
) -> list[dict[str, Any]]:
    """
    Liest Reaction-Log und filtert optional nach person_id, mode oder
    session_id. JSON-Decoding-Fehler werden geskipped (robust gegen
    kaputte Zeilen).
    """
    p = log_path or _DEFAULT_LOG_PATH
    if not p.exists():
        return []
    out: list[dict[str, Any]] = []
    for line in p.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            entry = json.loads(line)
        except json.JSONDecodeError:
            continue
        if person_id is not None and entry.get("person_id") != person_id:
            continue
        if mode is not None and entry.get("mode") != mode:
            continue
        if session_id is not None and entry.get("session_id") != session_id:
            continue
        out.append(entry)
    return out


def reaction_summary(
    log_path: Path | None = None,
    person_id: str | None = None,
    mode: str | None = None,
    session_id: str | None = None,
) -> dict[str, Any]:
    """
    Aggregiert das Reaction-Log: Gesamt-Counts pro Tag, pro Person, pro
    Modus, plus Track-Korrelation falls track_name gesetzt war.

    Liefert ein strukturiertes Dict mit Counts + Highlights, geeignet
    für Persona-Antworten.
    """
    entries = read_reactions(log_path=log_path, person_id=person_id, mode=mode, session_id=session_id)
    if not entries:
        return {
            "total_entries": 0,
            "tag_counts": {},
            "by_person": {},
            "by_mode": {},
            "by_track": {},
        }

    tag_counts: Counter[str] = Counter()
    by_person: dict[str, Counter[str]] = defaultdict(Counter)
    by_mode: Counter[str] = Counter()
    by_track: dict[str, Counter[str]] = defaultdict(Counter)

    for e in entries:
        t = e.get("tag", "?")
        p = e.get("person_id", "?")
        m = e.get("mode", "?")
        track = e.get("track_name")
        tag_counts[t] += 1
        by_person[p][t] += 1
        by_mode[m] += 1
        if track:
            by_track[track][t] += 1

    # Top-Track-Reactions (welche Tracks haben die meisten Reactions)
    top_tracks_by_count = sorted(
        ((tr, sum(c.values()), dict(c)) for tr, c in by_track.items()),
        key=lambda x: x[1],
        reverse=True,
    )[:10]

    return {
        "total_entries": len(entries),
        "tag_counts": dict(tag_counts),
        "tag_display": {t: TAG_DISPLAY.get(t, t) for t in tag_counts},
        "by_person": {p: dict(c) for p, c in by_person.items()},
        "by_mode": dict(by_mode),
        "by_track": {tr: dict(c) for tr, c in by_track.items()},
        "top_tracks_by_reactions": [
            {"track": tr, "total_reactions": cnt, "tag_breakdown": breakdown}
            for tr, cnt, breakdown in top_tracks_by_count
        ],
        "first_timestamp": entries[0].get("timestamp"),
        "last_timestamp": entries[-1].get("timestamp"),
    }


def list_known_tags() -> dict[str, Any]:
    """Liefert die definierten Tag-Vokabulare für UI/Hotkey-Mapping."""
    return {
        "personal": [
            {"tag": t, "display": TAG_DISPLAY.get(t, t)}
            for t in sorted(PERSONAL_TAGS)
        ],
        "crowd": [{"tag": t, "display": t.replace("_", " ")} for t in sorted(CROWD_TAGS)],
        "log_path": str(_DEFAULT_LOG_PATH),
    }
