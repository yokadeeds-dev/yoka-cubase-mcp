"""OSC-Translator: nimmt OSC-Address + Args, ruft passende Backend-Funktion.

Backend-Optionen:
- "mackie":      ueber loopMIDI + Mackie-Listener, fuer Cubase (default)
- "mcp":         ueber direkten Aufruf der MCP-Tool-Logik (im selben Prozess)
- "dry_log":    nichts ausfuehren, nur loggen (Sanity-Check fuer Schema)

Aktuell ist der "mackie"-Backend ein duenner Wrapper, der die bestehenden
runtime.persona.plugin_control + runtime.mackie.sender APIs nutzt. Kein
neuer MIDI-Code, nur Routing.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Callable

from runtime.osc.schema import OSCAction, OSCSchema, default_schema

logger = logging.getLogger(__name__)


@dataclass
class TranslateResult:
    """Ergebnis einer OSC-Translation."""
    ok: bool
    action_type: str
    address: str
    args: list[Any] = field(default_factory=list)
    extracted: dict[str, Any] = field(default_factory=dict)
    backend_response: dict[str, Any] | None = None
    error: str | None = None


class OSCTranslator:
    """Mapper von OSC-Events auf KI-Studio-Backend-Aktionen.

    Args:
        schema: OSCSchema (default = default_schema())
        backend: "mackie" | "mcp" | "dry_log"
        default_daw: nur fuer "mcp"-Backend relevant
        port: loopMIDI-Port-Name fuer mackie-Backend (default "AI_INPUT")
    """

    def __init__(
        self,
        schema: OSCSchema | None = None,
        backend: str = "dry_log",
        default_daw: str = "cubase",
        port: str = "AI_INPUT",
    ) -> None:
        self.schema = schema or default_schema()
        self.backend = backend
        self.default_daw = default_daw
        self.port = port

    def handle(self, osc_address: str, *args: Any) -> TranslateResult:
        """Hauptaufruf: nimmt OSC-Adresse + Args, fuehrt aus."""
        found = self.schema.find(osc_address)
        if found is None:
            return TranslateResult(
                ok=False, action_type="unknown", address=osc_address,
                args=list(args),
                error=f"Keine Aktion im Schema fuer Adresse {osc_address!r}",
            )

        action, extracted = found
        result = TranslateResult(
            ok=True,
            action_type=action.action_type,
            address=osc_address,
            args=list(args),
            extracted=extracted,
        )

        if self.backend == "dry_log":
            logger.info(
                "OSC dry_log: address=%s action=%s extracted=%s args=%s",
                osc_address, action.action_type, extracted, args,
            )
            result.backend_response = {"dry_log": True}
            return result

        if self.backend == "mackie":
            try:
                response = self._dispatch_mackie(action, extracted, args)
                result.backend_response = response
                result.ok = bool(response.get("ok", True))
                if not result.ok:
                    result.error = response.get("error")
            except Exception as e:  # noqa: BLE001 — POC-tolerant
                result.ok = False
                result.error = f"{type(e).__name__}: {e}"
            return result

        # backend == "mcp" — direkter Tool-Call ohne Server-Roundtrip
        if self.backend == "mcp":
            try:
                response = self._dispatch_mcp(action, extracted, args)
                result.backend_response = response
                result.ok = bool(response.get("ok", True))
                if not result.ok:
                    result.error = response.get("error")
            except Exception as e:  # noqa: BLE001
                result.ok = False
                result.error = f"{type(e).__name__}: {e}"
            return result

        result.ok = False
        result.error = f"Unbekannter Backend {self.backend!r}"
        return result

    # ------------------------------------------------------------------
    # Backend: mackie (via runtime.mackie.closedloop + persona.plugin_control)
    # ------------------------------------------------------------------

    def _dispatch_mackie(
        self, action: OSCAction, extracted: dict[str, Any], args: tuple[Any, ...],
    ) -> dict[str, Any]:
        """Mackie-Backend dispatcher."""
        # Lazy-Import damit OSC-Modul ohne mido importierbar bleibt (z. B. fuer Schema-Tests)
        from runtime.mackie.units import db_to_value14
        from runtime.midi_bridge.send_cc import send_cc

        at = action.action_type

        if at == "mackie_set_volume_db":
            if not args:
                return {"ok": False, "error": "volume_db braucht einen float-Arg"}
            track_idx = int(extracted["track_idx"])
            db = float(args[0])
            value14 = db_to_value14(db)
            return {
                "ok": True,
                "note": "set_track_volume_db ist eigentlich Pitch-Bend - fuer den POC noch nicht implementiert",
                "would_set": {"track_idx": track_idx, "db": db, "value14": value14},
            }

        if at == "mackie_set_volume_normalized":
            if not args:
                return {"ok": False, "error": "volume braucht einen float-Arg (0..1)"}
            pct = max(0.0, min(1.0, float(args[0])))
            # Approximation: 0=-60dB, 0.5=-6dB, 1=+6dB. Piecewise wuerde besser passen.
            db = pct * 72.0 - 60.0
            return {
                "ok": True,
                "note": "Normalized volume nicht final implementiert im POC",
                "would_set": {"track_idx": extracted["track_idx"], "db": db},
            }

        if at == "mackie_select_track":
            track_idx = int(extracted["track_idx"])
            return {"ok": True, "note": f"would select track {track_idx}"}

        if at == "mackie_transport_play":
            return {"ok": True, "note": "would send Mackie PLAY"}

        if at == "mackie_transport_stop":
            return {"ok": True, "note": "would send Mackie STOP"}

        if at == "mackie_set_mode":
            mode = extracted.get("mode_name", "")
            return {"ok": True, "note": f"would set mode {mode!r}"}

        if at in ("mackie_bank_left", "mackie_bank_right"):
            return {"ok": True, "note": f"would {at}"}

        if at == "plugin_apply_preset":
            try:
                from runtime.persona.plugin_control import apply_preset
            except ImportError:
                return {"ok": False, "error": "plugin_apply_preset requires premium package (yoka-cubase-premium)"}
            preset_id = extracted["preset_id"]
            bus = args[0] if args else None
            r = apply_preset(preset_id=preset_id, bus=bus, port=self.port, dry_run=False)
            return r

        if at == "plugin_apply_preset_dry_run":
            try:
                from runtime.persona.plugin_control import apply_preset
            except ImportError:
                return {"ok": False, "error": "plugin_apply_preset requires premium package (yoka-cubase-premium)"}
            preset_id = extracted["preset_id"]
            bus = args[0] if args else None
            r = apply_preset(preset_id=preset_id, bus=bus, port=self.port, dry_run=True)
            return r

        return {"ok": False, "error": f"Backend mackie kennt action_type {at!r} nicht"}

    # ------------------------------------------------------------------
    # Backend: mcp (direkter Aufruf der Plugin-Control-Logik)
    # ------------------------------------------------------------------

    def _dispatch_mcp(
        self, action: OSCAction, extracted: dict[str, Any], args: tuple[Any, ...],
    ) -> dict[str, Any]:
        """MCP-Backend: nutzt dieselbe Logik wie der MCP-Server-Dispatcher.

        Aktuell minimaler Wrapper — Fokus liegt auf den plugin_apply_preset
        Aktionen, weil das die meisten Wert-bringenden sind.
        """
        at = action.action_type

        if at == "plugin_apply_preset":
            try:
                from runtime.persona.plugin_control import apply_preset
            except ImportError:
                return {"ok": False, "error": "plugin_apply_preset requires premium package (yoka-cubase-premium)"}
            return apply_preset(
                preset_id=extracted["preset_id"],
                bus=args[0] if args else None,
                port=self.port,
                dry_run=False,
            )

        if at == "plugin_apply_preset_dry_run":
            try:
                from runtime.persona.plugin_control import apply_preset
            except ImportError:
                return {"ok": False, "error": "plugin_apply_preset requires premium package (yoka-cubase-premium)"}
            return apply_preset(
                preset_id=extracted["preset_id"],
                bus=args[0] if args else None,
                port=self.port,
                dry_run=True,
            )

        return {
            "ok": False,
            "error": f"MCP-Backend nicht implementiert fuer action_type {at!r} (POC)",
        }
