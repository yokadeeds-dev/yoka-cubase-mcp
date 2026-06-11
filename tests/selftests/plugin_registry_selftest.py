"""Selftest fuer runtime/persona/plugin_registry.py.

Testet:
- Join yoka_plugins.json + plugin_tags.json
- Lookup-Logik (Free-Text, Filter, Kombinationen)
- License-Filter (Antares Demo-expired)
- get_plugin_details (exact-match)
- list_untagged (Coverage-Inspektion)
- registry_stats

Aufruf:
    python -m tests.selftests.plugin_registry_selftest
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from runtime.persona.plugin_registry import (  # noqa: E402
    get_plugin_details,
    list_untagged,
    lookup_plugin,
    registry_stats,
    reload,
)


# ---------- Join + Stats ----------

def test_stats_basic() -> None:
    reload()
    stats = registry_stats()
    assert stats["total_plugins_in_inventory"] > 100, "Inventar sollte >100 Plugins haben"
    assert stats["tagged"] > 30, "Mindestens 30 Plugins sollten getagged sein"
    assert stats["with_cc_mapping"] == 3, "Erwartet 3 CC-mapped Plugins (Pro-Q3, Pro-C 2, Saturn 2)"
    assert "demo_expired" in stats["by_license_status"]
    print(f"  stats_basic OK -> {stats['tagged']} tagged / {stats['total_plugins_in_inventory']} total")


def test_get_plugin_details_known() -> None:
    d = get_plugin_details("FabFilter Pro-Q 3")
    assert d is not None
    assert d["vendor"] == "FabFilter"
    assert d["tagged"] is True
    assert d["cc_mapping"] == "fabfilter_pro_q3"
    assert "corrective_eq" in d["use_cases"]
    print("  get_plugin_details_known OK -> FabFilter Pro-Q 3 voll-aufgeloest")


def test_get_plugin_details_unknown() -> None:
    d = get_plugin_details("NoSuchPluginEverInstalled")
    assert d is None
    print("  get_plugin_details_unknown OK -> None")


def test_get_plugin_details_untagged() -> None:
    """Ein Plugin im Roh-Inventar das nicht getagged ist (z. B. IEM-Suite)."""
    d = get_plugin_details("ValhallaDelay")
    assert d is not None
    assert d["tagged"] is False
    assert d["tags"] == []
    assert d["license_status"] == "unknown"
    assert d["ki_role"] == "untagged"
    print("  get_plugin_details_untagged OK -> ValhallaDelay als untagged sichtbar")


# ---------- Lookup ----------

def test_lookup_query_free_text() -> None:
    r = lookup_plugin(query="bass compressor warm", limit=10)
    assert r.total_matches > 0
    # Pro-C 2 sollte unter den Top sein (matches "compressor" via tags)
    names = [m["name"] for m in r.matches]
    assert "FabFilter Pro-C 2" in names
    print(f"  lookup_query_free_text OK -> {r.total_matches} matches, Pro-C 2 dabei")


def test_lookup_use_case_filter() -> None:
    r = lookup_plugin(use_case="bass_glue", limit=10)
    assert r.total_matches >= 1
    names = [m["name"] for m in r.matches]
    assert "FabFilter Pro-C 2" in names
    print(f"  lookup_use_case_filter OK -> {r.total_matches} 'bass_glue' matches")


def test_lookup_sound_tag_filter() -> None:
    r = lookup_plugin(sound_tag="vintage", limit=10)
    assert r.total_matches >= 3, f"erwartet >=3 vintage tags, got {r.total_matches}"
    print(f"  lookup_sound_tag_filter OK -> {r.total_matches} 'vintage' matches")


def test_lookup_with_cc_mapping_only() -> None:
    r = lookup_plugin(with_cc_mapping_only=True, limit=10)
    assert r.total_matches == 3
    names = sorted(m["name"] for m in r.matches)
    assert names == ["FabFilter Pro-C 2", "FabFilter Pro-Q 3", "FabFilter Saturn 2"]
    print(f"  lookup_with_cc_mapping_only OK -> exakt die 3 erwarteten Plugins")


def test_lookup_combo_filter() -> None:
    """Kombination: category + sound_tag."""
    r = lookup_plugin(category="Reverb", sound_tag="vintage", limit=10)
    assert r.total_matches >= 1
    # Mindestens ValhallaVintageVerb
    names = [m["name"] for m in r.matches]
    assert "ValhallaVintageVerb" in names
    print(f"  lookup_combo_filter OK -> Reverb+vintage: {r.total_matches} matches inkl. ValhallaVintageVerb")


# ---------- License-Filter ----------

def test_license_filter_blocks_antares() -> None:
    """Antares-Suite ist demo_expired und sollte rausgefiltert werden."""
    with_filter = lookup_plugin(manufacturer="Antares", license_active_only=True, limit=50)
    without_filter = lookup_plugin(manufacturer="Antares", license_active_only=False, limit=50)
    assert without_filter.total_matches > with_filter.total_matches, "Filter sollte Antares-Plugins reduzieren"
    print(f"  license_filter_blocks_antares OK -> {without_filter.total_matches} ohne / {with_filter.total_matches} mit Filter")


# ---------- Untagged ----------

def test_list_untagged_has_content() -> None:
    untagged = list_untagged(limit=5)
    assert len(untagged) == 5
    for u in untagged:
        assert "name" in u
        assert "vendor" in u
    print(f"  list_untagged_has_content OK -> {len(untagged)} untagged sample")


# ---------- Runner ----------

ALL_TESTS = [
    test_stats_basic,
    test_get_plugin_details_known,
    test_get_plugin_details_unknown,
    test_get_plugin_details_untagged,
    test_lookup_query_free_text,
    test_lookup_use_case_filter,
    test_lookup_sound_tag_filter,
    test_lookup_with_cc_mapping_only,
    test_lookup_combo_filter,
    test_license_filter_blocks_antares,
    test_list_untagged_has_content,
]


def main() -> int:
    print(f"Running {len(ALL_TESTS)} plugin-registry selftests...\n")
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
    print(f"[OK] alle plugin-registry-Selftests bestanden ({len(ALL_TESTS)}/{len(ALL_TESTS)}).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
