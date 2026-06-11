"""DAWproject-Writer fuer KI-Studio (Spike 2026-05-21, Markt-Scan-Pattern #3).

DAWproject ist ein offenes XML-basiertes Austauschformat fuer DAW-Sessions
(initiiert von Bitwig + PreSonus 2024, nativ unterstuetzt in Cubase 14+,
Bitwig Studio 5+, Studio One 6.5+).

Strategischer Wert fuer KI-Studio: **das fehlende Glied** zwischen
"LLM generiert Komposition" und "DAW laedt die Session" (Layer-8-Vision
"Suno fuer DAW"). Statt MIDI-Files importieren + Plugins manuell setzen,
generiert die KI ein einziges .dawproject das Cubase nativ versteht.

Architektur (dieser Spike):
- Wir nutzen die externe Lib `dawproject` (roex-audio/dawproject-py)
- Eigener thin-Wrapper `compose.py` mit KI-Studio-relevanten Helpers
- POC: minimal-Project mit 1 MIDI-Track + 1 Clip mit Noten

Aufruf:
    from runtime.dawproject.compose import build_minimal_midi_project
    build_minimal_midi_project("output.dawproject")
"""

from runtime.dawproject.compose import (
    build_minimal_midi_project,
    build_multi_track_session,
)

__all__ = ["build_minimal_midi_project", "build_multi_track_session"]
