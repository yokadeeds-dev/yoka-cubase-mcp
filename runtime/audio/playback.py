"""Cross-platform Audio-File-Playback ohne externe Dependencies (nur Python stdlib).

Mac:    afplay (built-in, blocking)
Win:    winsound (WAV stdlib, blocking) / PowerShell MediaPlayer (MP3 mit Polling)
Linux:  paplay / aplay / mpg123 / play / ffplay (je nach Verfügbarkeit)

Design-Entscheidungen (siehe ADR 2026-05-21 — Mureka-Lessons):
- Keine zusätzlichen Python-Dependencies (anders als Mureka, das sounddevice+soundfile braucht)
- Blocking als Default (Mureka-Pattern: nach Generation/Bounce hören dann nächster Schritt)
- Non-blocking optional für Fire-and-forget-Cases (UI-Feedback während längerer Workflows)
"""
from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

SUPPORTED_FORMATS = frozenset({".wav", ".mp3", ".m4a", ".flac", ".aiff", ".ogg"})


class AudioPlaybackError(RuntimeError):
    """Wird geworfen wenn das File nicht abgespielt werden kann."""


def play_audio_file(
    path: str | Path,
    *,
    blocking: bool = True,
) -> None:
    """Spielt eine Audio-Datei ab.

    Args:
        path: Absoluter oder relativer Pfad zur Audio-Datei.
        blocking: True (default) = wartet auf Playback-Ende; False = fire-and-forget.

    Raises:
        FileNotFoundError: wenn das File nicht existiert.
        AudioPlaybackError: wenn das Format nicht unterstützt wird, kein Player verfügbar
                            ist, oder das Playback fehlschlägt.
    """
    resolved = Path(path).resolve()
    if not resolved.exists():
        raise FileNotFoundError(f"Audio file not found: {resolved}")
    if not resolved.is_file():
        raise AudioPlaybackError(f"Not a file: {resolved}")

    suffix = resolved.suffix.lower()
    if suffix not in SUPPORTED_FORMATS:
        raise AudioPlaybackError(
            f"Unsupported audio format: {suffix}. Supported: {sorted(SUPPORTED_FORMATS)}"
        )

    if sys.platform == "darwin":
        _play_mac(resolved, blocking)
    elif sys.platform == "win32":
        _play_windows(resolved, suffix, blocking)
    elif sys.platform.startswith("linux"):
        _play_linux(resolved, suffix, blocking)
    else:
        raise AudioPlaybackError(f"Unsupported platform: {sys.platform}")


def _play_mac(path: Path, blocking: bool) -> None:
    cmd = ["afplay", str(path)]
    try:
        if blocking:
            subprocess.run(cmd, check=True)
        else:
            subprocess.Popen(cmd)
    except (subprocess.CalledProcessError, FileNotFoundError) as e:
        raise AudioPlaybackError(f"afplay failed: {e}") from e


def _play_windows(path: Path, suffix: str, blocking: bool) -> None:
    # WAV blocking: winsound ist Python stdlib, robust und schnell.
    if suffix == ".wav" and blocking:
        try:
            import winsound

            winsound.PlaySound(str(path), winsound.SND_FILENAME)
            return
        except RuntimeError as e:
            raise AudioPlaybackError(f"winsound failed: {e}") from e

    # Non-blocking oder non-WAV: PowerShell MediaPlayer (Foreground) / Default-App.
    if blocking:
        # PowerShell MediaPlayer mit Polling auf NaturalDuration
        ps = (
            "Add-Type -AssemblyName presentationCore; "
            "$p = New-Object System.Windows.Media.MediaPlayer; "
            f"$p.Open([uri]'{path.as_uri()}'); "
            "for ($i=0; $i -lt 50; $i++) { "
            "if ($p.NaturalDuration.HasTimeSpan) { break }; "
            "Start-Sleep -Milliseconds 100 "
            "}; "
            "if (-not $p.NaturalDuration.HasTimeSpan) { "
            "throw 'NaturalDuration not available after 5s' "
            "}; "
            "$d = [math]::Ceiling($p.NaturalDuration.TimeSpan.TotalSeconds) + 1; "
            "$p.Play(); "
            "Start-Sleep -Seconds $d; "
            "$p.Stop(); "
            "$p.Close()"
        )
        try:
            subprocess.run(
                ["powershell", "-NoProfile", "-Command", ps],
                check=True,
                capture_output=True,
                text=True,
            )
        except subprocess.CalledProcessError as e:
            raise AudioPlaybackError(
                f"PowerShell MediaPlayer failed: {e.stderr or e.stdout or e}"
            ) from e
    else:
        # Fire-and-forget: Default-App öffnet's
        subprocess.Popen(["cmd", "/c", "start", "", str(path)], shell=False)


def _play_linux(path: Path, suffix: str, blocking: bool) -> None:
    if suffix == ".wav":
        candidates = ["aplay", "paplay", "play"]
    elif suffix == ".mp3":
        candidates = ["mpg123", "mpg321", "play", "ffplay"]
    else:
        candidates = ["play", "ffplay", "paplay"]

    for player in candidates:
        player_path = shutil.which(player)
        if not player_path:
            continue
        cmd: list[str] = [player_path, str(path)]
        if player == "ffplay":
            cmd[1:1] = ["-nodisp", "-autoexit"]
        try:
            if blocking:
                subprocess.run(cmd, check=True)
            else:
                subprocess.Popen(cmd)
            return
        except subprocess.CalledProcessError as e:
            raise AudioPlaybackError(f"{player} failed: {e}") from e

    raise AudioPlaybackError(
        f"No audio player found on Linux for {suffix}. "
        f"Install one of: {candidates}"
    )
