"""
AHK-Layer — Window-Guard + Hotkey-Send mit plattform-Dispatcher.

Was Mackie nicht abdeckt — Save, Export, Undo/Redo, Editor-Wechsel,
DAW-spezifische Macros — geht über synthetische Tastatur-Eingaben mit
strikter Window-Verifikation davor.

Plattform-Implementierungen:
- Windows: `_win_impl.py` (pywin32 + win32api.keybd_event)
- macOS:   `_mac_impl.py` (osascript + System Events)

Diese Datei dispatcht zur passenden Implementierung. Selbe API für beide:

    from runtime.ahk.bridge import AhkBridge, DAW_ACTIONS, find_daw_window
    bridge = AhkBridge()
    result = bridge.send_action("save_project", daw="cubase")

Die DAW_ACTIONS-Whitelist enthält pro Plattform die korrekten Hotkeys:
- Windows: ctrl+s, ctrl+z, ...
- Mac: cmd+s, cmd+z, ...

Das ist transparent für den Aufrufer. Tools wie `save_project(daw)` im
MCP-Server bleiben plattform-agnostisch.
"""

from __future__ import annotations

import platform

if platform.system() == "Darwin":
    from runtime.ahk._mac_impl import (  # noqa: F401
        AhkBridge,
        AhkResult,
        DAW_ACTIONS,
        DAW_PROCESS_NAMES as DAW_WINDOWS,  # alias für API-Konsistenz
        bring_to_front,
        find_daw_window,
        get_window_info,
        press_key_combo,
    )
else:
    from runtime.ahk._win_impl import (  # noqa: F401
        AhkBridge,
        AhkResult,
        DAW_ACTIONS,
        DAW_WINDOWS,
        bring_to_front,
        find_daw_window,
        get_window_info,
        press_key_combo,
    )


__all__ = [
    "AhkBridge",
    "AhkResult",
    "DAW_ACTIONS",
    "DAW_WINDOWS",
    "bring_to_front",
    "find_daw_window",
    "get_window_info",
    "press_key_combo",
]
