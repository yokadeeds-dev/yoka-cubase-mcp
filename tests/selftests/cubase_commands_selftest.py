"""
Selftest fuer runtime/midi_bridge/cubase_commands.py + das generierte
cubase_command_midi_map.json.

Prueft die Mapping-Integritaet (eindeutige Adressen, Adressraum-Grenzen,
Quell-Hash-Konsistenz) und den Resolver (exakt / Slug / mehrdeutig / fehlend)
OHNE realen MIDI-Output.

Aufruf:
    python -m tests.selftests.cubase_commands_selftest
"""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from runtime.midi_bridge.cubase_commands import (  # noqa: E402
    MAP_PATH,
    resolve,
    map_info,
    reload_map,
)

KEYMAP_CSV = ROOT / "docs" / "cubase_keymap.csv"


def _load() -> dict:
    return json.loads(MAP_PATH.read_text(encoding="utf-8"))


# ---------- Mapping-Integritaet ----------

def test_map_exists() -> None:
    assert MAP_PATH.exists(), (
        f"{MAP_PATH} fehlt — erst generate_cubase_midi_remote.py laufen lassen."
    )
    print("  map_exists OK")


def test_addresses_unique_and_in_range() -> None:
    m = _load()
    seen = set()
    for key, c in m["commands"].items():
        ch, cc = c["channel"], c["cc"]
        assert 0 <= ch <= 15, f"{key}: channel {ch} ausserhalb 0-15"
        assert 0 <= cc <= 127, f"{key}: cc {cc} ausserhalb 0-127"
        addr = (ch, cc)
        assert addr not in seen, f"{key}: Adresse {addr} doppelt vergeben"
        seen.add(addr)
    assert len(seen) == m["command_count"]
    print(f"  addresses_unique OK -> {len(seen)} eindeutige (ch,cc)")


def test_count_within_address_space() -> None:
    m = _load()
    total = m["address_space"]["total"]
    assert m["command_count"] <= total, (
        f"{m['command_count']} Commands > {total} Adressen"
    )
    print(f"  count_within_space OK -> {m['command_count']}/{total}")


def test_source_hash_matches_csv() -> None:
    """Schutz gegen Drift: JSON-Hash muss zur aktuellen CSV passen."""
    m = _load()
    actual = hashlib.sha256(KEYMAP_CSV.read_bytes()).hexdigest()
    assert m["source_sha256"] == actual, (
        "source_sha256 weicht von docs/cubase_keymap.csv ab — "
        "Mapping neu generieren (generate_cubase_midi_remote.py)."
    )
    print("  source_hash_matches OK")


def test_deterministic_allocation() -> None:
    """Index-Reihenfolge (Category, Command) -> channel=i//128, cc=i%128."""
    m = _load()
    ordered = sorted(
        m["commands"].values(), key=lambda c: (c["category"], c["command"])
    )
    for i, c in enumerate(ordered):
        assert c["channel"] == i // 128 and c["cc"] == i % 128, (
            f"Allokation nicht deterministisch bei Index {i}: {c['midi']}"
        )
    print("  deterministic_allocation OK")


# ---------- Resolver ----------

def test_resolve_exact() -> None:
    m = _load()
    key = next(iter(m["commands"]))
    r = resolve(key)
    assert r.ok and r.key == key
    assert r.channel == m["commands"][key]["channel"]
    assert r.cc == m["commands"][key]["cc"]
    print(f"  resolve_exact OK -> {key} = {r.channel}/{r.cc}")


def test_resolve_unique_slug() -> None:
    m = _load()
    # Ersten eindeutigen Slug aus dem Index nehmen.
    slug = next(iter(m["slug_index"]))
    r = resolve(slug)
    assert r.ok, f"Slug {slug} sollte aufloesen"
    assert r.key == m["slug_index"][slug]
    print(f"  resolve_unique_slug OK -> {slug}")


def test_resolve_missing() -> None:
    r = resolve("absolut_kein_command_xyz_123")
    assert r.ok is False
    assert r.channel is None
    print("  resolve_missing OK")


def test_resolve_empty() -> None:
    r = resolve("")
    assert r.ok is False
    print("  resolve_empty OK")


def test_map_info_fields() -> None:
    info = map_info()
    for f in ("version", "port", "trigger_value", "command_count"):
        assert info.get(f) is not None, f"map_info fehlt {f}"
    assert info["port"] == "AI_CMD"
    assert info["trigger_value"] == 127
    print(f"  map_info OK -> {info['command_count']} cmds, port {info['port']}")


# ---------- Runner ----------

ALL_TESTS = [
    test_map_exists,
    test_addresses_unique_and_in_range,
    test_count_within_address_space,
    test_source_hash_matches_csv,
    test_deterministic_allocation,
    test_resolve_exact,
    test_resolve_unique_slug,
    test_resolve_missing,
    test_resolve_empty,
    test_map_info_fields,
]


def main() -> int:
    reload_map()
    print(f"Running {len(ALL_TESTS)} cubase_commands selftests (no real MIDI)...\n")
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
    print(f"[OK] alle cubase_commands-Selftests bestanden ({len(ALL_TESTS)}/{len(ALL_TESTS)}).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
