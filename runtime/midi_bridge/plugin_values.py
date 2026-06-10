"""
plugin_values.py — Loest Plugin-Parameter by name in eine MIDI-CC-Adresse auf,
anhand der vom Value-Binding-Generator erzeugten cubase_value_cc_map.json.

Adressierungs-Modell (siehe generate_value_bindings.py):
  Port    : AI_VAL
  Channel : 0-7 (API)  = Insert-Slot 0-7 der selektierten Spur (DAW-Anzeige 1-8)
  CC      : 0-63       = Parameter-Index im Slot
  Wert    : 0-127      = Param-Min .. Param-Max

Damit kann die KI sagen "setze StudioEQ band1_gain auf Slot 0" statt rohe CCs.
Welches Plugin auf welchem Slot liegt, weiss die KI/der Nutzer (Selektion + Slot).
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

REPO = Path(__file__).resolve().parent.parent.parent
CC_MAP_PATH = REPO / "runtime" / "midi_bridge" / "cubase_value_cc_map.json"
# Free-Build: volle CC-Map fehlt -> Fallback auf die Demo (1 Stock-Plugin je Kategorie).
DEMO_CC_MAP_PATH = REPO / "runtime" / "midi_bridge" / "cubase_value_cc_map_demo.json"

_cache: Optional[dict] = None


_MISSING_MSG = (
    "Keine CC-Map gefunden (weder cubase_value_cc_map.json noch ...demo.json). "
    "make_demo_param_map.py bzw. generate_value_bindings.py laufen lassen, oder das "
    "Premium-Add-On mit voller Plugin-Abdeckung installieren."
)


def _load() -> dict:
    """Laedt die CC-Map: volle (Premium/Werkstatt) bevorzugt, sonst die Demo
    (Free-Build, 1 Stock-Plugin je Kategorie). Fehlt beides, gibt resolve() eine
    klare Meldung statt zu crashen — das Tool bleibt im Free-Server lauffaehig."""
    global _cache
    if _cache is None:
        for path in (CC_MAP_PATH, DEMO_CC_MAP_PATH):
            try:
                _cache = json.loads(path.read_text(encoding="utf-8"))
                break
            except FileNotFoundError:
                continue
        else:
            _cache = {"plugins": {}, "_missing": True}
    return _cache


def reload_map() -> None:
    """Cache leeren (nach Re-Scan/Generator-Lauf)."""
    global _cache
    _cache = None


def _match_plugin(query: str, plugins: dict):
    """(name, error). Exakt (case-insensitiv) bevorzugt, sonst eindeutiger Substring."""
    ql = query.strip().lower()
    for name in plugins:
        if name.lower() == ql:
            return name, None
    cands = [n for n in plugins if ql in n.lower()]
    if len(cands) == 1:
        return cands[0], None
    if len(cands) > 1:
        return None, f"Plugin '{query}' mehrdeutig: {sorted(cands)[:10]}"
    return None, f"Plugin '{query}' nicht in der CC-Map (129 Plugins). Tippfehler?"


def resolve(plugin: str, param: str):
    """Loest (plugin, param) -> dict mit cc/title/role/param_index auf.

    param wird gegen role, title und param_index (als String) gematcht.
    Rueckgabe: (info_dict | None, error | None).
    """
    m = _load()
    plugins = m.get("plugins", {})
    if m.get("_missing"):
        return None, _MISSING_MSG
    pl_name, err = _match_plugin(plugin, plugins)
    if err:
        return None, err
    pl = plugins[pl_name]
    ps = str(param).strip().lower()
    for p in pl["params"]:
        candidates = {
            str(p.get("role", "")).lower(),
            str(p.get("title", "")).lower(),
            str(p.get("param_index")),
            str(p.get("cc")),
        }
        if ps in candidates:
            return {"plugin": pl_name, **p}, None
    avail = [p.get("role") or p.get("title") for p in pl["params"]]
    return None, f"Param '{param}' nicht in '{pl_name}'. Verfuegbar: {avail[:25]}"


def list_params(plugin: str):
    """Alle Parameter eines Plugins (fuer Discovery). (list|None, error|None)."""
    m = _load()
    pl_name, err = _match_plugin(plugin, m.get("plugins", {}))
    if err:
        return None, err
    return m["plugins"][pl_name]["params"], None


def addressing() -> dict:
    return _load().get("addressing", {})
