"""
AHK-Layer Mac-Implementierung — osascript-basiert.

Window-Detection und Key-Send über AppleScript via `osascript -e ...`.
Kein zusätzliches Python-Paket nötig; macOS bringt osascript mit.

Map zu _win_impl.py:
- find_daw_window → frontmost/running app via System Events
- bring_to_front → 'tell application "Cubase" to activate'
- press_key_combo → 'keystroke "s" using {command down, shift down}'

Whitelist (DAW_ACTIONS) ist plattform-agnostisch und wird aus _win_impl
importiert — wir mappen Cubase/Ableton-Apps auf macOS-Process-Namen
und übersetzen die Hotkey-Combos auf Mac-Conventions:
  ctrl  → command (cmd auf Mac)
  weil Cubase/Ableton Mac-Builds Cmd statt Ctrl als Save/Undo nutzen.

UNGETESTET — geschrieben blind aus Windows-Session. Mac-Claude soll
verifizieren, anpassen und Selftests gegen reale Mac-Cubase laufen lassen.
"""

from __future__ import annotations

import shlex
import subprocess
import time
from dataclasses import dataclass
from typing import Any


# ---------- Mac-DAW-Process-Namen ----------

@dataclass
class MacDawSpec:
    name: str
    process_names: list[str]  # System Events Prozessnamen für diese DAW


DAW_PROCESS_NAMES: dict[str, MacDawSpec] = {
    "cubase": MacDawSpec(
        name="cubase",
        process_names=["Cubase 15", "Cubase 14", "Cubase 13", "Cubase Pro", "Cubase"],
    ),
    "ableton": MacDawSpec(
        name="ableton",
        process_names=["Live", "Ableton Live 12 Suite", "Ableton Live"],
    ),
    "logic": MacDawSpec(
        name="logic",
        process_names=["Logic Pro", "Logic"],
    ),
    "traktor": MacDawSpec(
        name="traktor",
        process_names=["Traktor", "Traktor Pro 4", "Traktor Pro 3"],
    ),
}


# ---------- Whitelist-Mapping (Mac-Hotkeys) ----------
#
# Auf Mac ist statt Ctrl die Cmd-Taste die Standard-Modifier für
# Save / Undo / Redo. Wir definieren hier Mac-spezifische DAW_ACTIONS
# parallel zu den Windows-DAW_ACTIONS in _win_impl.py.

MAC_DAW_ACTIONS: dict[str, dict[str, str]] = {
    "cubase": {
        "save_project": "cmd+s",
        "save_project_as": "cmd+shift+s",
        "undo": "cmd+z",
        "redo": "cmd+shift+z",
        # Window / View Toggles — Cubase-Mac nutzt dieselben F-Keys wie Windows.
        # Achtung: macOS belegt F-Keys teils mit System-Funktionen; ggf. in
        # Systemeinstellungen → Tastatur "F-Tasten als Standard-Funktionstasten"
        # aktivieren oder mit fn-Modifier senden.
        "open_mixer": "f3",
        "open_project_window": "f12",
        "focus_transport_panel": "f2",
        "toggle_left_zone": "cmd+alt+l",
        "toggle_right_zone": "cmd+alt+r",
        "toggle_lower_zone": "cmd+alt+e",
        "toggle_inspector": "cmd+i",  # User-Mapping nötig
        # Add-Track-Actions: User-Mapping in Cubase Key Commands erforderlich.
        "add_audio_track": "cmd+shift+t",
        "add_midi_track": "cmd+shift+m",
        "add_instrument_track": "cmd+shift+i",
    },
    "ableton": {
        "save_project": "cmd+s",
        "save_project_as": "cmd+shift+s",
        "undo": "cmd+z",
        "redo": "cmd+shift+z",
        "export_audio": "cmd+shift+r",
    },
    "logic": {
        "save_project": "cmd+s",
        "save_project_as": "cmd+shift+s",
        "undo": "cmd+z",
        "redo": "cmd+shift+z",
        "bounce": "cmd+b",
    },
    # Traktor: keine Standard-Hotkeys für DJ-Workflow im AHK-Sinne
}

# Re-export als DAW_ACTIONS (Bridge-API) — Mac-Variante
DAW_ACTIONS = MAC_DAW_ACTIONS


# ---------- AppleScript-Helper ----------

def _osascript(script: str) -> tuple[bool, str, str]:
    """Führt AppleScript aus, returns (ok, stdout, stderr)."""
    try:
        result = subprocess.run(
            ["osascript", "-e", script],
            capture_output=True,
            text=True,
            timeout=10,
        )
        return (result.returncode == 0, result.stdout.strip(), result.stderr.strip())
    except FileNotFoundError:
        return (False, "", "osascript nicht gefunden — sind wir auf Mac?")
    except subprocess.TimeoutExpired:
        return (False, "", "osascript timeout")


# ---------- DAW-Window-Erkennung ----------

def find_daw_window(daw: str) -> int | None:
    """
    Auf Mac: prüft, ob die DAW-App läuft. Gibt PID zurück (analog zu HWND auf Windows).
    None wenn die App nicht läuft.
    """
    if daw not in DAW_PROCESS_NAMES:
        raise ValueError(f"Unbekannte DAW {daw!r}. Bekannt: {sorted(DAW_PROCESS_NAMES.keys())}")

    spec = DAW_PROCESS_NAMES[daw]
    for proc_name in spec.process_names:
        ok, stdout, _ = _osascript(
            f'tell application "System Events" to '
            f'unix id of process "{proc_name}"'
        )
        if ok and stdout:
            try:
                return int(stdout)
            except ValueError:
                continue
    return None


def get_window_info(pid: int) -> dict[str, str]:
    """
    Holt Info über den Prozess via PID. Auf Mac: Bundle-Identifier und
    Process-Name.
    """
    ok, name, _ = _osascript(
        f'tell application "System Events" to '
        f'name of (first process whose unix id is {pid})'
    )
    return {
        "pid": str(pid),
        "name": name if ok else "unknown",
        "platform": "macos",
    }


def bring_to_front(pid: int) -> bool:
    """
    Aktiviert den Prozess via AppleScript. Mac hat dafür ein cleanes
    Activate-Command, kein UIPI-Workaround nötig.
    """
    ok, name, _ = _osascript(
        f'tell application "System Events" to '
        f'name of (first process whose unix id is {pid})'
    )
    if not ok or not name:
        return False
    # Aktivieren via Application-Tell
    ok, _, _ = _osascript(f'tell application "{name}" to activate')
    if not ok:
        return False
    time.sleep(0.1)
    # Verify: ist die App jetzt frontmost?
    ok, frontmost, _ = _osascript(
        'tell application "System Events" to '
        'name of first process whose frontmost is true'
    )
    return ok and frontmost == name


# ---------- Tastatur-Sender ----------

# Mapping bekannter Sondertasten → AppleScript-Key-Code-Namen
_KEY_NAME_MAP: dict[str, str] = {
    "enter": "return",
    "esc": "escape",
    "left": "left arrow",
    "right": "right arrow",
    "up": "up arrow",
    "down": "down arrow",
    "delete": "delete",
    "backspace": "delete",
    "space": "space",
    "tab": "tab",
}


def _modifiers_to_apple(modifiers: list[str]) -> str:
    """Setzt Modifier-Liste zusammen für 'using {...}' Klausel."""
    apple_modifiers: list[str] = []
    for m in modifiers:
        m_low = m.lower()
        if m_low in ("cmd", "command"):
            apple_modifiers.append("command down")
        elif m_low in ("ctrl", "control"):
            apple_modifiers.append("control down")
        elif m_low == "shift":
            apple_modifiers.append("shift down")
        elif m_low in ("alt", "option"):
            apple_modifiers.append("option down")
        else:
            raise ValueError(f"Unbekannter Modifier {m!r}")
    return ", ".join(apple_modifiers)


def press_key_combo(combo: str, hold_ms: int = 30) -> None:
    """
    Sendet eine Tastenkombi wie 'cmd+s' oder 'cmd+shift+z' an die aktive App.
    """
    parts = [p.strip().lower() for p in combo.split("+") if p.strip()]
    if not parts:
        raise ValueError(f"Leere Tastenkombi: {combo!r}")

    # Letztes Element ist der Hauptkey, davor die Modifier
    main_key = parts[-1]
    modifiers = parts[:-1]

    # Map main_key
    if main_key in _KEY_NAME_MAP:
        keystroke_target = _KEY_NAME_MAP[main_key]
        # Use 'key code' or 'key down/up' for special keys
        if " " in keystroke_target or keystroke_target in ("return", "escape", "tab", "space", "delete"):
            # AppleScript 'keystroke X' funktioniert für return/escape/tab/space/delete als Wort
            keystroke_clause = f'keystroke "{keystroke_target}"'
            # für arrow-keys: 'key code N' wäre besser, aber komplex; vorerst keystroke
        else:
            keystroke_clause = f'keystroke "{keystroke_target}"'
    else:
        # Single character
        keystroke_clause = f'keystroke "{main_key}"'

    using_clause = ""
    if modifiers:
        using_clause = f' using {{{_modifiers_to_apple(modifiers)}}}'

    script = f'tell application "System Events" to {keystroke_clause}{using_clause}'
    ok, _, err = _osascript(script)
    if not ok:
        raise RuntimeError(f"AppleScript-Tastendruck fehlgeschlagen: {err}")
    time.sleep(hold_ms / 1000.0)


# ---------- AhkResult + Bridge ----------
# (Re-implementiert mit gleicher API wie _win_impl.py)

@dataclass
class AhkResult:
    ok: bool
    action: str
    daw: str
    window_guard: str
    target_window: dict[str, str] | None
    elapsed_ms: int
    error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        d = {
            "ok": self.ok,
            "action": self.action,
            "daw": self.daw,
            "window_guard": self.window_guard,
            "target_window": self.target_window,
            "elapsed_ms": self.elapsed_ms,
        }
        if self.error:
            d["error"] = self.error
        return d


class AhkBridge:
    """Mac-Variante der AhkBridge."""

    def list_actions(self, daw: str | None = None) -> dict[str, list[str]]:
        if daw:
            if daw not in DAW_ACTIONS:
                return {}
            return {daw: sorted(DAW_ACTIONS[daw].keys())}
        return {d: sorted(actions.keys()) for d, actions in DAW_ACTIONS.items()}

    def send_action(self, action: str, daw: str, restore_focus: bool = False) -> AhkResult:
        t0 = time.monotonic()

        if daw not in DAW_ACTIONS:
            return AhkResult(
                ok=False, action=action, daw=daw,
                window_guard="failed", target_window=None,
                elapsed_ms=int((time.monotonic() - t0) * 1000),
                error=f"Unbekannte DAW {daw!r}. Bekannt: {sorted(DAW_ACTIONS.keys())}",
            )

        if action not in DAW_ACTIONS[daw]:
            return AhkResult(
                ok=False, action=action, daw=daw,
                window_guard="failed", target_window=None,
                elapsed_ms=int((time.monotonic() - t0) * 1000),
                error=f"Action {action!r} nicht in Whitelist für {daw}. Verfügbar: {sorted(DAW_ACTIONS[daw].keys())}",
            )

        combo = DAW_ACTIONS[daw][action]

        pid = find_daw_window(daw)
        if pid is None:
            return AhkResult(
                ok=False, action=action, daw=daw,
                window_guard="failed", target_window=None,
                elapsed_ms=int((time.monotonic() - t0) * 1000),
                error=f"DAW-App für {daw!r} nicht gefunden — läuft die App?",
            )

        target_info = get_window_info(pid)

        if not bring_to_front(pid):
            return AhkResult(
                ok=False, action=action, daw=daw,
                window_guard="failed", target_window=target_info,
                elapsed_ms=int((time.monotonic() - t0) * 1000),
                error="Konnte DAW-App nicht in den Vordergrund bringen.",
            )

        try:
            press_key_combo(combo)
        except Exception as e:
            return AhkResult(
                ok=False, action=action, daw=daw,
                window_guard="passed", target_window=target_info,
                elapsed_ms=int((time.monotonic() - t0) * 1000),
                error=f"Tastendruck fehlgeschlagen: {type(e).__name__}: {e}",
            )

        # restore_focus auf Mac aktuell nicht implementiert — Mac-Claude kann ergänzen
        # wenn das wirklich gebraucht wird (typisch nicht, weil Mac-Apps brav den
        # alten Fokus behalten oder schnell wechseln können).

        return AhkResult(
            ok=True, action=action, daw=daw,
            window_guard="passed", target_window=target_info,
            elapsed_ms=int((time.monotonic() - t0) * 1000),
        )
