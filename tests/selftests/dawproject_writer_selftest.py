"""Selftest fuer runtime/dawproject/compose.py — minimaler Generator-Test
+ XML-Sanity ohne echte DAW.

Aufruf:
    python -m tests.selftests.dawproject_writer_selftest
"""
from __future__ import annotations

import sys
import tempfile
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from runtime.dawproject.compose import (  # noqa: E402
    MidiNote,
    TrackSpec,
    build_minimal_midi_project,
    build_multi_track_session,
)


def test_minimal_project_created() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        out = build_minimal_midi_project(Path(tmp) / "test.dawproject")
        assert out.exists()
        assert out.stat().st_size > 500, "DAWproject sollte mindestens 500 bytes haben"
    print(f"  minimal_project_created OK -> File generiert (>{500} bytes)")


def test_minimal_project_is_valid_zip() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        out = build_minimal_midi_project(Path(tmp) / "test.dawproject")
        with zipfile.ZipFile(out) as z:
            names = z.namelist()
            assert "project.xml" in names, f"project.xml fehlt, got {names}"
            assert "metadata.xml" in names, f"metadata.xml fehlt, got {names}"
    print("  minimal_project_is_valid_zip OK -> project.xml + metadata.xml im ZIP")


def test_minimal_project_xml_structure() -> None:
    """project.xml hat erwartete XML-Elemente."""
    with tempfile.TemporaryDirectory() as tmp:
        out = build_minimal_midi_project(Path(tmp) / "test.dawproject")
        with zipfile.ZipFile(out) as z:
            xml = z.read("project.xml").decode("utf-8")
    # Wesentliche Elemente
    assert "<Project version=\"1.0\">" in xml
    assert "<Application name=\"KI-Studio-Mackie\"" in xml
    assert "<Track " in xml
    assert "<Arrangement" in xml
    assert "<Lanes " in xml
    assert "<Clips " in xml
    assert "<Notes " in xml
    # Mindestens 8 Notes (C-Dur-Tonleiter)
    assert xml.count("<Note ") == 8, f"erwartet 8 Noten, got {xml.count('<Note ')}"
    print(f"  minimal_project_xml_structure OK -> 8 Noten + alle Container-Elemente korrekt")


def test_multi_track_session() -> None:
    """Mehrere Tracks (Bass + Drums + Synth) in einer Session."""
    bass = TrackSpec(
        name="Bass",
        notes=[
            MidiNote(time=0.0, duration=0.5, pitch=36),  # C2
            MidiNote(time=1.0, duration=0.5, pitch=38),  # D2
            MidiNote(time=2.0, duration=0.5, pitch=41),  # F2
            MidiNote(time=3.0, duration=0.5, pitch=43),  # G2
        ],
        clip_duration=4.0,
        volume=0.85,
    )
    drums = TrackSpec(
        name="Drums",
        notes=[
            MidiNote(time=i * 0.5, duration=0.1, pitch=36 if i % 2 == 0 else 38, velocity=0.9)
            for i in range(8)
        ],
        clip_duration=4.0,
        volume=0.9,
    )
    synth = TrackSpec(
        name="Synth Pad",
        notes=[MidiNote(time=0.0, duration=4.0, pitch=60, velocity=0.5)],
        clip_duration=4.0,
        volume=0.6,
    )

    with tempfile.TemporaryDirectory() as tmp:
        out = build_multi_track_session(
            Path(tmp) / "trip_hop.dawproject",
            tracks=[bass, drums, synth],
            title="Trip-Hop POC",
        )
        with zipfile.ZipFile(out) as z:
            xml = z.read("project.xml").decode("utf-8")
        assert xml.count('<Track ') == 3, f"erwartet 3 Tracks, got {xml.count('<Track ')}"
        assert "Bass" in xml
        assert "Drums" in xml
        assert "Synth Pad" in xml
        # Bass(4) + Drums(8) + Synth(1) = 13 Notes
        assert xml.count("<Note ") == 13
    print(f"  multi_track_session OK -> 3 Tracks (Bass+Drums+Synth), 13 Notes total")


def test_empty_track_handled() -> None:
    """Track ohne Notes sollte trotzdem Datei erzeugen (kein crash)."""
    empty = TrackSpec(name="Leer", notes=[], clip_duration=2.0)
    with tempfile.TemporaryDirectory() as tmp:
        out = build_multi_track_session(
            Path(tmp) / "empty.dawproject",
            tracks=[empty],
        )
        assert out.exists()
    print("  empty_track_handled OK")


ALL_TESTS = [
    test_minimal_project_created,
    test_minimal_project_is_valid_zip,
    test_minimal_project_xml_structure,
    test_multi_track_session,
    test_empty_track_handled,
]


def main() -> int:
    print(f"Running {len(ALL_TESTS)} dawproject-writer selftests...\n")
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
    print(f"[OK] alle dawproject-writer-Selftests bestanden ({len(ALL_TESTS)}/{len(ALL_TESTS)}).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
