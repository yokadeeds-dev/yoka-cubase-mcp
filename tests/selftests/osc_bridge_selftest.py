"""Selftest fuer runtime/osc/ — Schema-Matching + Translator-Logik.

Testet ohne echten OSC-Server-Loop (kein UDP-Port-Binden, kein MIDI-Send):
- Schema.find() mit Pattern-Variablen
- Translator dry_log + mackie + mcp Backends
- Edge-Cases (unbekannte Adresse, falsche Arg-Anzahl)

Aufruf:
    python -m tests.selftests.osc_bridge_selftest
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from runtime.osc.schema import default_schema  # noqa: E402
from runtime.osc.translator import OSCTranslator  # noqa: E402


# ---------- Schema-Matching ----------

def test_schema_find_with_int_variable() -> None:
    schema = default_schema()
    found = schema.find("/track/3/volume_db")
    assert found is not None
    action, extracted = found
    assert action.action_type == "mackie_set_volume_db"
    assert extracted == {"track_idx": 3}
    print("  schema_find_with_int_variable OK -> /track/3/volume_db extracts track_idx=3")


def test_schema_find_static_address() -> None:
    schema = default_schema()
    found = schema.find("/transport/play")
    assert found is not None
    action, extracted = found
    assert action.action_type == "mackie_transport_play"
    assert extracted == {}
    print("  schema_find_static_address OK -> /transport/play")


def test_schema_find_with_string_variable() -> None:
    schema = default_schema()
    found = schema.find("/mode/plugin")
    assert found is not None
    action, extracted = found
    assert action.action_type == "mackie_set_mode"
    assert extracted == {"mode_name": "plugin"}
    print("  schema_find_with_string_variable OK -> /mode/plugin")


def test_schema_find_unknown_returns_none() -> None:
    schema = default_schema()
    assert schema.find("/no/such/address") is None
    assert schema.find("/track/3/bogus") is None
    print("  schema_find_unknown_returns_none OK")


def test_schema_find_preset_address() -> None:
    schema = default_schema()
    found = schema.find("/plugin/preset/triphop_bass_default")
    assert found is not None
    action, extracted = found
    assert action.action_type == "plugin_apply_preset"
    assert extracted == {"preset_id": "triphop_bass_default"}
    print("  schema_find_preset_address OK")


def test_schema_find_preset_dry_run_address() -> None:
    schema = default_schema()
    found = schema.find("/plugin/preset/triphop_bass_default/dry_run")
    assert found is not None
    action, extracted = found
    assert action.action_type == "plugin_apply_preset_dry_run"
    print("  schema_find_preset_dry_run_address OK")


# ---------- Translator dry_log ----------

def test_translator_dry_log_static() -> None:
    t = OSCTranslator(backend="dry_log")
    r = t.handle("/transport/play")
    assert r.ok
    assert r.action_type == "mackie_transport_play"
    assert r.backend_response == {"dry_log": True}
    print("  translator_dry_log_static OK")


def test_translator_dry_log_with_args() -> None:
    t = OSCTranslator(backend="dry_log")
    r = t.handle("/track/5/volume_db", -12.5)
    assert r.ok
    assert r.extracted == {"track_idx": 5}
    assert r.args == [-12.5]
    print("  translator_dry_log_with_args OK")


def test_translator_unknown_address() -> None:
    t = OSCTranslator(backend="dry_log")
    r = t.handle("/no/such/address")
    assert not r.ok
    assert "Keine Aktion" in (r.error or "")
    print("  translator_unknown_address OK")


# ---------- Translator mcp Backend (nutzt echte plugin_control-Logik) ----------

def test_translator_mcp_preset_dry_run() -> None:
    """Triphop-Bass-Preset im dry_run-Mode ueber OSC -> mcp-Backend."""
    t = OSCTranslator(backend="mcp")
    r = t.handle("/plugin/preset/triphop_bass_default/dry_run")
    assert r.ok, f"sollte ok sein, got error={r.error}"
    assert r.backend_response is not None
    assert r.backend_response.get("dry_run") is True
    assert r.backend_response.get("preset_id") == "triphop_bass_default"
    print("  translator_mcp_preset_dry_run OK -> ueber OSC dry_run-Plan berechnet")


def test_translator_mcp_unknown_preset() -> None:
    t = OSCTranslator(backend="mcp")
    r = t.handle("/plugin/preset/no_such_preset/dry_run")
    # Translator-Result: ok=True (Schema matched), aber Preset-Result ist ok=False
    assert r.backend_response is not None
    assert not r.backend_response.get("ok")
    print("  translator_mcp_unknown_preset OK -> Preset-Fehler korrekt im response")


# ---------- Runner ----------

ALL_TESTS = [
    test_schema_find_with_int_variable,
    test_schema_find_static_address,
    test_schema_find_with_string_variable,
    test_schema_find_unknown_returns_none,
    test_schema_find_preset_address,
    test_schema_find_preset_dry_run_address,
    test_translator_dry_log_static,
    test_translator_dry_log_with_args,
    test_translator_unknown_address,
    test_translator_mcp_preset_dry_run,
    test_translator_mcp_unknown_preset,
]


def main() -> int:
    print(f"Running {len(ALL_TESTS)} osc-bridge selftests...\n")
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
    print(f"[OK] alle osc-bridge-Selftests bestanden ({len(ALL_TESTS)}/{len(ALL_TESTS)}).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
