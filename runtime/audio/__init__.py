"""Audio-Playback und -Utilities für KI-Studio.

play_audio_file() ist die zentrale Funktion für blocking/non-blocking Audio-Wiedergabe.
Cross-platform: Mac (afplay), Win (winsound/PowerShell MediaPlayer), Linux (paplay/mpg123).

Eingeführt 2026-05-21 als Quick-Win 2 nach Mureka-Lessons-ADR — analog zu
mureka_mcp.api.play_audio, aber cross-platform und ohne externe Dependencies (nur stdlib).
"""

from runtime.audio.playback import AudioPlaybackError, play_audio_file

__all__ = ["AudioPlaybackError", "play_audio_file"]
