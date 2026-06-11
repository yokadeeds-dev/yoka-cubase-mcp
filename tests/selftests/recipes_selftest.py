"""
Selftest für runtime/persona/recipes.py — Sprint D.

Aufruf:
    python -m tests.selftests.recipes_selftest
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from runtime.persona.recipes import (  # noqa: E402
    find_recipes_by_keyword,
    get_recipe,
    list_categories,
    list_recipes,
    plan_recipe,
    reload,
)


def test_loader_loads_data() -> None:
    reload()
    cats = list_categories()
    cat_ids = {c["category_id"] for c in cats}
    for required in ("session_init", "routine_eq", "cleanup", "pre_processing"):
        assert required in cat_ids, f"Pflicht-Kategorie {required!r} fehlt"
    print(f"  loader_loads_data OK -> {len(cats)} Kategorien")


def test_pre_processing_recipes_exist() -> None:
    """Die 4 Pre-Processing-Rezepte (RX/Melodyne fuer Vocal+Guitar) sind da."""
    recipes = list_recipes(category="pre_processing")
    rec_ids = {r["recipe_id"] for r in recipes}
    for required in (
        "pre_process_vocal_rx_chain",
        "pre_process_guitar_rx_chain",
        "pre_process_vocal_melodyne",
        "pre_process_guitar_melodyne",
    ):
        assert required in rec_ids, f"Pre-Processing-Rezept {required!r} fehlt: {rec_ids}"
    print(f"  pre_processing_recipes_exist OK -> {len(recipes)} Pre-Processing-Rezepte")


def test_melodyne_recipe_has_yoka_2012_note() -> None:
    """Melodyne-Recipe muss Yoka-2012->2026-Update-Hinweis haben (er hat 2012 zuletzt benutzt)."""
    r = get_recipe("pre_process_vocal_melodyne")
    assert r["ok"] is True
    notes = r.get("yoka_notes", "") or ""
    assert "2012" in notes, "Melodyne-Recipe muss Yoka-2012-Hinweis enthalten"
    assert "ARA" in notes, "ARA-Hinweis (statt VST3) muss da sein"
    # F-Moll ist Default fuer aktuelles Projekt
    assert r["params_schema"]["key_root"]["default"] == "F"
    assert r["params_schema"]["scale_type"]["default"] == "minor"
    print(f"  melodyne_recipe_has_yoka_2012_note OK -> 2012-Update + ARA + F-minor default")


def test_rx_chain_order_critical() -> None:
    """RX-Chain hat fixe Reihenfolge: Mouth-Declick -> De-Plosive -> Voice-Denoise -> De-Ess."""
    r = get_recipe("pre_process_vocal_rx_chain")
    assert r["ok"] is True
    steps = r["steps"]
    # Reihenfolge der RX-Module-Loads
    rx_loads = [s for s in steps if s.get("tool") == "load_instrument_or_effect"]
    queries = [s["args"].get("name_query", "") for s in rx_loads]
    # Mouth-Declick muss VOR De-Plosive sein, beide vor Voice-Denoise, vor De-Ess
    expected_order = ["Mouth De-click", "De-plosive", "Voice De-noise", "De-ess"]
    indices = []
    for needle in expected_order:
        found = next((i for i, q in enumerate(queries) if needle in q), -1)
        assert found >= 0, f"RX-Modul {needle!r} fehlt in Chain"
        indices.append(found)
    assert indices == sorted(indices), f"RX-Chain-Reihenfolge falsch: {queries}"
    print(f"  rx_chain_order_critical OK -> Reihenfolge {expected_order}")


def test_list_recipes_no_filter() -> None:
    recipes = list_recipes()
    rec_ids = {r["recipe_id"] for r in recipes}
    for required in (
        "sidechain_kick_to_bass",
        "load_kick_kick3",
        "eq_kick_default",
        "eq_vocal_lead_default",
    ):
        assert required in rec_ids, f"Pflicht-Rezept {required!r} fehlt: {rec_ids}"
    assert len(recipes) >= 8, f"Erwartet >=8 Rezepte, bekam {len(recipes)}"
    print(f"  list_recipes OK -> {len(recipes)} Rezepte")


def test_list_recipes_filter_session_init() -> None:
    recipes = list_recipes(category="session_init")
    assert all(r["category"] == "session_init" for r in recipes)
    assert len(recipes) >= 3, f"Erwartet >=3 Session-Init Rezepte, bekam {len(recipes)}"
    print(f"  list_recipes_filter OK -> {len(recipes)} session_init Rezepte")


def test_get_recipe_kick_kick3() -> None:
    """KICK 3 ist Yokas Default — VST-Query muss 'KICK 3' sein."""
    r = get_recipe("load_kick_kick3")
    assert r["ok"] is True
    assert r["recipe_id"] == "load_kick_kick3"
    schema = r["params_schema"]
    assert schema["vst_query"]["default"] == "KICK 3"
    # Yoka-Note muss KICK 3 erwähnen
    notes = r.get("yoka_notes", "")
    assert "KICK 3" in notes
    print(f"  get_recipe_kick_kick3 OK -> Default-VST 'KICK 3', {len(r['steps'])} Steps")


def test_get_recipe_bass_layered_is_wip() -> None:
    """Bass-Layering muss als WIP markiert sein — Yoka noch in Findung."""
    r = get_recipe("load_bass_layered_wip")
    assert r["ok"] is True
    assert "WIP" in r["display_name"]
    notes = r.get("yoka_notes", "") or ""
    assert "WIP" in notes or "wip" in notes.lower()
    # Drei Layer-Synth-Slots
    schema = r["params_schema"]
    assert "sub_layer_synth" in schema
    assert "mid_layer_synth" in schema
    assert "definition_layer_synth" in schema
    print(f"  bass_layered_is_wip OK -> WIP-markiert, 3 Layer-Slots")


def test_get_recipe_unknown_returns_alternatives() -> None:
    r = get_recipe("dance_with_yourself")
    assert r["ok"] is False
    assert "available_recipes" in r
    assert "sidechain_kick_to_bass" in r["available_recipes"]
    print(f"  unknown_recipe OK -> {len(r['available_recipes'])} Alternativen")


def test_plan_recipe_with_defaults() -> None:
    """Plan ohne Overrides nutzt alle Default-Werte."""
    p = plan_recipe("sidechain_kick_to_bass")
    assert p["ok"] is True
    params = p["resolved_params"]
    assert params["ratio"] == 4.0  # default
    assert params["attack_ms"] == 1.0
    assert params["release_ms"] == 100.0
    # Steps müssen aufgelöste Werte haben (kein _param_ref übrig)
    for step in p["steps"]:
        for k in step["args"]:
            assert not k.endswith("_param_ref"), f"Unresolved ref in step {step}"
    # Step-Count plausibel
    assert p["step_count"] >= 5
    print(f"  plan_with_defaults OK -> {p['step_count']} Steps, ratio={params['ratio']}")


def test_plan_recipe_with_override() -> None:
    """Override für Ratio wird übernommen, andere Defaults bleiben."""
    p = plan_recipe("sidechain_kick_to_bass", overrides={"ratio": 6.5})
    assert p["ok"] is True
    assert p["resolved_params"]["ratio"] == 6.5
    assert p["resolved_params"]["attack_ms"] == 1.0  # default
    # In Steps muss 6.5 als value auftauchen
    ratios_in_steps = [
        step["args"].get("value")
        for step in p["steps"]
        if step["args"].get("param") == "Ratio"
    ]
    assert 6.5 in ratios_in_steps
    print(f"  plan_with_override OK -> ratio=6.5 propagiert in Steps")


def test_plan_recipe_override_out_of_range_fails() -> None:
    """Ratio=999 (außerhalb [1.5, 10.0]) muss als Validation-Error scheitern."""
    p = plan_recipe("sidechain_kick_to_bass", overrides={"ratio": 999.0})
    assert p["ok"] is False
    assert "validation_errors" in p
    assert any("999" in e or "ratio" in e.lower() for e in p["validation_errors"])
    print(f"  override_out_of_range OK -> Validation-Error: {p['validation_errors'][0]}")


def test_plan_recipe_unknown_param_fails() -> None:
    """Unbekannter Override-Key -> Validation-Error."""
    p = plan_recipe("sidechain_kick_to_bass", overrides={"unicorn_param": 1.0})
    assert p["ok"] is False
    assert "validation_errors" in p
    assert any("unicorn_param" in e for e in p["validation_errors"])
    print(f"  unknown_param OK -> Validation-Error für unbekannten Key")


def test_plan_recipe_daw_filter_ableton() -> None:
    """DAW-Filter 'ableton' filtert daw-spezifische Steps korrekt."""
    p = plan_recipe("load_kick_kick3", daw="ableton")
    assert p["ok"] is True
    assert p["daw_filter"] == "ableton"
    # Keine cubase-only Steps
    for step in p["steps"]:
        assert step.get("daw") in (None, "ableton")
    print(f"  daw_filter_ableton OK -> {p['step_count']} Steps")


def test_plan_recipe_unknown_daw_warning() -> None:
    """Unbekanntes DAW (z. B. 'pro_tools') -> Warning, aber ok=True."""
    p = plan_recipe("sidechain_kick_to_bass", daw="pro_tools")
    assert p["ok"] is True
    assert len(p["warnings"]) >= 1
    assert any("pro_tools" in w for w in p["warnings"])
    print(f"  unknown_daw_warning OK -> Warning: {p['warnings'][0][:60]}...")


def test_plan_recipe_if_param_skip() -> None:
    """include_definition_layer=False muss Definition-Layer-Steps skippen."""
    p = plan_recipe(
        "load_bass_layered_wip",
        overrides={"include_definition_layer": False},
    )
    assert p["ok"] is True
    # Steps mit "Bass-Def" / Definition-Layer dürfen NICHT auftauchen
    for step in p["steps"]:
        args = step["args"]
        track_name = args.get("name", "")
        assert "Bass-Def" not in track_name, f"Definition-Layer-Step nicht geskippt: {step}"
    print(f"  if_param_skip OK -> Definition-Layer korrekt geskippt ({p['step_count']} Steps)")


def test_find_recipes_by_keyword_sidechain() -> None:
    matches = find_recipes_by_keyword("sidechain")
    ids = {m["recipe_id"] for m in matches}
    assert "sidechain_kick_to_bass" in ids
    assert "sidechain_kick_to_pad" in ids
    print(f"  find_by_keyword OK -> {len(matches)} Treffer für 'sidechain'")


def test_find_recipes_by_keyword_kick() -> None:
    """'kick' findet Kick-Lade-Rezept + Sidechain + EQ-Kick."""
    matches = find_recipes_by_keyword("kick")
    ids = {m["recipe_id"] for m in matches}
    assert "load_kick_kick3" in ids
    assert "eq_kick_default" in ids
    assert len(matches) >= 3
    print(f"  find_by_keyword_kick OK -> {len(matches)} Treffer")


# ---------- Runner ----------

ALL_TESTS = [
    test_loader_loads_data,
    test_pre_processing_recipes_exist,
    test_melodyne_recipe_has_yoka_2012_note,
    test_rx_chain_order_critical,
    test_list_recipes_no_filter,
    test_list_recipes_filter_session_init,
    test_get_recipe_kick_kick3,
    test_get_recipe_bass_layered_is_wip,
    test_get_recipe_unknown_returns_alternatives,
    test_plan_recipe_with_defaults,
    test_plan_recipe_with_override,
    test_plan_recipe_override_out_of_range_fails,
    test_plan_recipe_unknown_param_fails,
    test_plan_recipe_daw_filter_ableton,
    test_plan_recipe_unknown_daw_warning,
    test_plan_recipe_if_param_skip,
    test_find_recipes_by_keyword_sidechain,
    test_find_recipes_by_keyword_kick,
]


def main() -> int:
    print(f"Running {len(ALL_TESTS)} recipe-planner selftests...\n")
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
    print(f"[OK] alle Recipe-Planner-Selftests bestanden ({len(ALL_TESTS)}/{len(ALL_TESTS)}).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
