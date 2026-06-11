"""
Selftest für runtime/persona/freq_advisor.py — Sprint B.

Aufruf:
    python -m tests.selftests.freq_advisor_selftest
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from runtime.persona.freq_advisor import (  # noqa: E402
    find_masking_conflicts,
    get_freq_advice,
    list_frequency_bands,
    list_track_roles,
    reload,
)


def test_loader_loads_data() -> None:
    reload()
    bands = list_frequency_bands()
    assert "sub_bass" in bands
    assert "bass" in bands
    assert "mids" in bands
    assert "treble" in bands
    print(f"  loader_loads_data OK -> {len(bands)} Frequenz-Bänder")


def test_list_track_roles() -> None:
    roles = list_track_roles()
    role_ids = {r["role_id"] for r in roles}
    # Pflicht-Rollen müssen da sein
    for required in ("kick", "snare", "bass", "vocal_lead", "vocal_backing", "acoustic_guitar", "master_bus"):
        assert required in role_ids, f"Pflicht-Rolle {required!r} fehlt: {role_ids}"
    assert len(roles) >= 12, f"Erwartet >=12 Rollen, bekam {len(roles)}"
    print(f"  list_track_roles OK -> {len(roles)} Rollen")


def test_get_freq_advice_kick() -> None:
    """Kick: Sub @40-50Hz, Punch @60-80Hz, Click @3-5kHz; Boxiness @400Hz."""
    a = get_freq_advice("kick")
    assert a["ok"] is True
    assert a["role_id"] == "kick"
    purposes = [z["purpose"] for z in a["core_zones"]]
    assert "Sub-Fundament" in purposes
    assert "Punch" in purposes
    assert "Click / Beater" in purposes
    # Problem-Zone Boxiness
    issues = [z["issue"] for z in a["problem_zones"]]
    assert any("Boxiness" in i for i in issues)
    # Masking
    assert "bass" in a["masking_conflicts"]
    print(f"  freq_advice_kick OK -> {len(a['core_zones'])} core, {len(a['problem_zones'])} problem zones")


def test_get_freq_advice_vocal_lead() -> None:
    """Vocal Lead: Warmth, Präsenz, Air; Boxiness, Nasalität, Sibilanz als Probleme."""
    a = get_freq_advice("vocal_lead")
    assert a["ok"] is True
    purposes = [z["purpose"] for z in a["core_zones"]]
    assert any("Präsenz" in p or "Forward" in p for p in purposes)
    assert any("Air" in p for p in purposes)
    issues = [z["issue"] for z in a["problem_zones"]]
    assert any("Sibilanz" in i for i in issues)
    assert any("Nasal" in i for i in issues)
    assert a["high_pass_hz"] == 100
    print(f"  freq_advice_vocal_lead OK -> HP {a['high_pass_hz']}Hz, {len(a['core_zones'])} core, {len(a['problem_zones'])} problems")


def test_get_freq_advice_master_bus() -> None:
    """Master: subtle Eingriffe, max ±2 dB."""
    a = get_freq_advice("master_bus")
    assert a["ok"] is True
    # Air-Shelf vorhanden
    purposes = [z["purpose"] for z in a["core_zones"]]
    assert any("Air" in p for p in purposes)
    # Notes erwähnt subtle
    assert "subtle" in (a.get("notes") or "").lower()
    print(f"  freq_advice_master OK -> Master-Bus mit subtle-Hinweis")


def test_get_freq_advice_unknown_role_returns_alternatives() -> None:
    a = get_freq_advice("unicorn_drum")
    assert a["ok"] is False
    assert "available_roles" in a
    assert "kick" in a["available_roles"]
    print(f"  freq_advice_unknown OK -> {len(a['available_roles'])} Rollen als Alternative")


def test_global_rules_present() -> None:
    """Critical-Listening-Rules + Sweep-Technique sind Teil jeder Antwort."""
    a = get_freq_advice("kick")
    rules = a.get("global_rules", {})
    assert "solo_vs_context" in rules
    assert rules["solo_vs_context"]
    assert "fletcher_munson_warning" in rules
    sweep = a.get("sweep_technique")
    assert sweep
    assert "step_1" in sweep
    print(f"  global_rules_present OK -> Solo/Context + Fletcher-Munson + Sweep im Output")


def test_masking_conflicts_kick_bass() -> None:
    """Kick und Bass sind klassische Masking-Partner — bidirektional erkannt."""
    k = find_masking_conflicts("kick")
    b = find_masking_conflicts("bass")
    assert k["ok"] is True
    assert b["ok"] is True
    assert "bass" in k["conflicts_with"]
    assert "kick" in b["conflicts_with"]
    # Resolution-Strategien sind angehängt
    assert "complementary_eq" in k["resolution_strategies"]
    assert "frequency_niche" in k["resolution_strategies"]
    print(f"  masking_conflicts_kick_bass OK -> bidirektional + 4 Resolution-Strategien")


def test_complementary_eq_hint_for_backing_vocal() -> None:
    """Backing-Vocal hat complementary_eq_hint zu Lead-Vocal."""
    a = get_freq_advice("vocal_backing")
    hint = a.get("complementary_eq_hint")
    assert hint
    assert "Lead" in hint
    print(f"  complementary_eq_hint OK -> Backing-Vocal kennt Lead-Beziehung")


def test_807_sub_mono_warning() -> None:
    """808/Sub-Bass hat Mono-Pflicht-Notiz."""
    a = get_freq_advice("808_sub")
    assert a["ok"] is True
    notes = a.get("notes", "")
    assert "Mono" in notes
    print(f"  808_sub_mono_warning OK -> Mono-Pflicht im Notes-Feld")


# ---------- Runner ----------

ALL_TESTS = [
    test_loader_loads_data,
    test_list_track_roles,
    test_get_freq_advice_kick,
    test_get_freq_advice_vocal_lead,
    test_get_freq_advice_master_bus,
    test_get_freq_advice_unknown_role_returns_alternatives,
    test_global_rules_present,
    test_masking_conflicts_kick_bass,
    test_complementary_eq_hint_for_backing_vocal,
    test_807_sub_mono_warning,
]


def main() -> int:
    print(f"Running {len(ALL_TESTS)} freq-advisor selftests...\n")
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
    print(f"[OK] alle Freq-Advisor-Selftests bestanden ({len(ALL_TESTS)}/{len(ALL_TESTS)}).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
