"""
Selftest für runtime/persona/reaction_logger.py — Sprint G MVP.

Komplett autonom, schreibt in temp-File statt Production-Log.

Aufruf:
    python -m tests.selftests.reaction_logger_selftest
"""

from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from runtime.persona.reaction_logger import (  # noqa: E402
    CROWD_TAGS,
    PERSONAL_TAGS,
    list_known_tags,
    log_reaction,
    reaction_summary,
    read_reactions,
)


def _temp_log() -> Path:
    """Frische temp .jsonl pro Test."""
    tmp = tempfile.NamedTemporaryFile(suffix=".jsonl", delete=False)
    tmp.close()
    p = Path(tmp.name)
    p.unlink(missing_ok=True)  # Datei selbst muss nicht existieren, nur Pfad
    return p


def test_log_personal_tag() -> None:
    log = _temp_log()
    try:
        entry = log_reaction("g", note="Bridge auf Track 5 hat geknallt", track_name="trip_hop_test", log_path=log)
        assert entry["tag"] == "g"
        assert entry["mode"] == "personal"
        assert entry["track_name"] == "trip_hop_test"
        assert "timestamp" in entry
        assert "monotonic_ms" in entry
        # Datei existiert + 1 Zeile
        assert log.exists()
        lines = log.read_text(encoding="utf-8").splitlines()
        assert len(lines) == 1
        parsed = json.loads(lines[0])
        assert parsed["tag"] == "g"
        print(f"  log_personal_tag OK -> g (Gänsehaut), Track 'trip_hop_test'")
    finally:
        log.unlink(missing_ok=True)


def test_log_crowd_tag() -> None:
    log = _temp_log()
    try:
        entry = log_reaction("tanzflaeche_ausgerastet", note="Drop bei 3:14", log_path=log)
        assert entry["mode"] == "crowd"
        assert entry["tag"] == "tanzflaeche_ausgerastet"
        print(f"  log_crowd_tag OK -> tanzflaeche_ausgerastet")
    finally:
        log.unlink(missing_ok=True)


def test_log_unknown_tag_accepted() -> None:
    """Unbekannter Tag: mode='unknown', aber kein Crash. Erlaubt Vokabular-Erweiterung."""
    log = _temp_log()
    try:
        entry = log_reaction("schwebend", note="experimentell", log_path=log)
        assert entry["mode"] == "unknown"
        assert entry["tag"] == "schwebend"
        print(f"  log_unknown_tag_accepted OK -> 'schwebend' mode=unknown")
    finally:
        log.unlink(missing_ok=True)


def test_log_with_daw_snapshot() -> None:
    """DAW-State-Snapshot wird mit gespeichert."""
    log = _temp_log()
    try:
        snapshot = {
            "mode": "plugin",
            "active_track": {"index": 6, "name": "DUNE01"},
            "active_plugin": {"plugin_name": "Physion Mk II", "page": 3},
        }
        entry = log_reaction("g", daw_state_snapshot=snapshot, log_path=log)
        assert entry["daw_state_snapshot"] == snapshot
        # Re-read
        entries = read_reactions(log_path=log)
        assert entries[0]["daw_state_snapshot"]["active_plugin"]["plugin_name"] == "Physion Mk II"
        print(f"  log_with_daw_snapshot OK -> Plugin-State im Eintrag persistiert")
    finally:
        log.unlink(missing_ok=True)


def test_read_reactions_filter_by_person() -> None:
    log = _temp_log()
    try:
        log_reaction("g", person_id="P01", log_path=log)
        log_reaction("k", person_id="P02", log_path=log)
        log_reaction("e", person_id="P01", log_path=log)
        p01 = read_reactions(log_path=log, person_id="P01")
        p02 = read_reactions(log_path=log, person_id="P02")
        assert len(p01) == 2
        assert len(p02) == 1
        assert all(e["person_id"] == "P01" for e in p01)
        print(f"  read_reactions_filter_by_person OK -> P01: 2, P02: 1")
    finally:
        log.unlink(missing_ok=True)


def test_read_reactions_filter_by_mode() -> None:
    log = _temp_log()
    try:
        log_reaction("g", log_path=log)              # personal
        log_reaction("tanzflaeche_ausgerastet", log_path=log)   # crowd
        log_reaction("k", log_path=log)              # personal
        personal = read_reactions(log_path=log, mode="personal")
        crowd = read_reactions(log_path=log, mode="crowd")
        assert len(personal) == 2
        assert len(crowd) == 1
        print(f"  read_reactions_filter_by_mode OK -> personal: 2, crowd: 1")
    finally:
        log.unlink(missing_ok=True)


def test_reaction_summary_aggregation() -> None:
    """Summary aggregiert tags, persons, modes, tracks."""
    log = _temp_log()
    try:
        log_reaction("g", track_name="Track A", log_path=log)
        log_reaction("g", track_name="Track A", log_path=log)
        log_reaction("k", track_name="Track A", log_path=log)
        log_reaction("g", track_name="Track B", log_path=log)
        log_reaction("a", track_name="Track C", log_path=log)
        s = reaction_summary(log_path=log)
        assert s["total_entries"] == 5
        assert s["tag_counts"]["g"] == 3
        assert s["tag_counts"]["k"] == 1
        assert s["tag_counts"]["a"] == 1
        # Top track sollte Track A sein (3 reactions)
        top = s["top_tracks_by_reactions"]
        assert top[0]["track"] == "Track A"
        assert top[0]["total_reactions"] == 3
        assert top[0]["tag_breakdown"]["g"] == 2
        print(f"  reaction_summary_aggregation OK -> Track A top mit 3 Reactions, davon 2× Gänsehaut")
    finally:
        log.unlink(missing_ok=True)


def test_reaction_summary_empty_log() -> None:
    """Leeres Log liefert leere Summary, kein Crash."""
    log = _temp_log()
    s = reaction_summary(log_path=log)
    assert s["total_entries"] == 0
    assert s["tag_counts"] == {}
    print(f"  reaction_summary_empty OK")


def test_list_known_tags() -> None:
    tags = list_known_tags()
    personal_ids = {t["tag"] for t in tags["personal"]}
    crowd_ids = {t["tag"] for t in tags["crowd"]}
    assert personal_ids == PERSONAL_TAGS
    assert crowd_ids == CROWD_TAGS
    assert "log_path" in tags
    print(f"  list_known_tags OK -> personal: {len(personal_ids)}, crowd: {len(crowd_ids)}")


def test_jsonl_corruption_robustness() -> None:
    """Eine kaputte Zeile darf den Reader nicht abschießen."""
    log = _temp_log()
    try:
        log_reaction("g", log_path=log)
        # Kaputte Zeile manuell anhängen
        with open(log, "a", encoding="utf-8") as f:
            f.write("THIS IS NOT JSON\n")
        log_reaction("k", log_path=log)
        entries = read_reactions(log_path=log)
        assert len(entries) == 2  # Kaputte Zeile geskipped
        print(f"  jsonl_corruption_robustness OK -> kaputte Zeile geskipped, 2 valide gelesen")
    finally:
        log.unlink(missing_ok=True)


# ---------- Runner ----------

ALL_TESTS = [
    test_log_personal_tag,
    test_log_crowd_tag,
    test_log_unknown_tag_accepted,
    test_log_with_daw_snapshot,
    test_read_reactions_filter_by_person,
    test_read_reactions_filter_by_mode,
    test_reaction_summary_aggregation,
    test_reaction_summary_empty_log,
    test_list_known_tags,
    test_jsonl_corruption_robustness,
]


def main() -> int:
    print(f"Running {len(ALL_TESTS)} reaction-logger selftests...\n")
    failures = []
    for t in ALL_TESTS:
        try:
            t()
        except AssertionError as e:
            print(f"  [FAIL] {t.__name__}: {e}")
            failures.append(t.__name__)
        except Exception as e:
            print(f"  [ERROR] {t.__name__}: {type(e).__name__}: {e}")
            failures.append(t.__name__)
    print()
    if failures:
        print(f"[FAIL] {len(failures)}/{len(ALL_TESTS)}: {failures}")
        return 1
    print(f"[OK] alle Reaction-Logger-Selftests bestanden ({len(ALL_TESTS)}/{len(ALL_TESTS)}).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
