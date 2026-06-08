"""
AHK-Layer (Python+pywin32-Variante) — Window-Guard + Hotkey-Send.

Was Mackie nicht abdeckt — Save, Export, Undo/Redo, Editor-Wechsel,
DAW-spezifische Macros — geht über synthetische Tastatur-Eingaben mit
strikter Window-Verifikation davor:

1. Find target DAW window (Cubase / Ableton)
2. Bring it to foreground (BringToFront)
3. Verify it's actually focused (GetForegroundWindow == target)
4. Send key sequence
5. Restore previous foreground window (optional, default off)

Kein AutoHotkey-Runtime nötig — pywin32 reicht. Wenn später echte AHK-
Power-User-Features benötigt werden (komplexe Makro-Sequenzen), kann
ein zusätzlicher AHK-v2-Layer hinzukommen.

Aufruf (aus Code):
    from runtime.ahk.bridge import AhkBridge
    bridge = AhkBridge()
    result = bridge.send_action("save_project", daw="cubase")
    # result: { ok, action, daw, window_guard, target_app, error?, elapsed_ms }
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any

import win32api  # type: ignore
import win32con  # type: ignore
import win32gui  # type: ignore


# ---------- DAW-Window-Erkennung ----------

@dataclass
class DawWindowSpec:
    name: str
    class_prefix: str | None  # GetClassName().startswith(...)
    title_contains: str | None  # title.lower() contains (kleingeschrieben)


DAW_WINDOWS: dict[str, DawWindowSpec] = {
    "cubase": DawWindowSpec(
        name="cubase",
        class_prefix="SteinbergWindowClass",
        title_contains="cubase",
    ),
    "ableton": DawWindowSpec(
        name="ableton",
        class_prefix="Ableton Live Window Class",
        title_contains="ableton live",
    ),
}


def find_daw_window(daw: str) -> int | None:
    """
    Sucht das Hauptfenster der DAW. Returns HWND oder None.
    Bei mehreren Treffern wird das erste sichtbare zurückgegeben.
    """
    if daw not in DAW_WINDOWS:
        raise ValueError(f"Unbekannte DAW {daw!r}. Bekannt: {sorted(DAW_WINDOWS.keys())}")

    spec = DAW_WINDOWS[daw]
    found: list[int] = []

    def callback(hwnd: int, _: Any) -> bool:
        if not win32gui.IsWindowVisible(hwnd):
            return True
        try:
            title = win32gui.GetWindowText(hwnd) or ""
            cls = win32gui.GetClassName(hwnd) or ""
        except Exception:
            return True

        title_match = spec.title_contains and spec.title_contains.lower() in title.lower()
        class_match = spec.class_prefix and cls.startswith(spec.class_prefix)
        if title_match or class_match:
            # Nur Hauptfenster (kein Parent)
            if win32gui.GetParent(hwnd) == 0:
                found.append(hwnd)
        return True

    win32gui.EnumWindows(callback, None)
    return found[0] if found else None


def get_window_info(hwnd: int) -> dict[str, str]:
    return {
        "hwnd": str(hwnd),
        "title": win32gui.GetWindowText(hwnd) or "",
        "class": win32gui.GetClassName(hwnd) or "",
    }


# ---------- Foreground-Bringen ----------

def bring_to_front(hwnd: int) -> bool:
    """
    Bringt das Fenster in den Vordergrund. Windows kann das verweigern, wenn
    der aufrufende Prozess nicht das aktive Fenster hält — wir versuchen den
    bekannten ALT-Tab-Trick als Workaround.
    """
    try:
        # Falls minimiert, restore
        if win32gui.IsIconic(hwnd):
            win32gui.ShowWindow(hwnd, win32con.SW_RESTORE)

        # Direkter Versuch
        win32gui.SetForegroundWindow(hwnd)
        time.sleep(0.05)

        # Verify
        if win32gui.GetForegroundWindow() == hwnd:
            return True

        # Workaround: ALT-Tap simuliert User-Aktivität, dann nochmal SetForeground
        win32api.keybd_event(win32con.VK_MENU, 0, 0, 0)
        time.sleep(0.01)
        win32gui.SetForegroundWindow(hwnd)
        win32api.keybd_event(win32con.VK_MENU, 0, win32con.KEYEVENTF_KEYUP, 0)
        time.sleep(0.05)

        return win32gui.GetForegroundWindow() == hwnd
    except Exception:
        return False


# ---------- Tastatur-Sender ----------

# Mapping bekannter Sondertasten → Virtual-Key-Codes
_KEY_MAP: dict[str, int] = {
    "ctrl": win32con.VK_CONTROL,
    "control": win32con.VK_CONTROL,
    "shift": win32con.VK_SHIFT,
    "alt": win32con.VK_MENU,
    "win": win32con.VK_LWIN,
    "enter": win32con.VK_RETURN,
    "return": win32con.VK_RETURN,
    "esc": win32con.VK_ESCAPE,
    "escape": win32con.VK_ESCAPE,
    "tab": win32con.VK_TAB,
    "space": win32con.VK_SPACE,
    "backspace": win32con.VK_BACK,
    "delete": win32con.VK_DELETE,
    "left": win32con.VK_LEFT,
    "right": win32con.VK_RIGHT,
    "up": win32con.VK_UP,
    "down": win32con.VK_DOWN,
    "f1": win32con.VK_F1, "f2": win32con.VK_F2, "f3": win32con.VK_F3,
    "f4": win32con.VK_F4, "f5": win32con.VK_F5, "f6": win32con.VK_F6,
    "f7": win32con.VK_F7, "f8": win32con.VK_F8, "f9": win32con.VK_F9,
    "f10": win32con.VK_F10, "f11": win32con.VK_F11, "f12": win32con.VK_F12,
    # F13-F24: existieren als Windows-Virtual-Keys auch ohne physische Tasten.
    # Cubase nimmt sie an, wenn ein synthetischer Keystroke ankommt — perfekt
    # fuer KI-Cluster, weil sie keine physische Tastatur-Kollision haben.
    "f13": win32con.VK_F13, "f14": win32con.VK_F14, "f15": win32con.VK_F15,
    "f16": win32con.VK_F16, "f17": win32con.VK_F17, "f18": win32con.VK_F18,
    "f19": win32con.VK_F19, "f20": win32con.VK_F20, "f21": win32con.VK_F21,
    "f22": win32con.VK_F22, "f23": win32con.VK_F23, "f24": win32con.VK_F24,
}


def _vk_for(key: str) -> int:
    k = key.strip().lower()
    if k in _KEY_MAP:
        return _KEY_MAP[k]
    # Single character (a-z, 0-9 etc.)
    if len(k) == 1:
        # win32api.VkKeyScan returns VK + shift state in the high byte
        scan = win32api.VkKeyScan(k)
        if scan == -1:
            raise ValueError(f"Unbekannte Taste: {key!r}")
        return scan & 0xFF
    raise ValueError(f"Unbekannte Taste: {key!r}")


def press_key_combo(combo: str, hold_ms: int = 30) -> None:
    """
    Sendet eine Tastenkombi wie 'ctrl+s' oder 'ctrl+shift+z'.
    Modifier-Reihenfolge: ctrl, shift, alt, win, dann der Hauptkey.
    """
    parts = [p.strip().lower() for p in combo.split("+") if p.strip()]
    vks = [_vk_for(p) for p in parts]

    # Press all in order
    for vk in vks:
        win32api.keybd_event(vk, 0, 0, 0)
    time.sleep(hold_ms / 1000.0)
    # Release reverse order
    for vk in reversed(vks):
        win32api.keybd_event(vk, 0, win32con.KEYEVENTF_KEYUP, 0)


# ---------- DAW-spezifische Action-Map ----------

# Whitelist: NUR diese Actions sind erlaubt. Kein generisches "tippe Text".
DAW_ACTIONS: dict[str, dict[str, str]] = {
    "cubase": {
        # ─── Verifiziert gegen Cubase 15 Key Commands.xml (2026-06-07) ───
        # Quelle: docs/cubase_keymap.csv + docs/drehbuch_hotkey_layout.md + drehbuch_macros.md
        # Patch-Skript: outputs/patch_cubase_keymap.py

        # --- Default Cubase-Shortcuts (built-in) ---
        "save_project": "ctrl+s",
        "save_project_as": "ctrl+shift+s",
        "undo": "ctrl+z",
        "redo": "ctrl+shift+z",
        "select_all": "ctrl+a",
        "duplicate": "ctrl+d",
        "delete": "delete",
        "open_mixer": "f3",                          # Devices: Mixer
        "open_mixer_lower": "alt+f3",                # MixConsole Lower Zone
        "open_vst_instruments_rack": "f11",          # Devices: VST Instruments
        "open_vst_connections": "f4",                # Devices: VST Connections
        "open_transport_panel": "f2",                # Transport: Panel
        "open_mediabay": "f5",                       # Media: Open MediaBay
        "open_add_track_dialog": "t",                # AddTrack: OpenDialog
        "toggle_right_zone": "ctrl+alt+r",           # Window Zones: Show/Hide Right Zone
        "transport_play_kbd": "space",               # Transport: Play/Stop

        # --- KI-Cluster (gepatcht via patch_cubase_keymap.py am 2026-06-07) ---
        # Track-Setup
        "add_group_to_selected": "ctrl+alt+shift+g",
        "add_fx_to_selected": "ctrl+alt+shift+x",
        "add_vca_to_selected": "ctrl+alt+shift+v",
        # MixConsole Snapshots
        "mix_snapshot_save": "ctrl+alt+shift+c",     # C = Capture (S kollidiert mit Export Mixdown)
        "mix_snapshot_recall_1": "ctrl+alt+shift+0",
        "mix_snapshot_recall_2": "ctrl+alt+shift+2",
        "mix_snapshot_recall_3": "ctrl+alt+shift+3",
        # Bypass-Cluster
        "bypass_inserts_selected": "ctrl+alt+shift+b",
        "bypass_eqs_selected": "ctrl+alt+shift+e",
        "bypass_sends_selected": "ctrl+alt+shift+n",
        "bypass_strip_selected": "ctrl+alt+shift+h",
        "bypass_modulators_selected": "ctrl+alt+shift+w",
        # PPLE (Process Project Logical Editor — projektweite Macros)
        "ppl_toggle_eq_bypass_selected": "ctrl+alt+shift+q",
        "ppl_toggle_inserts_bypass_selected": "ctrl+alt+shift+j",
        "ppl_toggle_sends_bypass_selected": "ctrl+alt+shift+k",
        "ppl_hide_empty_midi": "ctrl+alt+shift+y",
        "ppl_open_key_editor_selected": "ctrl+alt+shift+u",
        "ppl_open_sample_editor_selected": "ctrl+alt+shift+l",
        "ppl_quantize_16th_selected": "ctrl+alt+shift+6",
        "ppl_quantize_8th_selected": "ctrl+alt+shift+8",
        "ppl_quantize_4th_selected": "ctrl+alt+shift+4",
        # Quantize-Live
        "quantize_iterative": "ctrl+alt+shift+5",
        "quantize_freeze": "ctrl+alt+shift+7",
        "quantize_undo": "ctrl+alt+shift+9",
        # Editor-Opener (Lower Zone)
        "open_key_editor_lower": "ctrl+alt+shift+p",
        "open_drum_editor_lower": "ctrl+alt+shift+d",
        "open_sample_editor_lower": "ctrl+alt+shift+m",
        "open_score_editor_lower": "ctrl+alt+shift+o",

        # --- Macros (Cubase-eigene Sequenz-Macros, gepatcht 2026-06-07) ---
        # Siehe docs/drehbuch_macros.md für die Step-Listen.
        "macro_demo_setup_basic": "ctrl+alt+shift+r",     # New + Add Group + Mixer + Workspace1
        "macro_solo_selected_loop": "ctrl+alt+shift+f",   # Solo + Locators + Cycle + Play
        "macro_prep_eq_demo": "ctrl+alt+shift+z",         # Bypass Inserts + Solo
        "macro_reset_take": "ctrl+alt+shift+f13",         # Stop + Zero + Recall1 + Solo off + WS1
        "macro_finalize_and_save": "ctrl+alt+shift+f14",  # Stop + Solo off + Snapshot + Save
        "macro_quantize_demo_show": "ctrl+alt+shift+f15", # Open Key Editor + Select All

        # Export Audio Mixdown (Cubase-Default, überraschend Strg+Alt+Shift+S)
        "export_audio_mixdown": "ctrl+alt+shift+s",
        "macro_export_mixdown_whole_song": "ctrl+alt+shift+1",  # User-Custom-Macro

        # --- Patch v2 (2026-06-07): Record-Workflow & Plugin-Slots ---

        # Cubase-Defaults (kein XML-Patch nötig, nur Whitelist-Eintrag):
        # Achtung: single-letter Hotkeys feuern auch in Text-Eingabefelder.
        # Window-Guard "no_modal_dialog" hilft hier nur bedingt — Track-Name-
        # Inline-Editing ist kein Modal. Aufrufer muss sicherstellen, dass
        # Project-Window-Hintergrund Fokus hat.
        "record_enable_selected": "r",
        "mute_selected": "m",
        "solo_selected": "s",
        "metronome_toggle": "c",
        "punch_in_toggle": "i",
        "punch_out_toggle": "o",

        # Gepatchte Hotkeys (Patch v2):
        "insert_01_editor": "ctrl+alt+shift+f16",        # Plugin im Insert-Slot 1
        "insert_02_editor": "ctrl+alt+shift+f17",        # Insert-Slot 2
        "close_all_insert_editors": "ctrl+alt+shift+f18",
        "monitor_selected": "ctrl+alt+shift+f19",        # Monitor toggle für aktive Spur
        "toggle_step_input": "ctrl+alt+shift+f20",       # MIDI Step-Input
        "ppl_toggle_record_all": "ctrl+alt+shift+f21",   # PPLE: alle Tracks record-enable togglen
        "ppl_toggle_monitor_all_audio": "ctrl+alt+shift+f22",
        "open_plugin_manager": "ctrl+alt+shift+f23",
        "focus_next_plugin_window": "ctrl+alt+shift+f24",

        # Virtual Keyboard (Cubase-Default, für MIDI-Eingabe via Computer-Keyboard)
        "open_virtual_keyboard": "alt+k",
    },
    "ableton": {
        "save_project": "ctrl+s",
        "save_project_as": "ctrl+shift+s",
        "undo": "ctrl+z",
        "redo": "ctrl+shift+z",  # In Ableton funktioniert auch ctrl+y
        # Ableton Export: ctrl+shift+r für "Export Audio/Video"
        "export_audio": "ctrl+shift+r",
    },
}


def _merge_generated_cubase_actions() -> None:
    """Merged die generierten Pareto-Cubase-Actions (cubase_actions_generated.json)
    in DAW_ACTIONS['cubase']. Die JSON wird von outputs/generate_pareto_keymap.py
    erzeugt und enthaelt ~379 Hotkey-Bindings fuer Workflow-Commands.

    setdefault: die handgepflegten Basis-Actions oben haben Vorrang, generierte
    Actions ergaenzen nur. Faellt die JSON weg, laeuft die Basis-Whitelist normal.
    """
    import json
    from pathlib import Path
    p = Path(__file__).resolve().parent / "cubase_actions_generated.json"
    if not p.exists():
        return
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return
    cubase = DAW_ACTIONS.setdefault("cubase", {})
    for action, spec in data.items():
        key = spec.get("key") if isinstance(spec, dict) else spec
        if key:
            cubase.setdefault(action, key)


_merge_generated_cubase_actions()


# ---------- Bridge-API ----------

@dataclass
class AhkResult:
    ok: bool
    action: str
    daw: str
    window_guard: str  # "passed" | "failed"
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
    """Hält keine globale State, jeder send_action ist self-contained."""

    def list_actions(self, daw: str | None = None) -> dict[str, list[str]]:
        if daw:
            if daw not in DAW_ACTIONS:
                return {}
            return {daw: sorted(DAW_ACTIONS[daw].keys())}
        return {d: sorted(actions.keys()) for d, actions in DAW_ACTIONS.items()}

    def send_action(self, action: str, daw: str, restore_focus: bool = False) -> AhkResult:
        """
        Hauptmethode. Sucht DAW-Fenster, bringt nach vorne, verifiziert Fokus,
        sendet Key-Combo, optional restore alten Fokus.
        """
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

        hwnd = find_daw_window(daw)
        if hwnd is None:
            return AhkResult(
                ok=False, action=action, daw=daw,
                window_guard="failed", target_window=None,
                elapsed_ms=int((time.monotonic() - t0) * 1000),
                error=f"DAW-Fenster für {daw!r} nicht gefunden — läuft die DAW?",
            )

        target_info = get_window_info(hwnd)

        # Optional: aktuellen Fokus merken um später wiederherzustellen
        prev_hwnd = win32gui.GetForegroundWindow() if restore_focus else None

        if not bring_to_front(hwnd):
            return AhkResult(
                ok=False, action=action, daw=daw,
                window_guard="failed", target_window=target_info,
                elapsed_ms=int((time.monotonic() - t0) * 1000),
                error="Konnte DAW-Fenster nicht in den Vordergrund bringen.",
            )

        # Window-Guard verifiziert: wirklich Cubase/Ableton vorne?
        if win32gui.GetForegroundWindow() != hwnd:
            return AhkResult(
                ok=False, action=action, daw=daw,
                window_guard="failed", target_window=target_info,
                elapsed_ms=int((time.monotonic() - t0) * 1000),
                error="Window-Guard fehlgeschlagen: Vordergrund nicht das DAW-Fenster.",
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

        if restore_focus and prev_hwnd and prev_hwnd != hwnd:
            try:
                bring_to_front(prev_hwnd)
            except Exception:
                pass

        return AhkResult(
            ok=True, action=action, daw=daw,
            window_guard="passed", target_window=target_info,
            elapsed_ms=int((time.monotonic() - t0) * 1000),
        )
