"""OSC-Adress-Schema für KI-Studio.

Definiert wie OSC-Adressen auf interne Aktionen (Mackie-MIDI-Sends oder
direkte MCP-Tool-Calls) gemappt werden.

Schema-Konvention orientiert sich an Reaper-OSC + AbletonOSC mit kleinen
KI-Studio-Erweiterungen:

    /track/<N>/volume <float 0..1>          — Track-Volume (0 = -inf, 1 = +6 dB)
    /track/<N>/volume_db <float -144..12>   — Track-Volume in dB direkt
    /track/<N>/select                       — Track selektieren (kein Arg)
    /track/<N>/mute <bool>                  — Track mute toggle/set
    /transport/play                          — Play
    /transport/stop                          — Stop
    /transport/record                        — Record (Zone=red, expliziter Intent)
    /mode <string>                          — Mode-Wechsel: track/send/pan/plugin/eq/instrument
    /bank/left                               — Bank zurueck
    /bank/right                              — Bank vor
    /plugin/preset <string>                  — apply_preset(preset_id)
    /plugin/preset/dry_run <string>          — apply_preset(preset_id, dry_run=True) — STC-Phase

Konfiguration: pro Schema-Entry der Ziel-Action + ob STC-Pattern angewendet wird.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable


@dataclass
class OSCAction:
    """Definiert eine einzelne OSC-Adress-Aktion."""
    address: str                          # OSC-Pattern, z. B. "/track/{idx}/volume"
    description: str                       # Mensch-lesbar
    action_type: str                       # "mackie_select_track" / "mackie_set_volume_db" / "mcp_call" / etc.
    arg_schema: list[str] = field(default_factory=list)  # erwartete Arg-Typen ["int", "float"]
    address_params: list[str] = field(default_factory=list)  # Pfad-Variablen, z. B. ["track_idx"]
    notes: str = ""


@dataclass
class OSCSchema:
    """Komplette Schema-Definition."""
    name: str
    version: str
    actions: dict[str, OSCAction] = field(default_factory=dict)

    def find(self, osc_address: str) -> tuple[OSCAction, dict[str, Any]] | None:
        """Matcht einen konkreten OSC-Pfad (z. B. '/track/3/volume') gegen Schema.

        Returns (action, extracted_params) oder None wenn kein Match.
        Pfad-Variablen werden extrahiert (z. B. {'track_idx': 3}).
        """
        for pattern, action in self.actions.items():
            parts_p = pattern.strip("/").split("/")
            parts_a = osc_address.strip("/").split("/")
            if len(parts_p) != len(parts_a):
                continue
            extracted: dict[str, Any] = {}
            matched = True
            for pp, pa in zip(parts_p, parts_a):
                if pp.startswith("{") and pp.endswith("}"):
                    var_name = pp[1:-1]
                    # Versuche int-Konvertierung wenn passend
                    try:
                        extracted[var_name] = int(pa)
                    except ValueError:
                        extracted[var_name] = pa
                else:
                    if pp != pa:
                        matched = False
                        break
            if matched:
                return action, extracted
        return None


def default_schema() -> OSCSchema:
    """Default-Schema fuer Cubase/Ableton via Mackie-Backend."""
    schema = OSCSchema(name="ki-studio-default", version="1.0")

    schema.actions["/track/{track_idx}/volume_db"] = OSCAction(
        address="/track/{track_idx}/volume_db",
        description="Track-Volume in dB direkt (-144 = mute, 0 = unity, +12 = max)",
        action_type="mackie_set_volume_db",
        arg_schema=["float"],
        address_params=["track_idx"],
        notes="track_idx 0-7 (Mackie-Bank-Position)",
    )

    schema.actions["/track/{track_idx}/volume"] = OSCAction(
        address="/track/{track_idx}/volume",
        description="Track-Volume als float 0..1 (0=-inf, 0.5=-6dB, 1=+6dB)",
        action_type="mackie_set_volume_normalized",
        arg_schema=["float"],
        address_params=["track_idx"],
        notes="Approximation: pct = (db + 60) / 72 — fuer simple Slider-Mappings",
    )

    schema.actions["/track/{track_idx}/select"] = OSCAction(
        address="/track/{track_idx}/select",
        description="Track selektieren (Mackie SELECT-Button)",
        action_type="mackie_select_track",
        arg_schema=[],
        address_params=["track_idx"],
        notes="track_idx 0-7",
    )

    schema.actions["/transport/play"] = OSCAction(
        address="/transport/play",
        description="Transport Play",
        action_type="mackie_transport_play",
    )

    schema.actions["/transport/stop"] = OSCAction(
        address="/transport/stop",
        description="Transport Stop",
        action_type="mackie_transport_stop",
    )

    schema.actions["/mode/{mode_name}"] = OSCAction(
        address="/mode/{mode_name}",
        description="Mode-Wechsel: track/send/pan/plugin/eq/instrument",
        action_type="mackie_set_mode",
        address_params=["mode_name"],
    )

    schema.actions["/bank/left"] = OSCAction(
        address="/bank/left",
        description="Mackie Bank Left (-8 Tracks)",
        action_type="mackie_bank_left",
    )

    schema.actions["/bank/right"] = OSCAction(
        address="/bank/right",
        description="Mackie Bank Right (+8 Tracks)",
        action_type="mackie_bank_right",
    )

    schema.actions["/plugin/preset/{preset_id}"] = OSCAction(
        address="/plugin/preset/{preset_id}",
        description="apply_preset (Mix-Preset aus mix_presets.json)",
        action_type="plugin_apply_preset",
        arg_schema=["string?"],  # optional: bus
        address_params=["preset_id"],
        notes="Wenn arg gegeben, ueberschreibt default_bus aus Preset.",
    )

    schema.actions["/plugin/preset/{preset_id}/dry_run"] = OSCAction(
        address="/plugin/preset/{preset_id}/dry_run",
        description="apply_preset mit STC dry_run=True (Vorschlag-Phase)",
        action_type="plugin_apply_preset_dry_run",
        arg_schema=["string?"],
        address_params=["preset_id"],
        notes="STC-Pattern: zeigt was passieren wuerde, sendet keine CCs.",
    )

    return schema
