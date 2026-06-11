"""
Sprint D — Recipe-Planner.

Lädt strukturierte One-Shot-Workflows aus knowledge/recipes.json und liefert
für jedes Rezept einen ausgeplanten Action-Plan: geordnete Liste von
(tool, args, purpose)-Tripeln, mit aufgelösten Parameter-Referenzen.

WICHTIG: Der Planner *führt nichts aus*. Er liefert nur den Plan. Die
tatsächliche Ausführung erfolgt explizit durch:
  (a) Persona-Konversation (Yoka liest den Plan, gibt go),
  (b) MCP-Tool-Dispatch in einem späteren Sprint (D2: recipe_run-Tool),
  (c) Manuelle Bedienung via Mackie/AHK (Plan als Anleitung).

Pure Funcs ohne State, gleicher Pattern wie freq_advisor.py + mastering.py.

Aufruf-Beispiel:
    plan = plan_recipe("sidechain_kick_to_bass", overrides={"ratio": 6.0})
    if plan["ok"]:
        for step in plan["steps"]:
            print(step["tool"], step["args"], step["purpose"])
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


_KNOWLEDGE_DIR = Path(__file__).resolve().parent / "knowledge"

_cache: dict[str, Any] = {}


def _load_recipes() -> dict[str, Any]:
    """Lädt recipes.json (cached)."""
    if "recipes" not in _cache:
        path = _KNOWLEDGE_DIR / "recipes.json"
        if not path.exists():
            raise FileNotFoundError(f"recipes.json fehlt: {path}")
        _cache["recipes"] = json.loads(path.read_text(encoding="utf-8"))
    return _cache["recipes"]


def reload() -> None:
    """Cache leeren — bei expliziter Edit-Aktion."""
    _cache.clear()


def list_categories() -> list[dict[str, Any]]:
    """Liste der Recipe-Kategorien mit Display-Namen + Beschreibung."""
    data = _load_recipes()
    return [
        {
            "category_id": cid,
            "display_name": cat["display_name"],
            "description": cat.get("description", ""),
        }
        for cid, cat in data.get("categories", {}).items()
    ]


def list_recipes(category: str | None = None) -> list[dict[str, Any]]:
    """
    Liste aller Rezepte (optional gefiltert nach Kategorie).
    Liefert Übersichts-Felder, nicht die vollen Steps.
    """
    data = _load_recipes()
    out = []
    for rid, recipe in data.get("recipes", {}).items():
        if category and recipe.get("category") != category:
            continue
        out.append(
            {
                "recipe_id": rid,
                "display_name": recipe.get("display_name", rid),
                "category": recipe.get("category"),
                "daw_compat": recipe.get("daw_compat", []),
                "description": recipe.get("description", ""),
                "step_count": len(recipe.get("steps", [])),
                "param_count": len(recipe.get("params_schema", {})),
            }
        )
    return out


def get_recipe(recipe_id: str) -> dict[str, Any]:
    """
    Liefert das volle Rezept inkl. Steps und Params-Schema.
    Wenn Rezept unbekannt: ok=False mit available_recipes.
    """
    data = _load_recipes()
    recipe = data.get("recipes", {}).get(recipe_id)
    if recipe is None:
        return {
            "ok": False,
            "error": f"Unbekanntes Rezept: {recipe_id!r}",
            "available_recipes": sorted(data.get("recipes", {}).keys()),
        }
    return {
        "ok": True,
        "recipe_id": recipe_id,
        **recipe,
    }


def _validate_overrides(
    overrides: dict[str, Any],
    schema: dict[str, Any],
) -> list[str]:
    """
    Prüft Override-Werte gegen params_schema.
    Liefert Liste der Validierungs-Fehler (leer wenn alles ok).
    """
    errors: list[str] = []
    for key, value in overrides.items():
        if key not in schema:
            errors.append(f"Unbekannter Parameter: {key!r}")
            continue
        spec = schema[key]
        ptype = spec.get("type")
        # Type-Check (lax — float akzeptiert int, etc.)
        if ptype == "float":
            if not isinstance(value, (int, float)):
                errors.append(f"{key!r}: erwartet float, bekam {type(value).__name__}")
                continue
            value_f = float(value)
            rng = spec.get("range")
            if rng and (value_f < rng[0] or value_f > rng[1]):
                errors.append(f"{key!r}={value_f} außerhalb {rng}")
        elif ptype == "string":
            if not isinstance(value, str):
                errors.append(f"{key!r}: erwartet string, bekam {type(value).__name__}")
        elif ptype == "boolean":
            if not isinstance(value, bool):
                errors.append(f"{key!r}: erwartet boolean, bekam {type(value).__name__}")
    return errors


def _resolve_param_ref(
    args: dict[str, Any],
    resolved_params: dict[str, Any],
) -> dict[str, Any]:
    """
    Ersetzt 'value_param_ref' / '<key>_param_ref' Felder durch tatsächliche
    Werte aus resolved_params. Mutates: nein — gibt neuen Dict zurück.

    Konvention:
      - "<base>_param_ref": "param_name" -> "<base>": resolved_params[param_name]
      - "value_param_ref": "param_name"  -> "value": resolved_params[param_name]
    """
    out: dict[str, Any] = {}
    for key, val in args.items():
        if key.endswith("_param_ref") and isinstance(val, str):
            base = key[: -len("_param_ref")]  # strip suffix
            target_key = "value" if base == "value" else base
            if val in resolved_params:
                out[target_key] = resolved_params[val]
            else:
                # Ref auf nicht-resolved Param: behalte als Marker
                out[key] = val
                out[f"_unresolved_{base}"] = True
        else:
            out[key] = val
    return out


def plan_recipe(
    recipe_id: str,
    overrides: dict[str, Any] | None = None,
    daw: str | None = None,
) -> dict[str, Any]:
    """
    Hauptfunktion: erstellt einen ausführbaren Plan aus einem Recipe.

    Args:
      recipe_id: ID aus recipes.json
      overrides: User-Werte für params_schema (z. B. {"ratio": 6.0})
      daw: optional Filter — "cubase" / "ableton" — Steps mit "daw"-Feld
           werden nur eingeschlossen wenn sie zum Ziel-DAW passen.

    Returns:
      ok=True, recipe_id, display_name, daw_filter, resolved_params,
      steps (geordnet, mit aufgelösten args), preconditions, postcheck_hints,
      warnings (z. B. wenn DAW nicht in daw_compat).

      ok=False, error, validation_errors wenn Overrides ungültig.
    """
    overrides = overrides or {}
    data = _load_recipes()
    recipe = data.get("recipes", {}).get(recipe_id)
    if recipe is None:
        return {
            "ok": False,
            "error": f"Unbekanntes Rezept: {recipe_id!r}",
            "available_recipes": sorted(data.get("recipes", {}).keys()),
        }

    schema = recipe.get("params_schema", {})

    # 1) Overrides validieren
    errors = _validate_overrides(overrides, schema)
    if errors:
        return {
            "ok": False,
            "error": "Override-Validierung fehlgeschlagen",
            "validation_errors": errors,
            "params_schema": schema,
        }

    # 2) Resolved Params: Defaults + Overrides
    resolved_params: dict[str, Any] = {}
    for key, spec in schema.items():
        if key in overrides:
            resolved_params[key] = overrides[key]
        elif "default" in spec:
            resolved_params[key] = spec["default"]
        # Sonst: Param bleibt unresolved — wird unten als Warning markiert

    # 3) DAW-Compat-Warning (nicht-fatal)
    warnings: list[str] = []
    if daw and daw not in recipe.get("daw_compat", []):
        warnings.append(
            f"DAW {daw!r} nicht in daw_compat={recipe.get('daw_compat')} — "
            f"Recipe könnte angepasst werden müssen."
        )

    # 4) Steps auflösen
    resolved_steps: list[dict[str, Any]] = []
    for idx, step in enumerate(recipe.get("steps", []), start=1):
        # DAW-spezifische Steps filtern wenn daw gesetzt
        step_daw = step.get("daw")
        if daw and step_daw and step_daw != daw:
            continue

        # if_param: bedingter Step (z. B. include_definition_layer=False -> skip)
        if_param_keys = []
        for arg_key, arg_val in step.get("args", {}).items():
            if arg_key == "if_param" and isinstance(arg_val, str):
                if_param_keys.append(arg_val)

        skip = False
        for ifk in if_param_keys:
            if not resolved_params.get(ifk, True):
                skip = True
                break
        if skip:
            continue

        # Args auflösen
        raw_args = {k: v for k, v in step.get("args", {}).items() if k != "if_param"}
        resolved_args = _resolve_param_ref(raw_args, resolved_params)

        resolved_steps.append(
            {
                "step_num": idx,
                "tool": step["tool"],
                "args": resolved_args,
                "purpose": step.get("purpose", ""),
                "daw": step_daw,
            }
        )

    return {
        "ok": True,
        "recipe_id": recipe_id,
        "display_name": recipe.get("display_name", recipe_id),
        "category": recipe.get("category"),
        "description": recipe.get("description", ""),
        "daw_filter": daw,
        "daw_compat": recipe.get("daw_compat", []),
        "preconditions": recipe.get("preconditions", []),
        "resolved_params": resolved_params,
        "params_schema": schema,
        "steps": resolved_steps,
        "step_count": len(resolved_steps),
        "postcheck_hints": recipe.get("postcheck_hints", []),
        "yoka_notes": recipe.get("yoka_notes"),
        "warnings": warnings,
        "version": data.get("version"),
        "source_doc": data.get("source_doc"),
    }


def find_recipes_by_keyword(keyword: str) -> list[dict[str, Any]]:
    """
    Sucht Rezepte deren display_name, description oder yoka_notes das Keyword
    (case-insensitive) enthalten. Hilfsfunktion für die Persona-Suche.
    """
    if not keyword or not keyword.strip():
        return []
    kw = keyword.lower().strip()
    data = _load_recipes()
    out = []
    for rid, recipe in data.get("recipes", {}).items():
        haystack = " ".join(
            [
                recipe.get("display_name", ""),
                recipe.get("description", ""),
                recipe.get("yoka_notes", "") or "",
                rid,
            ]
        ).lower()
        if kw in haystack:
            out.append(
                {
                    "recipe_id": rid,
                    "display_name": recipe.get("display_name", rid),
                    "category": recipe.get("category"),
                    "match_score": haystack.count(kw),
                }
            )
    return sorted(out, key=lambda r: -r["match_score"])
