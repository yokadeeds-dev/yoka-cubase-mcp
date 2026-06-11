"""DAWproject-Composer: high-level Helpers fuer den KI-Studio-Workflow.

Statt direkt mit der raw dawproject-Lib zu hantieren, bietet dieses Modul
KI-Studio-orientierte Builder:

- build_minimal_midi_project(...) — 1 Track + 1 Clip + N Noten (POC)
- build_multi_track_session(...)  — n Tracks mit MIDI-Content (Layer-8-Vorstufe)
- write_project(...)              — Project + MetaData -> .dawproject-File

Die hier gewaehlten Konventionen:
- Time-Unit: SECONDS (lesbarer als Beats fuer Test)
- Default Tempo: 120 BPM (kann ueberschrieben werden via Project.transport)
- MIDI-Pitch: GM-Standard (60 = C4)
- Velocity: 0..1 normalisiert (DAWproject-Konvention)
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from dawproject import (
    Application,
    Arrangement,
    Channel,
    ContentType,
    DawProject,
    Lanes,
    MetaData,
    MixerRole,
    Note,
    Notes,
    Project,
    RealParameter,
    Referenceable,
    TimeUnit,
    Track,
    Unit,
    Utility,
)


@dataclass
class MidiNote:
    """KI-Studio-freundliche Note-Spec (analog Mureka-Prompt-Schema)."""
    time: float          # Sekunden vom Track-Start
    duration: float      # Sekunden
    pitch: int           # MIDI 0..127, 60 = C4
    velocity: float = 0.8  # 0..1
    channel: int = 0


@dataclass
class TrackSpec:
    """High-Level Track-Definition fuer build_multi_track_session."""
    name: str
    notes: list[MidiNote] = field(default_factory=list)
    clip_start: float = 0.0
    clip_duration: float | None = None  # None = automatisch (letzte Note + duration)
    volume: float = 0.8     # linear 0..1
    pan: float = 0.5        # 0=L, 0.5=center, 1=R
    color: str | None = None


def build_minimal_midi_project(
    output_path: str | Path = "output.dawproject",
    project_title: str = "KI-Studio Minimal Test",
    artist: str = "KI-Studio",
) -> Path:
    """Minimal-POC: 1 Track mit 8 Noten (C-Dur-Tonleiter aufsteigend).

    Verwendet Sekunden als Time-Unit, 120 BPM implizit. Schreibt ein
    .dawproject-File und gibt den Pfad zurueck.
    """
    out = Path(output_path).resolve()

    notes = [
        MidiNote(time=i * 0.5, duration=0.4, pitch=60 + step, velocity=0.8)
        for i, step in enumerate([0, 2, 4, 5, 7, 9, 11, 12])
    ]

    track = TrackSpec(
        name="C-Dur Tonleiter",
        notes=notes,
        clip_start=0.0,
        clip_duration=4.5,
        volume=0.8,
        pan=0.5,
    )

    return _write_session(
        output_path=out,
        tracks=[track],
        title=project_title,
        artist=artist,
    )


def build_multi_track_session(
    output_path: str | Path,
    tracks: list[TrackSpec],
    title: str = "KI-Studio Multi-Track Session",
    artist: str = "KI-Studio",
) -> Path:
    """Layer-8-Vorstufe: mehrere Tracks aus KI-generierten MidiNote-Listen.

    Vor Composer-AI-Integration: User/LLM gibt Liste von TrackSpec-Objekten,
    diese Funktion baut das DAWproject zusammen.
    """
    return _write_session(
        output_path=Path(output_path).resolve(),
        tracks=tracks,
        title=title,
        artist=artist,
    )


# ----------------------------------------------------------------------
# Internal: das eigentliche Project-Building
# ----------------------------------------------------------------------

def _write_session(
    output_path: Path,
    tracks: list[TrackSpec],
    title: str,
    artist: str,
) -> Path:
    """Baut das Project-Objekt und ruft DawProject.save()."""
    Referenceable.reset_id()  # frische ID-Counter

    project = Project()
    project.application = Application(name="KI-Studio-Mackie", version="0.1.0")

    # Arrangement-Container fuer die Clips (Arrangement hat 'lanes', nicht 'content')
    arrangement_lanes = Lanes(time_unit=TimeUnit.SECONDS)
    arrangement = Arrangement(lanes=arrangement_lanes)
    project.arrangement = arrangement

    for spec in tracks:
        # Track + Channel via Utility-Factory
        track = Utility.create_track(
            name=spec.name,
            content_types={ContentType.NOTES},
            mixer_role=MixerRole.REGULAR,
            volume=spec.volume,
            pan=spec.pan,
        )
        if spec.color:
            track.color = spec.color
        project.structure.append(track)

        # Notes-Timeline + Notes
        notes_timeline = Notes(time_unit=TimeUnit.SECONDS, track=track)
        for n in spec.notes:
            notes_timeline.notes.append(
                Note(
                    time=n.time,
                    duration=n.duration,
                    key=n.pitch,
                    channel=n.channel,
                    vel=n.velocity,
                )
            )

        # Clip umschliesst die Notes-Timeline
        duration = spec.clip_duration
        if duration is None and spec.notes:
            duration = max(n.time + n.duration for n in spec.notes)
        clip = Utility.create_clip(
            content=notes_timeline,
            time=spec.clip_start,
            duration=duration or 1.0,
        )

        # Clip in Track-Lane einbetten
        from dawproject import Clips  # local import damit Modul-Header schlank bleibt
        clips_container = Clips(track=track, time_unit=TimeUnit.SECONDS)
        clips_container.clips.append(clip)
        arrangement_lanes.lanes.append(clips_container)

    # Schreiben
    metadata = MetaData(title=title, artist=artist)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    DawProject.save(project, metadata, {}, str(output_path))
    return output_path
