"""
MCP-Server für KI-Studio Mackie — exponiert DAW-Steuerung als Tools für
Claude (oder beliebige MCP-Clients).

Multi-DAW-fähig (Etappe 6): hält pro DAW einen eigenen ClosedLoopController.
Aktuell unterstützt: cubase, ableton. Erweiterbar via DAW_REGISTRY.

Tool-Schema-Konvention:
- Alle Tools haben einen optionalen `daw`-Parameter (Default: "cubase").
- Tool-Returns enthalten `target_daw` im Result-Envelope.

Aufruf (via Claude-Code-Konfig in ~/.claude.json):
    {
      "mcpServers": {
        "ki-studio-mackie": {
          "command": ".../python.exe",
          "args": ["-m", "runtime.mcp.server"],
          "cwd": "...KI Studio 2026",
          "env": {
            "MACKIE_DAW_DEFAULT": "cubase",
            "MACKIE_LISTENER_PORT_CUBASE":  "MACKIE_FROM_CUBASE",
            "MACKIE_SENDER_PORT_CUBASE":    "MACKIE_TO_CUBASE",
            "MACKIE_LISTENER_PORT_ABLETON": "MACKIE_FROM_ABLETON",
            "MACKIE_SENDER_PORT_ABLETON":   "MACKIE_TO_ABLETON"
          }
        }
      }
    }

Manueller Test:
    python -m runtime.mcp.server          # läuft auf stdio bis EOF
"""

from __future__ import annotations

import asyncio
import json
import os
import time
from typing import Any

from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import TextContent, Tool

from runtime.ahk.bridge import DAW_ACTIONS, AhkBridge
from runtime.mackie.closedloop import ClosedLoopController
from runtime.mackie.units import db_to_value14, value14_to_db
from runtime.midi_bridge.send_cc import (
    send_cc as send_midi_cc,
    send_cc_value_for_param as send_midi_cc_pct,
    send_cc_value_for_range as send_midi_cc_range,
    send_notes as send_midi_notes,
    send_note_sequence as send_midi_note_sequence,
)
# ---------- Premium-Plugin-Hook ----------
# Premium-Module (persona, traktor) sind optional. Wenn die Imports failen,
# laeuft der Server im Public-Build-Modus: nur Core-Tools verfuegbar.
# Public-Init kopiert Files OHNE runtime/persona/ + runtime/traktor/ → automatisch.
#
# Defensive: Premium-Module muessen im SELBEN runtime/-Verzeichnis liegen wie
# dieses Modul. Sonst koennten sys.path-Leaks (Claude Code spawnt MCP-Server
# manchmal mit cwd der Host-App, nicht der MCP-Config) Premium-Module aus
# einem anderen Repo laden und damit die Public/Private-Trennung umgehen.
def _premium_in_same_runtime() -> bool:
    import os as _os
    _here = _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__)))  # .../runtime/
    return _os.path.isdir(_os.path.join(_here, "persona")) and _os.path.isdir(_os.path.join(_here, "traktor"))

if _premium_in_same_runtime():
    try:
        from runtime.persona.plugin_control import (
            apply_preset as plugin_apply_preset,
            list_presets as plugin_list_presets,
            set_pro_c2 as plugin_set_pro_c2,
            set_pro_q3_band as plugin_set_pro_q3_band,
        )
        from runtime.persona.plugin_registry import (
            get_plugin_details as registry_get_plugin_details,
            list_untagged as registry_list_untagged,
            lookup_plugin as registry_lookup_plugin,
            registry_stats as registry_stats_fn,
        )
        from runtime.persona.cubase_plugin_sync import sync as cubase_plugin_sync_run
        from runtime.persona.reports import render_session_report
        from runtime.traktor.observer import snapshot as traktor_snapshot
        PREMIUM_AVAILABLE = True
    except ImportError:
        PREMIUM_AVAILABLE = False
else:
    PREMIUM_AVAILABLE = False

if not PREMIUM_AVAILABLE:
    plugin_apply_preset = None  # type: ignore[assignment]
    plugin_list_presets = None  # type: ignore[assignment]
    plugin_set_pro_c2 = None  # type: ignore[assignment]
    plugin_set_pro_q3_band = None  # type: ignore[assignment]
    registry_get_plugin_details = None  # type: ignore[assignment]
    registry_list_untagged = None  # type: ignore[assignment]
    registry_lookup_plugin = None  # type: ignore[assignment]
    registry_stats_fn = None  # type: ignore[assignment]
    cubase_plugin_sync_run = None  # type: ignore[assignment]
    render_session_report = None  # type: ignore[assignment]
    traktor_snapshot = None  # type: ignore[assignment]
    PREMIUM_AVAILABLE = False


# ---------- DAW-Registry (Multi-DAW) ----------
#
# Pro DAW: ein Paar loopMIDI-Ports. ENV-Variablen pro DAW überschreibbar.
# Backwards-Compat: alte ENV-Vars MACKIE_LISTENER_PORT/MACKIE_SENDER_PORT
# werden weiterhin als Cubase-Ports respektiert, falls die DAW-spezifischen
# nicht gesetzt sind.

DAW_REGISTRY: dict[str, dict[str, str]] = {
    "cubase": {
        "listener_port": os.environ.get(
            "MACKIE_LISTENER_PORT_CUBASE",
            os.environ.get("MACKIE_LISTENER_PORT", "MACKIE_FROM_CUBASE"),
        ),
        "sender_port": os.environ.get(
            "MACKIE_SENDER_PORT_CUBASE",
            os.environ.get("MACKIE_SENDER_PORT", "MACKIE_TO_CUBASE"),
        ),
    },
    "ableton": {
        "listener_port": os.environ.get("MACKIE_LISTENER_PORT_ABLETON", "MACKIE_FROM_ABLETON"),
        "sender_port": os.environ.get("MACKIE_SENDER_PORT_ABLETON", "MACKIE_TO_ABLETON"),
    },
}

# Traktor-Entry nur registrieren wenn Premium-Module verfuegbar (Traktor-Observer ist Premium)
if PREMIUM_AVAILABLE:
    DAW_REGISTRY["traktor"] = {
        "listener_port": os.environ.get("MACKIE_LISTENER_PORT_TRAKTOR", "MACKIE_FROM_CUBASE"),
        "sender_port": os.environ.get("MACKIE_SENDER_PORT_TRAKTOR", "MACKIE_TO_CUBASE"),
    }

DEFAULT_DAW = os.environ.get("MACKIE_DAW_DEFAULT", os.environ.get("MACKIE_DAW", "cubase"))
DEFAULT_TIMEOUT_MS = 800

# Schema-Fragment für den daw-Parameter (in jedem Tool wiederverwendet)
_DAW_PARAM_SCHEMA = {
    "type": "string",
    "enum": sorted(DAW_REGISTRY.keys()),
    "default": DEFAULT_DAW,
    "description": f"Ziel-DAW. Default: {DEFAULT_DAW}.",
}


# ---------- Result-Envelope (Concept-Sketch §6) ----------

def _now_iso() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime()) + time.strftime("%z")


def _envelope(
    *,
    tool: str,
    ok: bool,
    daw: str = DEFAULT_DAW,
    requested: Any = None,
    observed: Any = None,
    verified: bool = False,
    was_already_satisfied: bool | None = None,
    source: str = "state_mirror",
    freshness_ms: int | None = None,
    elapsed_ms: int | None = None,
    error: str | None = None,
) -> dict[str, Any]:
    env: dict[str, Any] = {
        "ok": ok,
        "tool": tool,
        "target_daw": daw,
        "verified": verified,
        "source": source,
        "timestamp": _now_iso(),
    }
    if was_already_satisfied is not None:
        env["was_already_satisfied"] = was_already_satisfied
    if requested is not None:
        env["requested"] = requested
    if observed is not None:
        env["observed"] = observed
    if freshness_ms is not None:
        env["freshness_ms"] = freshness_ms
    if elapsed_ms is not None:
        env["elapsed_ms"] = elapsed_ms
    if error is not None:
        env["error"] = error
    return env


def _to_content(env: dict[str, Any]) -> list[TextContent]:
    return [TextContent(type="text", text=json.dumps(env, indent=2, ensure_ascii=False))]


def _error_envelope(tool: str, daw: str, message: str) -> list[TextContent]:
    return _to_content(_envelope(tool=tool, ok=False, daw=daw, error=message))


# ---------- Multi-DAW-Controller-Registry ----------

_controllers: dict[str, ClosedLoopController] = {}
_controllers_lock = asyncio.Lock()


async def _get_controller(daw: str) -> ClosedLoopController:
    """
    Lazy: öffnet MIDI-Ports erst beim ersten Tool-Call für diese DAW.
    Wirft KeyError wenn DAW nicht in DAW_REGISTRY,
    OSError/ValueError wenn Ports nicht existieren / nicht öffnbar sind.
    """
    if daw not in DAW_REGISTRY:
        raise KeyError(f"Unbekannte DAW {daw!r}. Bekannt: {sorted(DAW_REGISTRY.keys())}")
    async with _controllers_lock:
        if daw not in _controllers:
            cfg = DAW_REGISTRY[daw]
            cl = ClosedLoopController(
                listener_port=cfg["listener_port"],
                sender_port=cfg["sender_port"],
                daw=daw,
            )
            cl.start_listening()
            _controllers[daw] = cl
        return _controllers[daw]


def _get_daw_arg(args: dict[str, Any]) -> str:
    """Liest den daw-Parameter aus den Tool-Args, fällt auf DEFAULT_DAW zurück."""
    return args.get("daw") or DEFAULT_DAW


# ---------- Tool-Definitionen ----------

# Convenience: Tools ohne weitere Parameter brauchen nur daw
def _schema_only_daw() -> dict[str, Any]:
    return {
        "type": "object",
        "properties": {"daw": _DAW_PARAM_SCHEMA},
        "additionalProperties": False,
    }


# Tool-Description-Konvention (LLM-readable, eingeführt 2026-05-21 nach Mureka-Lessons-ADR):
#
#   Read-only, zone=green.                                       — no side effects, safe to call freely
#   Zone=yellow (mutates DAW state).                             — changes live DAW state, generally reversible via DAW Undo
#   [DESTRUCTIVE] Zone=red — explicit user intent required.    — irreversible or file-system writing, only on explicit user request
#
# Spezial-Warnings für besonders gefährliche Tools werden in der jeweiligen description ergänzt
# (z.B. "overwrites previous takes", "replaces existing inserts").

_ALL_TOOLS: list[Tool] = [
    Tool(
        name="list_connected_daws",
        description=(
            "Listet alle DAWs in der Registry mit ihren konfigurierten Ports und ob sie "
            "schon initialisiert wurden. Nützlich um zu prüfen, welche Cross-DAW-Operationen "
            "aktuell möglich sind. Read-only, zone=green."
        ),
        inputSchema={"type": "object", "properties": {}, "additionalProperties": False},
    ),
    Tool(
        name="get_daw_state",
        description=(
            "Liefert den kompletten aktuellen DAW-State aus dem State-Mirror — Transport, "
            "Mode, aktive Spur, sichtbare Tracks mit Volume/Mute/Solo/VU, 2-Char-Display, "
            "Timecode. Read-only, zone=green."
        ),
        inputSchema=_schema_only_daw(),
    ),
    Tool(
        name="get_active_track",
        description=(
            "Liefert nur die aktuell aktive Spur mit Index, Name und Status. "
            "Read-only, zone=green."
        ),
        inputSchema=_schema_only_daw(),
    ),
    Tool(
        name="list_tracks",
        description=(
            "Liefert die reduzierte Liste aller 8 sichtbaren Track-Strips der aktuellen "
            "Mackie-Bank. Read-only, zone=green."
        ),
        inputSchema=_schema_only_daw(),
    ),
    Tool(
        name="select_track",
        description=(
            "Selektiert einen Track via Mackie-SELECT-Button (Index 0-7 = Bank-Position). "
            "Closed-Loop-verifiziert. Zone=yellow (mutates DAW state)."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "daw": _DAW_PARAM_SCHEMA,
                "track_index": {
                    "type": "integer",
                    "minimum": 0,
                    "maximum": 7,
                    "description": "Bank-Position 0-7.",
                },
                "timeout_ms": {"type": "integer", "minimum": 100, "maximum": 5000, "default": DEFAULT_TIMEOUT_MS},
            },
            "required": ["track_index"],
            "additionalProperties": False,
        },
    ),
    Tool(
        name="set_mode",
        description=(
            "Wechselt den Mackie-Mode: track | send | pan | plugin | eq | instrument. "
            "Closed-Loop-verifiziert. Zone=yellow (mutates DAW state)."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "daw": _DAW_PARAM_SCHEMA,
                "mode": {
                    "type": "string",
                    "enum": ["track", "send", "pan", "plugin", "eq", "instrument"],
                },
                "timeout_ms": {"type": "integer", "minimum": 100, "maximum": 5000, "default": DEFAULT_TIMEOUT_MS},
            },
            "required": ["mode"],
            "additionalProperties": False,
        },
    ),
    Tool(
        name="force_track_mode",
        description=(
            "Convenience: bringt die DAW in den Track-Mode, damit Track-Namen in LCD-Reihe 1 "
            "stehen. Zone=yellow (mutates DAW state)."
        ),
        inputSchema=_schema_only_daw(),
    ),
    Tool(
        name="transport_play",
        description=(
            "Startet die Wiedergabe via Mackie-PLAY-Button. Closed-Loop-verifiziert. Zone=yellow (mutates DAW state)."
        ),
        inputSchema=_schema_only_daw(),
    ),
    Tool(
        name="transport_stop",
        description=(
            "Stoppt die Wiedergabe via Mackie-STOP-Button. Closed-Loop-verifiziert. Zone=yellow (mutates DAW state)."
        ),
        inputSchema=_schema_only_daw(),
    ),
    Tool(
        name="transport_record",
        description=(
            "Aktiviert Aufnahme-Modus via Mackie-RECORD-Button. "
            "⚠️ Zone=red (destructive, explicit user intent required — starts audio recording, "
            "writes to project folder, can overwrite previous takes if punch-in is armed)."
        ),
        inputSchema=_schema_only_daw(),
    ),
    Tool(
        name="set_track_volume",
        description=(
            "Setzt die Lautstärke einer Spur via Mackie-Pitch-Bend (14-Bit). "
            "Cubase-Quirk: kein Echo zurück → verified=False, nur Send bestätigt. "
            "Ableton echoed pitch_bend in der Regel zurück. Zone=yellow (mutates DAW state)."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "daw": _DAW_PARAM_SCHEMA,
                "track_index": {"type": "integer", "minimum": 0, "maximum": 8},
                "value14": {
                    "type": "integer",
                    "minimum": 0,
                    "maximum": 16383,
                    "description": "14-Bit-Fader-Wert. ~12286 = 0 dB, 0 = -inf, 16383 = +10 dB.",
                },
            },
            "required": ["track_index", "value14"],
            "additionalProperties": False,
        },
    ),
    Tool(
        name="set_track_volume_db",
        description=(
            "Setzt die Lautstärke einer Spur in dB. Konvertiert intern zu 14-Bit-Mackie-"
            "Wert via piecewise-linearer Approximation (0 dB @ value14=12286). "
            "Cubase echoed pitch_bend nicht zurück (verified=false), Ableton in der "
            "Regel schon. Zone=yellow (mutates DAW state). "
            "STC-Pattern: setze dry_run=true fuer Vorschlag-Phase (zeigt geplanten "
            "value14, sendet aber NICHT). Default false."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "daw": _DAW_PARAM_SCHEMA,
                "track_index": {"type": "integer", "minimum": 0, "maximum": 8},
                "db": {
                    "type": "number",
                    "minimum": -144,
                    "maximum": 12,
                    "description": "Ziel-dB. -144 ≈ -inf (Mute), 0 = unity, +10 = max.",
                },
                "dry_run": {"type": "boolean", "default": False, "description": "STC-Vorschlag-Phase: true = nur berechnen, NICHT senden. Default false."},
            },
            "required": ["track_index", "db"],
            "additionalProperties": False,
        },
    ),
    Tool(
        name="bank_left",
        description="Schiebt das Mackie-Display um 8 Tracks zurück. Zone=yellow (mutates DAW state).",
        inputSchema=_schema_only_daw(),
    ),
    Tool(
        name="bank_right",
        description="Schiebt das Mackie-Display um 8 Tracks vor. Zone=yellow (mutates DAW state).",
        inputSchema=_schema_only_daw(),
    ),
    Tool(
        name="channel_left",
        description="Verschiebt die Selektion um 1 Track zurück. Zone=yellow (mutates DAW state).",
        inputSchema=_schema_only_daw(),
    ),
    Tool(
        name="channel_right",
        description="Verschiebt die Selektion um 1 Track vor. Zone=yellow (mutates DAW state).",
        inputSchema=_schema_only_daw(),
    ),
    # ---- AHK-Layer-Tools (Window-Guard + Hotkey-Send) ----
    Tool(
        name="get_active_plugin",
        description=(
            "Liefert das aktuell aktive Plugin im Plugin-Mode der DAW: plugin_name, "
            "track_name, page, page_count, encoders[8] mit Parameter-Namen. Funktioniert "
            "nur, wenn die DAW im Plugin-Mode ist (set_mode 'plugin' vorher). Read-only, "
            "zone=green."
        ),
        inputSchema=_schema_only_daw(),
    ),
    Tool(
        name="plugin_page_next",
        description=(
            "Navigiert auf die nächste Plugin-Parameter-Page (channel_right in Plugin-Mode). "
            "Vorher set_mode('plugin') aufrufen. Zone=yellow (mutates DAW state)."
        ),
        inputSchema=_schema_only_daw(),
    ),
    Tool(
        name="plugin_page_prev",
        description=(
            "Navigiert auf die vorherige Plugin-Parameter-Page (channel_left in Plugin-Mode). "
            "Zone=yellow (mutates DAW state)."
        ),
        inputSchema=_schema_only_daw(),
    ),
    # ---- Session-Logging-Tools ----
    Tool(
        name="start_session_log",
        description=(
            "Aktiviert oder resetet den Event-Log für die DAW. Loggt SELECT, MUTE, SOLO, "
            "REC_ARM, FADER (throttled 250ms), TRANSPORT_CHANGE, MODE_CHANGE. Vorbereitung "
            "für Mix-Reports / Persona Nicker. Zone=green."
        ),
        inputSchema=_schema_only_daw(),
    ),
    Tool(
        name="get_session_summary",
        description=(
            "Liefert aggregierte Übersicht des aktuellen Session-Logs: Counts pro Event-Typ, "
            "Track-Selection-Verlauf, Mode-Wechsel, Transport-Wechsel. Zone=green."
        ),
        inputSchema=_schema_only_daw(),
    ),
    Tool(
        name="get_session_report",
        description=(
            "Rendert das Session-Log als menschen-lesbaren Markdown-Report mit "
            "Aktivitäts-Übersicht, Track-Wechsel-Verlauf, Mode/Transport-History und "
            "Persona-Voice-Quick-Take. Vorbereitung für Persona Nicker. Zone=green."
        ),
        inputSchema=_schema_only_daw(),
    ),
    Tool(
        name="ahk_list_actions",
        description=(
            "Listet alle whitelisted Hotkey-Actions pro DAW (save_project, undo, redo, "
            "export_audio, ...). Read-only, zone=green."
        ),
        inputSchema={
            "type": "object",
            "properties": {"daw": _DAW_PARAM_SCHEMA},
            "additionalProperties": False,
        },
    ),
    # ---------- Persona Sprint A: Mastering-Chain-Advisor ----------
    Tool(
        name="nicker_list_mastering_genres",
        description=(
            "Liefert die verfügbaren Genres für nicker_suggest_mastering_chain mit "
            "Display-Namen, Beschreibung, Natural-LUFS-Targets und Charakter-Fokus. "
            "Wissensbasis: YMP/Studium/21_Mastering_Finalizing.md. Read-only, zone=green."
        ),
        inputSchema={"type": "object", "properties": {}, "additionalProperties": False},
    ),
    Tool(
        name="nicker_list_mastering_platforms",
        description=(
            "Liefert die verfügbaren Plattformen für nicker_suggest_mastering_chain "
            "(Spotify, Apple Music, YouTube, Tidal, SoundCloud, Club/DJ, Vinyl, CD-Redbook) "
            "mit Target-LUFS, True-Peak-Limit und Normalisierungs-Verhalten. Read-only, zone=green."
        ),
        inputSchema={"type": "object", "properties": {}, "additionalProperties": False},
    ),
    Tool(
        name="nicker_suggest_mastering_chain",
        description=(
            "Liefert eine strukturierte Mastering-Chain-Empfehlung für (Genre × Plattform): "
            "aufgelöste Chain-Steps (generic_chain mit Genre-Overrides), Loudness-Strategie "
            "(delta_db zwischen Genre-Natural und Plattform-Target + Klartext-Empfehlung), "
            "Warnungen, Reference-Artists. Wissensbasis: YMP/Studium/21_Mastering_Finalizing.md. "
            "Read-only, zone=green."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "genre": {
                    "type": "string",
                    "description": "Genre-ID, z. B. 'techno', 'psy_ambient', 'classical_acoustic', 'pop_rock', 'hiphop_trap', 'drum_and_bass', 'breakbeat', 'britcore', 'trip_hop', 'rap', 'progressive_trance', 'psytrance', 'dub_techno'. Liste via nicker_list_mastering_genres.",
                },
                "platform": {
                    "type": "string",
                    "default": "spotify",
                    "description": "Plattform-ID, z. B. 'spotify', 'apple_music', 'youtube', 'tidal', 'soundcloud', 'club_dj', 'vinyl', 'cd_redbook'. Liste via nicker_list_mastering_platforms. Default: spotify.",
                },
            },
            "required": ["genre"],
            "additionalProperties": False,
        },
    ),
    # ---------- YMP-Studium-Wissensbasis (Block C, operationalisiert) ----------
    Tool(
        name="nicker_list_studium_docs",
        description=(
            "Listet alle YMP-Studium-Dokumente mit Metadaten (ymp_id, Titel, Kategorie, "
            "Tags, Größe). Optional Filter nach Kategorie ('foundation', 'daw_tools', "
            "'production_craft', 'uncategorized'). Wissensbasis: YMP/Studium/. "
            "Read-only, zone=green."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "category": {
                    "type": "string",
                    "enum": ["foundation", "daw_tools", "production_craft", "uncategorized"],
                    "description": "Optional auf eine Kategorie filtern.",
                },
            },
            "additionalProperties": False,
        },
    ),
    Tool(
        name="nicker_search_studium",
        description=(
            "Keyword-Suche über alle YMP-Studium-Dokumente. Liefert top_k Treffer "
            "mit Score (Titel ×10, Tags ×5, Body ×1) und Snippet (Body-Kontext um den "
            "ersten Treffer). Wissensbasis-Vorrang (D2 in persona_nicker_detail_spec). "
            "Read-only, zone=green."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Suchbegriff(e), durch Whitespace getrennt.",
                },
                "top_k": {
                    "type": "integer",
                    "default": 5,
                    "minimum": 1,
                    "maximum": 20,
                    "description": "Maximale Anzahl Treffer (Default: 5).",
                },
            },
            "required": ["query"],
            "additionalProperties": False,
        },
    ),
    Tool(
        name="nicker_get_studium_doc",
        description=(
            "Liefert ein einzelnes YMP-Studium-Dokument per ymp_id. Mit "
            "include_body=true wird ein Body-Excerpt (Default 2000 Char, "
            "max_chars=0 = vollständig) zurückgegeben. Wenn nur Metadaten gewollt: "
            "include_body=false. Wissensbasis: YMP/Studium/. Read-only, zone=green."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "ymp_id": {
                    "type": "integer",
                    "description": "Numerische ID aus dem Datei-Präfix (z. B. 21 für Mastering).",
                },
                "include_body": {
                    "type": "boolean",
                    "default": False,
                    "description": "Body-Text mit zurückgeben? Default: false (nur Metadaten).",
                },
                "max_chars": {
                    "type": "integer",
                    "default": 2000,
                    "minimum": 0,
                    "maximum": 100000,
                    "description": "Maximale Zeichen im Body-Excerpt. 0 = vollständig (Vorsicht: Token-Last). Default: 2000.",
                },
            },
            "required": ["ymp_id"],
            "additionalProperties": False,
        },
    ),
    # ---------- Sprint E1: Audio-Analytics-Layer ----------
    Tool(
        name="nicker_analyze_audio_file",
        description=(
            "Misst eine Audio-Datei (WAV/FLAC/AIFF) deterministisch: Peak, RMS, "
            "LUFS-Integrated, LUFS-Short-Term-Max, True-Peak (4× Oversampling), "
            "Spektrum-Bänder (sub/low/mid/high/air), Stereo-Korrelation, Mono-"
            "Kompatibilität. ITU BS.1770-konform via pyloudnorm. Read-only, zone=green."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "Absoluter oder relativer Pfad zur Audio-Datei.",
                },
            },
            "required": ["path"],
            "additionalProperties": False,
        },
    ),
    Tool(
        name="nicker_audit_audio_file",
        description=(
            "Analysiert eine Audio-Datei und liefert einen strukturierten Audit-"
            "Bericht gegen YMP-Genre/Platform-Targets. Findings klassifiziert nach "
            "critical / suggestive / observation. Prüft Headroom, LUFS, True-Peak, "
            "Stereo-Mono-Kompatibilität, Spektrum-Balance vs. Genre-Charakter. "
            "Read-only, zone=green."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "Pfad zur Audio-Datei.",
                },
                "genre": {
                    "type": "string",
                    "description": "Genre-ID (z. B. 'trip_hop'). Optional. Liste via nicker_list_mastering_genres.",
                },
                "platform": {
                    "type": "string",
                    "default": "spotify",
                    "description": "Plattform-ID (Default: spotify). Liste via nicker_list_mastering_platforms.",
                },
            },
            "required": ["path"],
            "additionalProperties": False,
        },
    ),
    Tool(
        name="nicker_suggest_track_settings",
        description=(
            "Leitet aus Audio-Mess-Daten + Track-Rolle + Genre konkrete Plugin-"
            "Setting-VORSCHLÄGE als Pre-Settings ab (HP, EQ, Compressor, De-Esser, "
            "Saturation, Limiter wenn master). NICHT zum direkten Drücken — Yoka "
            "prüft und justiert. Track-Rollen via nicker_list_track_roles. "
            "Read-only, zone=green."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "Pfad zur Audio-Datei (Stem oder Track-Bounce).",
                },
                "track_role": {
                    "type": "string",
                    "enum": ["drums", "bass", "harmonic", "acoustic_guitar", "vocal_lead", "vocal_backing", "master"],
                    "description": "Rolle der Spur im Mix.",
                },
                "genre": {
                    "type": "string",
                    "description": "Genre-ID (z. B. 'trip_hop'). Optional aber empfohlen für Genre-Overrides.",
                },
                "platform": {
                    "type": "string",
                    "default": "spotify",
                    "description": "Plattform-ID, nur relevant wenn track_role='master' (für Limiter-Target).",
                },
            },
            "required": ["path", "track_role"],
            "additionalProperties": False,
        },
    ),
    Tool(
        name="nicker_list_track_roles",
        description=(
            "Listet die unterstützten Track-Rollen (drums, bass, harmonic, "
            "acoustic_guitar, vocal_lead, vocal_backing, master) mit Default-HP-"
            "Cutoff und Default-Compressor-Ratio. Read-only, zone=green."
        ),
        inputSchema={"type": "object", "properties": {}, "additionalProperties": False},
    ),
    Tool(
        name="nicker_compare_audio_files",
        description=(
            "A/B-Vergleich zweier Audio-Dateien (eigener Mix vs. Reference-Track). "
            "Liefert numerische Deltas pro Feld (Loudness, Spektrum-Bänder, Stereo) "
            "plus Similarity-Score (0..1) und Klartext-Notizen ('A ist 3 dB lauter', "
            "'B hat mehr Air-Band'). Sprint F. Read-only, zone=green."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "path_a": {"type": "string", "description": "Pfad zur ersten Audio-Datei (z. B. eigener Mix)."},
                "path_b": {"type": "string", "description": "Pfad zur zweiten Audio-Datei (z. B. Reference-Track)."},
            },
            "required": ["path_a", "path_b"],
            "additionalProperties": False,
        },
    ),
    # ---------- Sprint G: Reaction-Tagging-Layer (Yoka als Feedback-Geber) ----------
    Tool(
        name="nicker_log_reaction",
        description=(
            "Loggt einen Reaction-Tag während Hör-Sessions in JSONL-Datei. "
            "Personal-Tags: g (Gänsehaut), k (kribbelt), a (abstoßend), n (neutral), "
            "l (langweilig), t (Träne/bewegt), e (euphorisch), f (Flow), u (ungeduldig), "
            "z (Zorn). Crowd-Tags: tanzflaeche_ausgerastet, gejubelt, mitgesungen, "
            "pause_genutzt, verlassen, stillgestanden, tanzpaare_gebildet. Mit "
            "with_daw_snapshot=true wird der aktuelle DAW-State automatisch mit "
            "gespeichert (Plugin, Track, Mode). Sprint G MVP — Layer 8 Wahrnehmungs-"
            "modell-Trainings-Daten. Zone=green (Logging-only)."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "tag": {
                    "type": "string",
                    "description": "Tag aus PERSONAL_TAGS oder CROWD_TAGS, oder eigenes Wort (mode=unknown).",
                },
                "note": {
                    "type": "string",
                    "description": "Optionale Notiz / Kontext-Beschreibung.",
                },
                "audio_position_s": {
                    "type": "number",
                    "description": "Audio-Position in Sekunden falls relevant.",
                },
                "track_name": {
                    "type": "string",
                    "description": "Track-Name (für Auswertung pro Track).",
                },
                "with_daw_snapshot": {
                    "type": "boolean",
                    "default": False,
                    "description": "Aktuellen DAW-State (mode, active_track, active_plugin) automatisch mit-loggen.",
                },
                "daw": {
                    "type": "string",
                    "default": "cubase",
                    "description": "DAW für den Snapshot (relevant nur bei with_daw_snapshot=true).",
                },
                "session_id": {
                    "type": "string",
                    "description": "Optionale Session-ID zur Gruppierung.",
                },
                "person_id": {
                    "type": "string",
                    "default": "P01",
                    "description": "Person-ID (Default: P01 = Yoka).",
                },
            },
            "required": ["tag"],
            "additionalProperties": False,
        },
    ),
    Tool(
        name="nicker_reaction_summary",
        description=(
            "Aggregiert das Reaction-Log: Counts pro Tag, pro Person, pro Modus, plus "
            "Top-Tracks nach Reaktionen mit Tag-Breakdown. Optional Filter nach person_id, "
            "mode (personal/crowd/unknown), session_id. Read-only, zone=green."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "person_id": {"type": "string", "description": "Filter auf bestimmte Person."},
                "mode": {"type": "string", "enum": ["personal", "crowd", "unknown"], "description": "Filter auf Modus."},
                "session_id": {"type": "string", "description": "Filter auf Session-ID."},
            },
            "additionalProperties": False,
        },
    ),
    Tool(
        name="nicker_list_reaction_tags",
        description=(
            "Liefert die definierten Tag-Vokabulare (personal + crowd) mit Display-Namen "
            "und den Log-File-Pfad. Hilfreich für UI/Hotkey-Mapping. Read-only, zone=green."
        ),
        inputSchema={"type": "object", "properties": {}, "additionalProperties": False},
    ),
    # ---------- Sprint B: Frequenz-Advisor ----------
    Tool(
        name="nicker_freq_advice",
        description=(
            "Liefert pro Track-Rolle (kick, snare, bass, vocal_lead, etc.) "
            "strukturierte Frequenz-Empfehlungen: Core-Zonen mit Cuts/Boosts, Problem-"
            "Zonen mit Lösungen, High-Pass-Cutoff, Masking-Konflikte, plus globale "
            "Hör-Regeln (Solo vs. Context, Fletcher-Munson) und Sweep-Technique. "
            "Wissensbasis: YMP/Studium/35_EQ_Frequency_Management.md. Read-only, zone=green."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "track_role": {
                    "type": "string",
                    "description": "Track-Rolle, z. B. 'kick', 'snare', 'bass', '808_sub', 'vocal_lead', 'vocal_backing', 'acoustic_guitar', 'e_guitar', 'synth_lead', 'synth_pad', 'tom', 'hihat', 'drums_group', 'harmonic_other', 'master_bus'. Liste via nicker_list_freq_track_roles.",
                },
            },
            "required": ["track_role"],
            "additionalProperties": False,
        },
    ),
    Tool(
        name="nicker_list_freq_track_roles",
        description=(
            "Listet alle unterstützten Track-Rollen für nicker_freq_advice mit Display-"
            "Namen + Anzahl Core/Problem-Zonen. Read-only, zone=green."
        ),
        inputSchema={"type": "object", "properties": {}, "additionalProperties": False},
    ),
    Tool(
        name="nicker_find_masking_conflicts",
        description=(
            "Liefert die Tracks mit denen eine Track-Rolle Frequenz-Konflikte hat "
            "(bidirektional erkannt) plus Lösungs-Strategien (Complementary EQ, "
            "Frequency Niche, Dynamic EQ, Sidechain Compression). Read-only, zone=green."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "track_role": {
                    "type": "string",
                    "description": "Track-Rolle für die Konflikt-Analyse.",
                },
            },
            "required": ["track_role"],
            "additionalProperties": False,
        },
    ),
    Tool(
        name="save_project",
        description=(
            "Speichert das Projekt in der angegebenen DAW (Hotkey Ctrl+S, mit Window-"
            "Guard). Schreibt Datei auf Disk. Zone=red — explizite Intent erforderlich."
        ),
        inputSchema=_schema_only_daw(),
    ),
    Tool(
        name="undo",
        description="Macht die letzte Aktion in der DAW rückgängig (Ctrl+Z). Zone=yellow (mutates DAW state).",
        inputSchema=_schema_only_daw(),
    ),
    Tool(
        name="redo",
        description="Wiederholt die letzte rückgängig gemachte Aktion (Ctrl+Shift+Z). Zone=yellow (mutates DAW state).",
        inputSchema=_schema_only_daw(),
    ),
    Tool(
        name="ahk_send_action",
        description=(
            "Generischer Aufruf für eine whitelisted Hotkey-Action. Action muss in der "
            "DAW-Whitelist sein (siehe ahk_list_actions). Zone=red für destruktive Actions, "
            "yellow für nicht-destruktive — der Aufrufer ist verantwortlich für die Klassifizierung."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "daw": _DAW_PARAM_SCHEMA,
                "action": {
                    "type": "string",
                    "description": "Action-Name aus der DAW-Whitelist (z. B. 'save_project_as', 'export_audio').",
                },
                "restore_focus": {
                    "type": "boolean",
                    "default": False,
                    "description": "Ob nach dem Send der vorherige Fokus wiederhergestellt werden soll.",
                },
            },
            "required": ["action"],
            "additionalProperties": False,
        },
    ),
    # ---- Sprint D: MIDI-CC-Send fuer Plugin-Parameter-Steuerung ----
    Tool(
        name="nicker_send_midi_cc",
        description=(
            "Sendet eine MIDI-Control-Change-Nachricht an einen loopMIDI-Port. "
            "Default-Port: XBOARD_BRIDGED (von Cubase als MIDI-Input verbunden). "
            "Plugin muss vorher per MIDI Learn auf den CC trainiert sein. "
            "Zone=yellow — schreibender Eingriff in DAW-Plugin-State. "
            "POC-validiert 2026-05-06 mit FabFilter Pro-MB auf Bass-Gruppe."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "cc": {
                    "type": "integer",
                    "minimum": 0,
                    "maximum": 127,
                    "description": "MIDI-CC-Nummer (0-127). Yokas Setup nutzt typisch CC 21+ fuer Plugin-Learns.",
                },
                "value": {
                    "type": "integer",
                    "minimum": 0,
                    "maximum": 127,
                    "description": "CC-Wert (0-127). 0=Plugin-Param-Min, 127=Max, 64=Mitte.",
                },
                "port": {
                    "type": "string",
                    "default": "XBOARD_BRIDGED",
                    "description": "loopMIDI-Output-Port. Substring-Match unterstuetzt.",
                },
                "channel": {
                    "type": "integer",
                    "minimum": 0,
                    "maximum": 15,
                    "default": 0,
                    "description": "MIDI-Kanal (0-15, entspricht Kanal 1-16 in DAW-Anzeige). Konvention: Kanal 0/1=Bass, 1/2=Drums, 2/3=Vocal, 3/4=Synth, 4/5=Master.",
                },
            },
            "required": ["cc", "value"],
            "additionalProperties": False,
        },
    ),
    Tool(
        name="nicker_send_midi_cc_pct",
        description=(
            "Sendet MIDI-CC mit Ziel-Wert in Prozent (0.0-100.0). Konvertiert intern "
            "auf CC-Wert 0-127. Komfort-Wrapper fuer 'setze Plugin-Param auf 50%' "
            "ohne dass Aufrufer Range kennen muss. Zone=yellow (mutates DAW state)."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "cc": {"type": "integer", "minimum": 0, "maximum": 127},
                "value_pct": {
                    "type": "number",
                    "minimum": 0.0,
                    "maximum": 100.0,
                    "description": "Ziel-Wert in Prozent (0-100).",
                },
                "port": {"type": "string", "default": "XBOARD_BRIDGED"},
                "channel": {"type": "integer", "minimum": 0, "maximum": 15, "default": 0},
            },
            "required": ["cc", "value_pct"],
            "additionalProperties": False,
        },
    ),
    Tool(
        name="nicker_send_midi_cc_range",
        description=(
            "Sendet MIDI-CC mit Ziel-Wert in einer beliebigen Range (z.B. -60 bis 0 dB "
            "fuer Compressor-Threshold). Berechnet intern den passenden CC-Wert 0-127. "
            "Beispiel: target_value=-18 dB in range [-60, 0] -> CC-Wert 89. Zone=yellow (mutates DAW state)."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "cc": {"type": "integer", "minimum": 0, "maximum": 127},
                "target_value": {
                    "type": "number",
                    "description": "Ziel-Wert in der Plugin-Param-Range.",
                },
                "range_min": {
                    "type": "number",
                    "description": "Range-Minimum (entspricht CC-Wert 0).",
                },
                "range_max": {
                    "type": "number",
                    "description": "Range-Maximum (entspricht CC-Wert 127). Darf kleiner sein als range_min fuer invertierte Mappings.",
                },
                "port": {"type": "string", "default": "XBOARD_BRIDGED"},
                "channel": {"type": "integer", "minimum": 0, "maximum": 15, "default": 0},
            },
            "required": ["cc", "target_value", "range_min", "range_max"],
            "additionalProperties": False,
        },
    ),
    Tool(
        name="nicker_set_plugin_param",
        description=(
            "Setzt einen Plugin-Parameter BY NAME per MIDI-CC — Cubase-Stock UND "
            "Drittanbieter (129 Plugins gescannt), OHNE plugin-internes MIDI-Learn. "
            "Loest (plugin, param) ueber cubase_value_cc_map.json zu einer CC auf und "
            "sendet an Port AI_VAL. Adressierung: channel = insert_slot (0-7) der "
            "SELEKTIERTEN Spur, cc = Parameter-Index, value 0-127 = Param-Min..Max. "
            "Voraussetzung: loopMIDI-Port AI_VAL + ki_studio_value_remote.js aktiv in "
            "Cubase; das Plugin liegt auf insert_slot der aktuell selektierten Spur. "
            "param matcht role ('band1_gain'), title ('1 Gain') oder Param-Index. "
            "Zone=yellow — schreibender Eingriff in Plugin-State."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "plugin": {
                    "type": "string",
                    "description": "Plugin-Name (object_title), z.B. 'StudioEQ', 'Frequency', 'Blackhole'. Exakt (case-insensitiv) oder eindeutiger Substring.",
                },
                "param": {
                    "type": "string",
                    "description": "Parameter: role ('band1_gain'), title ('1 Gain') oder Param-Index ('1').",
                },
                "value": {
                    "type": "integer", "minimum": 0, "maximum": 127,
                    "description": "CC-Wert 0-127 (0=Min, 64=Mitte, 127=Max).",
                },
                "insert_slot": {
                    "type": "integer", "minimum": 0, "maximum": 7, "default": 0,
                    "description": "Insert-Slot 0-7 der selektierten Spur (= MIDI-Channel). Default 0 = Insert 1.",
                },
            },
            "required": ["plugin", "param", "value"],
            "additionalProperties": False,
        },
    ),
    # ---- Voll-Command-Zugriff via MIDI Remote (jenseits Hotkey-Limit) ----
    Tool(
        name="send_cubase_command",
        description=(
            "Triggert EINEN beliebigen Cubase-Command per Name — auch die ~1559 "
            "ungebundenen, die nicht in den Hotkey-Raum passen. Loest command_name "
            "ueber das versionierte Mapping (cubase_command_midi_map.json) zu einer "
            "eindeutigen (channel, cc) auf und sendet einen Button-Press-CC (127) an "
            "Port AI_CMD. Cubases MIDI-Remote-Script (ki_studio_command_remote.js) "
            "faengt den CC ab und fuehrt den Host-Command aus. "
            "Voraussetzung: loopMIDI-Port AI_CMD existiert + Script in Cubase aktiv. "
            "command_name: bevorzugt 'Category/Command' (eindeutig), sonst eindeutiger "
            "Slug oder eindeutiger Command-Name. Mehrdeutig -> Fehler mit Kandidaten. "
            "Zone=yellow — fuehrt eine DAW-Aktion aus. Fuer bereits per Hotkey "
            "gebundene Commands stattdessen ahk_send_action nutzen."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "command_name": {
                    "type": "string",
                    "description": (
                        "Command-Bezeichnung. Bevorzugt 'Category/Command' "
                        "(z.B. 'Audio/Bounce'). Auch eindeutiger Slug oder Command-Name."
                    ),
                },
                "port": {
                    "type": "string",
                    "description": "Optionaler Port-Override. Default: AI_CMD (aus Mapping).",
                },
            },
            "required": ["command_name"],
            "additionalProperties": False,
        },
    ),
    Tool(
        name="send_midi_note",
        description=(
            "Sendet einen MIDI-Akkord an einen loopMIDI-Port: alle Notes gleichzeitig Note-On, "
            "wartet duration_ms, dann alle Note-Off. Brueckt die Luecke zwischen CC (Plugin-Params) "
            "und tatsaechlichen Toenen. Use-Case: Cubase-Instrument-Track scharfgeschaltet auf Recording "
            "mit Input=loopMIDI-Port -> Noten werden aufgenommen + Instrument spielt. "
            "C4=60, C-Dur-Akkord = [60, 64, 67]. Blockt fuer duration_ms (max 30000ms). "
            "Zone=yellow — schreibt MIDI-Daten in die DAW wenn Track armed."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "notes": {
                    "type": "array",
                    "items": {"type": "integer", "minimum": 0, "maximum": 127},
                    "minItems": 1,
                    "description": "MIDI-Notennummern (0-127). C4=60, A4=69. Mehrere = Akkord.",
                },
                "duration_ms": {
                    "type": "integer",
                    "minimum": 1,
                    "maximum": 30000,
                    "default": 500,
                    "description": "Wie lange die Noten gehalten werden (1-30000ms). Default 500.",
                },
                "velocity": {
                    "type": "integer",
                    "minimum": 0,
                    "maximum": 127,
                    "default": 80,
                    "description": "Note-On-Velocity (0-127). Default 80 (mittel).",
                },
                "port": {
                    "type": "string",
                    "default": "AI_INPUT",
                    "description": "loopMIDI-Output-Port. Default AI_INPUT (Cubase-Recording-Input).",
                },
                "channel": {
                    "type": "integer",
                    "minimum": 0,
                    "maximum": 15,
                    "default": 0,
                    "description": "MIDI-Kanal (0-15 = Kanal 1-16 in DAW). Default 0.",
                },
            },
            "required": ["notes"],
            "additionalProperties": False,
        },
    ),
    Tool(
        name="send_midi_note_sequence",
        description=(
            "Spielt eine Melodie sequenziell: Note 1 fuer note_duration_ms, gap_ms Pause, Note 2, ... "
            "Blockt fuer (note_duration_ms + gap_ms) * len(notes) — max 30000ms gesamt. "
            "Use-Case: schnelle Tonleiter-Demo, einfache Motive. Fuer komplexe Patterns "
            "bitte mehrere send_midi_note-Calls. Zone=yellow."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "notes": {
                    "type": "array",
                    "items": {"type": "integer", "minimum": 0, "maximum": 127},
                    "minItems": 1,
                    "description": "MIDI-Notennummern in Reihenfolge.",
                },
                "note_duration_ms": {
                    "type": "integer",
                    "minimum": 1,
                    "maximum": 5000,
                    "default": 250,
                    "description": "Laenge jeder Note in ms.",
                },
                "gap_ms": {
                    "type": "integer",
                    "minimum": 0,
                    "maximum": 5000,
                    "default": 50,
                    "description": "Pause zwischen Noten in ms.",
                },
                "velocity": {
                    "type": "integer", "minimum": 0, "maximum": 127, "default": 80,
                },
                "port": {"type": "string", "default": "AI_INPUT"},
                "channel": {"type": "integer", "minimum": 0, "maximum": 15, "default": 0},
            },
            "required": ["notes"],
            "additionalProperties": False,
        },
    ),
    Tool(
        name="nicker_list_midi_ports",
        description=(
            "Listet alle verfuegbaren MIDI-Output-Ports (loopMIDI + Hardware). "
            "Hilfreich fuer Debugging und Konfiguration. Read-only, zone=green."
        ),
        inputSchema={"type": "object", "properties": {}, "additionalProperties": False},
    ),
    # ---- Sprint D: High-Level Plugin-Control (Tier-1) ----
    Tool(
        name="nicker_set_pro_q3_band",
        description=(
            "Setzt mehrere Parameter eines FabFilter Pro-Q3-Bandes in einem Aufruf. "
            "KI nennt konkrete Werte (Hz/dB/Q/Filter-Type), Tool berechnet CC-Werte "
            "automatisch und sendet sequenziell. Nutzt midi_channel_layout.json fuer "
            "Range-Mapping. Zone=yellow (mutates DAW state). "
            "STC-Pattern: setze dry_run=true fuer Vorschlag-Phase (zeigt geplante CCs, "
            "sendet aber NICHT). Default false (= direkt anwenden)."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "bus": {
                    "type": "string",
                    "enum": ["bass", "drums", "synth", "vocals", "other", "guitar", "percussions", "backing_vocals", "master"],
                    "description": "Ziel-Bus (Kanal-Konvention: bass=1, drums=2, ..., master=16).",
                },
                "band_num": {"type": "integer", "minimum": 1, "maximum": 3, "description": "Band-Nummer (1-3)."},
                "freq_hz": {"type": "number", "minimum": 10, "maximum": 30000, "description": "Frequenz in Hz (log-mapped)."},
                "gain_db": {"type": "number", "minimum": -30, "maximum": 30, "description": "Gain in dB."},
                "q": {"type": "number", "minimum": 0.025, "maximum": 40, "description": "Q-Faktor."},
                "shape": {
                    "type": "string",
                    "enum": ["Bell", "Low Cut", "Low Shelf", "Notch", "High Cut", "High Shelf", "Band Pass", "Tilt Shelf", "Flat Tilt"],
                    "description": "Filter-Type. Pro-Q3 hat 9 Typen.",
                },
                "slope": {
                    "type": "number",
                    "enum": [6, 12, 18, 24, 36, 48, 72, 96],
                    "description": "Slope in dB/oct (nur fuer Cut/Shelf-Filter relevant).",
                },
                "enabled": {"type": "boolean", "description": "Band an/aus."},
                "port": {"type": "string", "default": "AI_INPUT"},
                "dry_run": {"type": "boolean", "default": False, "description": "STC-Vorschlag-Phase: true = nur berechnen, NICHT senden. Default false."},
            },
            "required": ["bus", "band_num"],
            "additionalProperties": False,
        },
    ),
    Tool(
        name="nicker_set_pro_c2",
        description=(
            "Setzt FabFilter Pro-C 2 Compressor-Parameter in einem Aufruf. "
            "Threshold/Ratio/Attack/Release plus Wet/Dry Gain. KI gibt konkrete Werte, "
            "Tool berechnet CCs (CC48-57) und sendet an passenden Bus-Kanal. Zone=yellow (mutates DAW state). "
            "STC-Pattern: setze dry_run=true fuer Vorschlag-Phase (zeigt geplante CCs, "
            "sendet aber NICHT). Default false."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "bus": {"type": "string", "enum": ["bass", "drums", "synth", "vocals", "other", "guitar", "percussions", "backing_vocals", "master"]},
                "threshold_db": {"type": "number", "minimum": -60, "maximum": 0},
                "ratio": {"type": "number", "minimum": 1, "maximum": 99},
                "attack_ms": {"type": "number", "minimum": 0.05, "maximum": 500},
                "release_ms": {"type": "number", "minimum": 5, "maximum": 3000},
                "knee_db": {"type": "number", "minimum": 0, "maximum": 72},
                "range_db": {"type": "number", "minimum": 0, "maximum": 60},
                "lookahead_ms": {"type": "number", "minimum": 0, "maximum": 20},
                "hold_ms": {"type": "number", "minimum": 0, "maximum": 500},
                "wet_gain_db": {"type": "number", "minimum": -36, "maximum": 36},
                "dry_gain_db": {"type": "number", "minimum": -36, "maximum": 36, "description": "Fuer Parallel-Comp NY-Style."},
                "port": {"type": "string", "default": "AI_INPUT"},
                "dry_run": {"type": "boolean", "default": False, "description": "STC-Vorschlag-Phase: true = nur berechnen, NICHT senden. Default false."},
            },
            "required": ["bus"],
            "additionalProperties": False,
        },
    ),
    Tool(
        name="nicker_apply_preset",
        description=(
            "Wendet ein fertiges Mix-Preset aus mix_presets.json an. Sendet alle CCs "
            "fuer Pro-Q3 + Pro-C 2 in einem Rutsch an den passenden Bus. "
            "Presets sind datenbasiert (z.B. triphop_bass_default aus Stem-Analyse). "
            "Read mix_presets.json fuer Inhalt. "
            "[OVERWRITES] Zone=yellow — mutates DAW state, overwrites current EQ + Comp "
            "settings on the target bus; previous values are not preserved, use DAW Undo to revert. "
            "STC-Pattern (empfohlen vor Preset-Apply): setze dry_run=true fuer Vorschlag, "
            "praesentiere User die geplanten CCs, dann erneut mit dry_run=false (= default) anwenden."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "preset_id": {"type": "string", "description": "z.B. 'triphop_bass_default', 'master_bus_streaming', 'bypass_all_bass'."},
                "bus": {"type": "string", "description": "Optional: ueberschreibt default_bus aus Preset.", "enum": ["bass", "drums", "synth", "vocals", "other", "guitar", "percussions", "backing_vocals", "master"]},
                "port": {"type": "string", "default": "AI_INPUT"},
                "dry_run": {"type": "boolean", "default": False, "description": "STC-Vorschlag-Phase: true = nur berechnen aller CCs des Presets, NICHT senden. Default false."},
            },
            "required": ["preset_id"],
            "additionalProperties": False,
        },
    ),
    Tool(
        name="nicker_list_mix_presets",
        description=(
            "Listet alle verfuegbaren Mix-Presets aus mix_presets.json mit Display-Name, "
            "Kategorie und Beschreibung. Optional Filter nach Kategorie. Read-only, zone=green."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "category": {
                    "type": "string",
                    "enum": ["bass", "drums", "synth", "vocals", "backing_vocals", "percussions", "other", "guitar", "master"],
                    "description": "Optional: nur Presets dieser Kategorie.",
                },
            },
            "additionalProperties": False,
        },
    ),
    # ---- Plugin-Registry (Markt-Scan-Pattern, Context-Window-Loesung, 2026-05-21) ----
    Tool(
        name="nicker_lookup_plugin",
        description=(
            "Sucht in Yokas 321-Plugin-Inventar (Cubase-Report + KI-Anreicherung). "
            "Loest das Context-Window-Problem: statt alle Plugins im System-Prompt "
            "zu listen, gezielter Lookup mit Free-Text-Query + Filter. Joined "
            "yoka_plugins.json (Roh) mit plugin_tags.json (Tags/Use-Cases/Lizenz). "
            "Default license_active_only=True blockiert Antares-Demo-Suite. "
            "Read-only, zone=green."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Free-text. Matched gegen Name/Vendor/Tags/Use-Cases/Notes. Beispiel: 'warm bass compressor'."},
                "category": {"type": "string", "description": "Cubase-Kategorie-Substring (case-insensitive): 'EQ', 'Dynamics', 'Reverb', 'Delay', 'Modulation', 'Pitch Shift', 'Distortion', 'Restoration', 'Mastering', 'Synth', 'Spatial'."},
                "manufacturer": {"type": "string", "description": "Vendor-Substring (case-insensitive): 'FabFilter', 'iZotope', 'Valhalla', 'Eventide', 'Mastering the Mix', ..."},
                "use_case": {"type": "string", "description": "Exact Tag-Match aus plugin_tags.json. Beispiele: 'bass_glue', 'vocal_compression', 'master_limiter', 'corrective_eq', 'vocal_tuning'."},
                "sound_tag": {"type": "string", "description": "Exact Tag-Match. Beispiele: 'warm', 'vintage', 'transparent', 'surgical', 'character', 'modern'."},
                "with_cc_mapping_only": {"type": "boolean", "default": False, "description": "True = nur KI-MIDI-steuerbare Plugins (aktuell Pro-Q3, Pro-C 2, Saturn 2)."},
                "license_active_only": {"type": "boolean", "default": True, "description": "True (default) = blockiert demo_expired-Plugins (Antares-Suite)."},
                "limit": {"type": "integer", "default": 10, "minimum": 1, "maximum": 50},
            },
            "additionalProperties": False,
        },
    ),
    Tool(
        name="nicker_get_plugin_details",
        description=(
            "Voll-Datensatz fuer ein bekanntes Plugin (Name muss exact matchen). "
            "Liefert Vendor, Type, Tags, Use-Cases, CC-Mapping-Ref, License-Status, Notes. "
            "Liefert null wenn Name nicht im Inventar. Read-only, zone=green."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "Plugin-Name. Exact match mit yoka_plugins.json (case-sensitive). Beispiel: 'FabFilter Pro-Q 3' (mit Leerzeichen!), 'ValhallaVintageVerb' (zusammen)."},
            },
            "required": ["name"],
            "additionalProperties": False,
        },
    ),
    Tool(
        name="nicker_plugin_registry_stats",
        description=(
            "Sanity-Stats der Plugin-Registry: tagged vs. untagged Plugins, License-Verteilung, "
            "KI-Role-Verteilung, CC-Mapping-Coverage. Hilfreich um zu sehen wie vollstaendig "
            "die Anreicherung ist. Read-only, zone=green."
        ),
        inputSchema={"type": "object", "properties": {}, "additionalProperties": False},
    ),
    Tool(
        name="nicker_sync_plugins_from_cubase",
        description=(
            "Synct die Nicker-Plugin-Registry (yoka_plugins.json) gegen Cubase's native "
            "VstPlugInfoV4.xml (VST3) + Vst2xPlugin Infos Cubase.xml (VST2). Default = dry-run: "
            "liefert nur Diff (to_add / to_update / to_remove). Mit apply=True schreibt es die "
            "Registry und legt vorher ein .backup_YYYY-MM-DD an. Handgepflegte Felder "
            "(vendor/type/version + plugin_tags.json) bleiben unangetastet — XML liefert nur "
            "technische Felder (uid, bus-counts, latency, sidechain_bus, flags-raw). "
            "Matching: UID Primary Key, Name Fallback. to_remove wird nur reported, NIEMALS "
            "auto-geloescht (ausser remove_stale=True). zone=yellow (Filesystem-Write nur bei apply)."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "apply": {"type": "boolean", "default": False,
                          "description": "True = schreibt yoka_plugins.json (mit Backup). False (default) = dry-run."},
                "remove_stale": {"type": "boolean", "default": False,
                                 "description": "True = entfernt Registry-Eintraege die nicht mehr im XML sind. Default: nur reporten."},
                "vst3_xml_path": {"type": "string",
                                  "description": "Optional override fuer VstPlugInfoV4.xml. Default: %APPDATA%/Steinberg/Cubase 15_64/VstPlugInfoV4.xml."},
                "vst2_xml_path": {"type": "string",
                                  "description": "Optional override fuer Vst2xPlugin Infos Cubase.xml."},
            },
            "additionalProperties": False,
        },
    ),

    # ---- Audio-Helper (Quick-Win 2 nach Mureka-Lessons-ADR, 2026-05-21) ----
    Tool(
        name="play_audio_file",
        description=(
            "Spielt eine lokale Audio-Datei (WAV/MP3/M4A/FLAC/AIFF/OGG) auf dem aktuellen "
            "Rechner ab. Cross-platform: Mac (afplay), Win (winsound für WAV, PowerShell "
            "MediaPlayer für MP3), Linux (paplay/mpg123). Default blocking — wartet auf "
            "Playback-Ende bevor das Tool returned, damit das LLM den nächsten Schritt "
            "nach gehörtem Resultat planen kann (analog Mureka-Pattern). "
            "Use-Cases: nach Bounce/Render direkt vorhören, A/B-Vergleich von Audio-Files, "
            "Quick-Listen zu Recordings. Read-only auf Filesystem, zone=green."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "Absoluter oder relativer Pfad zur Audio-Datei.",
                },
                "blocking": {
                    "type": "boolean",
                    "default": True,
                    "description": "True (default): wartet auf Playback-Ende. False: fire-and-forget.",
                },
            },
            "required": ["path"],
            "additionalProperties": False,
        },
    ),
    # ---- Cubase Port-Setup-Validator (Diagnose bei Mackie-Disconnect) ----
    Tool(
        name="validate_cubase_port_setup",
        description=(
            "Parst Cubase's Port Setup.xml (%APPDATA%/Steinberg/Cubase 15_64/Port Setup.xml) "
            "und prueft, ob die erwarteten Mackie-loopMIDI-Ports (MACKIE_TO_CUBASE, "
            "MACKIE_FROM_CUBASE, MACKIE_TO_ABLETON, MACKIE_FROM_ABLETON) bei Cubase "
            "registriert sind. Liefert ok, missing_ports, all_mackie_ports und Treiber-"
            "Verteilung. Diagnose-Tool bei Mackie-Disconnects — zeigt in einer MCP-Antwort, "
            "ob Cubase die Ports ueberhaupt kennt, ohne Studio-Setup-Dialog zu oeffnen. "
            "Read-only, zone=green."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "Optionaler Pfad zu Port Setup.xml. Default: %APPDATA%/Steinberg/Cubase 15_64/Port Setup.xml.",
                },
            },
            "additionalProperties": False,
        },
    ),
    Tool(
        name="list_cubase_audio_drivers",
        description=(
            "Liefert die Treiber-Verteilung aus Cubase's Port Setup.xml: pro Treiber "
            "(ASIO Link Pro, ZOOM L-12, Windows MIDI, ...) Anzahl Inputs/Outputs/Total. "
            "Hilft bei der Diagnose von Audio-Setup-Problemen (ASIO-Treiber fehlt, "
            "Interface nicht erkannt, ...). Read-only, zone=green."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "Optionaler Pfad zu Port Setup.xml. Default: %APPDATA%/Steinberg/Cubase 15_64/Port Setup.xml.",
                },
            },
            "additionalProperties": False,
        },
    ),
    # ---- Traktor-Bridge-Tools (Etappe 7) ----
    Tool(
        name="get_traktor_state",
        description=(
            "Liefert den Traktor Deck-State aller Decks (A-D): Play, Volume, EQ, Filter, "
            "Crossfader, Loop/Sync Active via MIDI Round-Trip (Input→Output). "
            "Snapshot-basiert: pollt Traktor einmal und sammelt Output-CCs. "
            "Einschränkung S8-Mode: Mixer-Werte sind binär (0 oder 127). "
            "Read-only, zone=green."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "deck": {
                    "type": "string",
                    "enum": ["A", "B", "C", "D"],
                    "description": "Optional: nur ein bestimmtes Deck abfragen.",
                },
            },
            "additionalProperties": False,
        },
    ),
]


# ---------- Premium-Tool-Filter ----------
# Wenn PREMIUM_AVAILABLE=False (Public-Build), werden Premium-Tools aus der
# nach aussen exponierten TOOLS-Liste gefiltert. Die Definitionen bleiben in
# _ALL_TOOLS, werden aber nicht registriert.

_PREMIUM_TOOL_NAMES: set[str] = {
    "nicker_list_mastering_genres",
    "nicker_list_mastering_platforms",
    "nicker_suggest_mastering_chain",
    "nicker_list_studium_docs",
    "nicker_search_studium",
    "nicker_get_studium_doc",
    "nicker_analyze_audio_file",
    "nicker_audit_audio_file",
    "nicker_suggest_track_settings",
    "nicker_list_track_roles",
    "nicker_compare_audio_files",
    "nicker_log_reaction",
    "nicker_reaction_summary",
    "nicker_list_reaction_tags",
    "nicker_freq_advice",
    "nicker_list_freq_track_roles",
    "nicker_find_masking_conflicts",
    "nicker_send_midi_cc",
    "nicker_send_midi_cc_pct",
    "nicker_send_midi_cc_range",
    "nicker_set_plugin_param",
    "nicker_list_midi_ports",
    "nicker_set_pro_q3_band",
    "nicker_set_pro_c2",
    "nicker_apply_preset",
    "nicker_list_mix_presets",
    "nicker_lookup_plugin",
    "nicker_get_plugin_details",
    "nicker_plugin_registry_stats",
    "nicker_sync_plugins_from_cubase",
    "get_traktor_state",
}

TOOLS: list[Tool] = [
    t for t in _ALL_TOOLS
    if PREMIUM_AVAILABLE or t.name not in _PREMIUM_TOOL_NAMES
]


# ---------- MCP-Server ----------

server = Server("ki-studio-mackie")


@server.list_tools()
async def list_tools() -> list[Tool]:
    return TOOLS


@server.call_tool()
async def call_tool(name: str, arguments: dict[str, Any] | None) -> list[TextContent]:
    args = arguments or {}
    daw = _get_daw_arg(args)

    # ---- Premium-Guard ----
    # Wenn Premium-Tool aufgerufen, aber Premium nicht installiert: frueh raus.
    # Normalerweise sollte die MCP-Tool-Liste schon gefiltert sein (s.o. TOOLS),
    # aber falls ein Client raten sollte, geben wir eine klare Fehlermeldung.
    if not PREMIUM_AVAILABLE and name in _PREMIUM_TOOL_NAMES:
        return _error_envelope(
            tool=name, daw=daw,
            message=(
                f"Tool '{name}' requires the premium package "
                f"(yoka-cubase-premium). This is the public/free build."
            ),
        )

    # ---- Plugin-Registry (Markt-Scan-Pattern, 2026-05-21) ----
    if name == "nicker_lookup_plugin":
        try:
            result = registry_lookup_plugin(
                query=args.get("query"),
                category=args.get("category"),
                manufacturer=args.get("manufacturer"),
                use_case=args.get("use_case"),
                sound_tag=args.get("sound_tag"),
                with_cc_mapping_only=bool(args.get("with_cc_mapping_only", False)),
                license_active_only=bool(args.get("license_active_only", True)),
                limit=int(args.get("limit", 10)),
            )
            return _to_content(_envelope(
                tool=name, ok=True, daw=daw,
                requested=args,
                observed=result.to_dict(),
                verified=True,
                source="plugin_registry",
            ))
        except (FileNotFoundError, KeyError, ValueError) as e:
            return _error_envelope(name, daw, f"{type(e).__name__}: {e}")

    if name == "nicker_get_plugin_details":
        try:
            plugin_name = args.get("name", "")
            if not plugin_name:
                return _error_envelope(name, daw, "name is required")
            details = registry_get_plugin_details(plugin_name)
            return _to_content(_envelope(
                tool=name, ok=details is not None, daw=daw,
                requested={"name": plugin_name},
                observed=details if details else {"found": False, "name": plugin_name},
                verified=details is not None,
                source="plugin_registry",
                error=None if details else f"Plugin {plugin_name!r} nicht im Inventar (Case-sensitive!).",
            ))
        except (FileNotFoundError, KeyError) as e:
            return _error_envelope(name, daw, f"{type(e).__name__}: {e}")

    if name == "nicker_plugin_registry_stats":
        try:
            stats = registry_stats_fn()
            return _to_content(_envelope(
                tool=name, ok=True, daw=daw,
                observed=stats,
                verified=True,
                source="plugin_registry",
            ))
        except (FileNotFoundError, KeyError) as e:
            return _error_envelope(name, daw, f"{type(e).__name__}: {e}")

    if name == "nicker_sync_plugins_from_cubase":
        try:
            from pathlib import Path as _Path
            xml_paths = None
            if args.get("vst3_xml_path") or args.get("vst2_xml_path"):
                from runtime.persona.cubase_plugin_sync import default_xml_paths
                xml_paths = default_xml_paths()
                if v3 := args.get("vst3_xml_path"):
                    xml_paths["vst3"] = _Path(v3)
                if v2 := args.get("vst2_xml_path"):
                    xml_paths["vst2"] = _Path(v2)
            result = cubase_plugin_sync_run(
                apply=bool(args.get("apply", False)),
                remove_stale=bool(args.get("remove_stale", False)),
                xml_paths=xml_paths,
            )
            return _to_content(_envelope(
                tool=name, ok=True, daw=daw,
                requested=args,
                observed=result,
                verified=result.get("applied", False),
                source="cubase_xml_sync",
            ))
        except (FileNotFoundError, OSError, ValueError) as e:
            return _error_envelope(name, daw, f"{type(e).__name__}: {e}")

    # ---- Audio-Helper (Quick-Win 2 nach Mureka-Lessons-ADR, 2026-05-21) ----
    if name == "play_audio_file":
        from runtime.audio import AudioPlaybackError, play_audio_file

        path_arg = args.get("path", "")
        blocking = bool(args.get("blocking", True))
        if not path_arg:
            return _error_envelope(name, daw, "path is required")
        try:
            play_audio_file(path_arg, blocking=blocking)
            return _to_content(_envelope(
                tool=name, ok=True, daw=daw,
                requested={"path": path_arg, "blocking": blocking},
                observed={"played": path_arg, "blocking": blocking},
                verified=True,
                source="runtime.audio.playback",
            ))
        except FileNotFoundError as e:
            return _error_envelope(name, daw, f"File not found: {e}")
        except AudioPlaybackError as e:
            return _error_envelope(name, daw, f"Playback failed: {e}")

    # ---- Traktor-Bridge-Tools (kein Mackie-Controller nötig) ----
    if name == "get_traktor_state":
        try:
            data = traktor_snapshot(timeout=1.5)
            deck_filter = args.get("deck")
            if deck_filter:
                observed = data["decks"].get(deck_filter)
                if observed is None:
                    return _error_envelope(name, "traktor", f"Deck {deck_filter!r} nicht gefunden.")
            else:
                observed = data["decks"]
            return _to_content(_envelope(
                tool=name, ok=True, daw="traktor",
                observed=observed, verified=True,
                source="traktor_midi_roundtrip",
                freshness_ms=int(data.get("uptime_s", 0) * 1000),
            ))
        except (OSError, ValueError) as e:
            return _error_envelope(
                name, "traktor",
                f"Traktor nicht erreichbar — IAC-Ports prüfen. {type(e).__name__}: {e}",
            )

    # ---- Sprint D: MIDI-CC-Send (kein DAW-Controller noetig) ----
    if name == "nicker_send_midi_cc":
        result = send_midi_cc(
            cc=int(args["cc"]),
            value=int(args["value"]),
            port=args.get("port", "XBOARD_BRIDGED"),
            channel=int(args.get("channel", 0)),
        )
        return _to_content(_envelope(
            tool=name, ok=result.ok, daw=daw,
            requested={
                "cc": result.cc, "value": result.value,
                "channel": result.channel, "port": args.get("port", "XBOARD_BRIDGED"),
            },
            observed={
                "port_used": result.port_used,
                "cc_sent": result.cc, "value_sent": result.value,
                "channel": result.channel,
            },
            verified=result.ok,
            source="midi_send",
            error=result.error,
        ))

    if name == "nicker_send_midi_cc_pct":
        result = send_midi_cc_pct(
            cc=int(args["cc"]),
            target_value_pct=float(args["value_pct"]),
            port=args.get("port", "XBOARD_BRIDGED"),
            channel=int(args.get("channel", 0)),
        )
        return _to_content(_envelope(
            tool=name, ok=result.ok, daw=daw,
            requested={
                "cc": result.cc, "value_pct": args["value_pct"],
                "channel": result.channel,
            },
            observed={
                "port_used": result.port_used,
                "cc_sent": result.cc, "value_sent": result.value,
                "channel": result.channel,
            },
            verified=result.ok,
            source="midi_send",
            error=result.error,
        ))

    if name == "nicker_send_midi_cc_range":
        result = send_midi_cc_range(
            cc=int(args["cc"]),
            target_value=float(args["target_value"]),
            range_min=float(args["range_min"]),
            range_max=float(args["range_max"]),
            port=args.get("port", "XBOARD_BRIDGED"),
            channel=int(args.get("channel", 0)),
        )
        return _to_content(_envelope(
            tool=name, ok=result.ok, daw=daw,
            requested={
                "cc": result.cc,
                "target_value": args["target_value"],
                "range_min": args["range_min"],
                "range_max": args["range_max"],
                "channel": result.channel,
            },
            observed={
                "port_used": result.port_used,
                "cc_sent": result.cc, "value_sent": result.value,
                "channel": result.channel,
            },
            verified=result.ok,
            source="midi_send",
            error=result.error,
        ))

    if name == "send_cubase_command":
        from runtime.midi_bridge.cubase_commands import (
            send_cubase_command as _send_cubase_command,
        )
        res, send = _send_cubase_command(
            command_name=str(args["command_name"]),
            port=args.get("port"),
        )
        if not res.ok:
            return _to_content(_envelope(
                tool=name, ok=False, daw=daw,
                requested={"command_name": args["command_name"]},
                observed={"candidates": res.candidates},
                verified=False, source="command_map",
                error=res.error,
            ))
        return _to_content(_envelope(
            tool=name, ok=bool(send and send.ok), daw=daw,
            requested={
                "command_name": args["command_name"],
                "resolved": res.key,
            },
            observed={
                "category": res.category, "command": res.command,
                "channel": res.channel, "cc": res.cc,
                "port_used": send.port_used if send else None,
                "value_sent": send.value if send else None,
            },
            # MIDI ist fire-and-forget: ok=CC gesendet. Ob Cubase den Command
            # wirklich ausfuehrte, ist ueber diesen Pfad nicht rueckmeldbar.
            verified=False,
            source="midi_send",
            error=(send.error if send and not send.ok else None),
        ))

    if name == "nicker_set_plugin_param":
        from runtime.midi_bridge.plugin_values import resolve as _resolve_pp
        info, err = _resolve_pp(str(args["plugin"]), str(args["param"]))
        if err:
            return _to_content(_envelope(
                tool=name, ok=False, daw=daw,
                requested={"plugin": args["plugin"], "param": args["param"]},
                observed={}, verified=False, source="value_cc_map", error=err,
            ))
        slot = int(args.get("insert_slot", 0))
        result = send_midi_cc(
            cc=int(info["cc"]),
            value=int(args["value"]),
            port="AI_VAL",
            channel=slot,
        )
        return _to_content(_envelope(
            tool=name, ok=result.ok, daw=daw,
            requested={
                "plugin": info["plugin"], "param": args["param"],
                "value": int(args["value"]), "insert_slot": slot,
            },
            observed={
                "resolved_cc": info["cc"],
                "resolved_title": info.get("title"),
                "resolved_role": info.get("role"),
                "channel": slot, "port_used": result.port_used,
                "value_sent": result.value,
            },
            verified=False,  # MIDI ist fire-and-forget
            source="midi_send",
            error=result.error,
        ))

    if name == "send_midi_note":
        # to_thread: send_midi_notes blockt via time.sleep bis zu 30s. In einem
        # Worker-Thread laufen lassen, damit der asyncio-Event-Loop des MCP-Servers
        # nicht einfriert (sonst kein paralleler Tool-Call/State-Poll waehrend der Note).
        note_result = await asyncio.to_thread(
            send_midi_notes,
            notes=[int(n) for n in args["notes"]],
            duration_ms=int(args.get("duration_ms", 500)),
            velocity=int(args.get("velocity", 80)),
            port=args.get("port", "AI_INPUT"),
            channel=int(args.get("channel", 0)),
        )
        return _to_content(_envelope(
            tool=name, ok=note_result.ok, daw=daw,
            requested={
                "notes": note_result.notes,
                "duration_ms": note_result.duration_ms,
                "velocity": note_result.velocity,
                "channel": note_result.channel,
                "port": args.get("port", "AI_INPUT"),
            },
            observed={
                "port_used": note_result.port_used,
                "notes_sent": note_result.notes,
                "velocity": note_result.velocity,
                "channel": note_result.channel,
                "duration_ms": note_result.duration_ms,
            },
            verified=note_result.ok,
            source="midi_send",
            error=note_result.error,
        ))

    if name == "send_midi_note_sequence":
        # to_thread: blockt via time.sleep bis 30s — siehe send_midi_note oben.
        seq_result = await asyncio.to_thread(
            send_midi_note_sequence,
            notes=[int(n) for n in args["notes"]],
            note_duration_ms=int(args.get("note_duration_ms", 250)),
            gap_ms=int(args.get("gap_ms", 50)),
            velocity=int(args.get("velocity", 80)),
            port=args.get("port", "AI_INPUT"),
            channel=int(args.get("channel", 0)),
        )
        return _to_content(_envelope(
            tool=name, ok=seq_result.ok, daw=daw,
            requested={
                "notes": seq_result.notes,
                "note_duration_ms": int(args.get("note_duration_ms", 250)),
                "gap_ms": int(args.get("gap_ms", 50)),
                "velocity": seq_result.velocity,
                "channel": seq_result.channel,
                "port": args.get("port", "AI_INPUT"),
            },
            observed={
                "port_used": seq_result.port_used,
                "notes_sent": seq_result.notes,
                "total_duration_ms": seq_result.duration_ms,
                "channel": seq_result.channel,
            },
            verified=seq_result.ok,
            source="midi_send",
            error=seq_result.error,
        ))

    if name == "nicker_list_midi_ports":
        from runtime.midi_bridge.send_cc import list_ports as list_midi_ports
        ports = list_midi_ports()
        return _to_content(_envelope(
            tool=name, ok=True, daw=daw,
            observed={"output_ports": ports, "count": len(ports)},
            verified=True, source="mido",
        ))

    # ---- High-Level Plugin-Control ----
    if name == "nicker_set_pro_q3_band":
        try:
            dry_run = bool(args.get("dry_run", False))
            result = plugin_set_pro_q3_band(
                bus=args["bus"],
                band_num=int(args["band_num"]),
                freq_hz=args.get("freq_hz"),
                gain_db=args.get("gain_db"),
                q=args.get("q"),
                shape=args.get("shape"),
                slope=args.get("slope"),
                enabled=args.get("enabled"),
                port=args.get("port", "AI_INPUT"),
                dry_run=dry_run,
            )
            return _to_content(_envelope(
                tool=name, ok=result.all_ok, daw=daw,
                requested=args,
                observed=result.to_dict(),
                verified=result.all_ok and not dry_run,
                source="plugin_control_dry_run" if dry_run else "plugin_control",
                error=("STC dry_run: keine CCs gesendet, nur Vorschlag berechnet" if dry_run else None),
            ))
        except (ValueError, KeyError) as e:
            return _error_envelope(name, daw, f"{type(e).__name__}: {e}")

    if name == "nicker_set_pro_c2":
        try:
            dry_run = bool(args.get("dry_run", False))
            result = plugin_set_pro_c2(
                bus=args["bus"],
                threshold_db=args.get("threshold_db"),
                ratio=args.get("ratio"),
                attack_ms=args.get("attack_ms"),
                release_ms=args.get("release_ms"),
                knee_db=args.get("knee_db"),
                range_db=args.get("range_db"),
                lookahead_ms=args.get("lookahead_ms"),
                hold_ms=args.get("hold_ms"),
                wet_gain_db=args.get("wet_gain_db"),
                dry_gain_db=args.get("dry_gain_db"),
                port=args.get("port", "AI_INPUT"),
                dry_run=dry_run,
            )
            return _to_content(_envelope(
                tool=name, ok=result.all_ok, daw=daw,
                requested=args,
                observed=result.to_dict(),
                verified=result.all_ok and not dry_run,
                source="plugin_control_dry_run" if dry_run else "plugin_control",
                error=("STC dry_run: keine CCs gesendet, nur Vorschlag berechnet" if dry_run else None),
            ))
        except (ValueError, KeyError) as e:
            return _error_envelope(name, daw, f"{type(e).__name__}: {e}")

    if name == "nicker_apply_preset":
        try:
            dry_run = bool(args.get("dry_run", False))
            result = plugin_apply_preset(
                preset_id=args["preset_id"],
                bus=args.get("bus"),
                port=args.get("port", "AI_INPUT"),
                dry_run=dry_run,
            )
            return _to_content(_envelope(
                tool=name, ok=result.get("ok", False), daw=daw,
                requested=args,
                observed=result,
                verified=result.get("ok", False) and not dry_run,
                source="plugin_control_dry_run" if dry_run else "plugin_control",
                error=(
                    result.get("error") if result.get("error")
                    else ("STC dry_run: kein Preset angewendet, nur Vorschlag berechnet" if dry_run else None)
                ),
            ))
        except Exception as e:
            return _error_envelope(name, daw, f"{type(e).__name__}: {e}")

    if name == "nicker_list_mix_presets":
        presets = plugin_list_presets(category=args.get("category"))
        return _to_content(_envelope(
            tool=name, ok=True, daw=daw,
            observed={"presets": presets, "count": len(presets)},
            verified=True, source="knowledge_base",
        ))

    # ---- Cubase Port-Setup-Validator (kein Controller noetig) ----
    if name == "validate_cubase_port_setup":
        from runtime.setup.cubase_port_setup import validate_port_setup
        result = validate_port_setup(args.get("path"))
        return _to_content(_envelope(
            tool=name, ok=result["ok"], daw=daw,
            requested={"path": args.get("path")} if args.get("path") else None,
            observed=result,
            verified=result.get("available", False),
            source="cubase_port_setup_xml",
            error=result.get("error"),
        ))

    if name == "list_cubase_audio_drivers":
        from runtime.setup.cubase_port_setup import list_audio_drivers
        result = list_audio_drivers(args.get("path"))
        return _to_content(_envelope(
            tool=name, ok=result["ok"], daw=daw,
            requested={"path": args.get("path")} if args.get("path") else None,
            observed=result,
            verified=result.get("available", False),
            source="cubase_port_setup_xml",
            error=result.get("error"),
        ))

    # list_connected_daws braucht keinen Controller
    if name == "list_connected_daws":
        info: dict[str, dict[str, Any]] = {}
        for daw_name, cfg in DAW_REGISTRY.items():
            info[daw_name] = {
                "listener_port": cfg["listener_port"],
                "sender_port": cfg["sender_port"],
                "initialized": daw_name in _controllers,
            }
        env = _envelope(
            tool=name, ok=True, daw=DEFAULT_DAW,
            observed=info, verified=True, source="registry",
        )
        return _to_content(env)

    # Validierung daw
    if daw not in DAW_REGISTRY:
        return _error_envelope(
            name, daw,
            f"Unbekannte DAW {daw!r}. Verfügbar: {sorted(DAW_REGISTRY.keys())}",
        )

    try:
        # Alle anderen Tools brauchen einen Controller
        try:
            cl = await _get_controller(daw)
        except (OSError, ValueError) as e:
            return _error_envelope(
                name, daw,
                f"DAW {daw!r} nicht erreichbar — Ports {DAW_REGISTRY[daw]} prüfen "
                f"(loopMIDI läuft? DAW konfiguriert?). {type(e).__name__}: {e}",
            )

        if name == "get_daw_state":
            snap = cl.state.snapshot()
            return _to_content(_envelope(
                tool=name, ok=True, daw=daw, observed=snap, verified=True,
                freshness_ms=snap.get("freshness_ms"),
            ))

        if name == "get_active_track":
            snap = cl.state.snapshot()
            return _to_content(_envelope(
                tool=name, ok=True, daw=daw, observed=snap.get("active_track"),
                verified=True, freshness_ms=snap.get("freshness_ms"),
            ))

        if name == "list_tracks":
            snap = cl.state.snapshot()
            return _to_content(_envelope(
                tool=name, ok=True, daw=daw, observed=snap["tracks"],
                verified=True, freshness_ms=snap.get("freshness_ms"),
            ))

        if name == "select_track":
            track_index = int(args["track_index"])
            timeout_ms = int(args.get("timeout_ms", DEFAULT_TIMEOUT_MS))
            result = cl.select_track(track_index, timeout_ms=timeout_ms)
            return _to_content(_envelope(
                tool=name, ok=result["ok"], daw=daw,
                requested={"track_index": track_index, "timeout_ms": timeout_ms},
                observed=result["snapshot"].get("active_track"),
                verified=result["verified"], was_already_satisfied=result.get("was_already_satisfied"), source="closed_loop",
                freshness_ms=result["snapshot"].get("freshness_ms"),
                elapsed_ms=result["elapsed_ms"],
                error=None if result["verified"] else "Echo blieb im Timeout-Fenster aus (möglich: Track war bereits selektiert).",
            ))

        if name == "set_mode":
            mode = args["mode"]
            timeout_ms = int(args.get("timeout_ms", DEFAULT_TIMEOUT_MS))
            result = cl.set_mode(mode, timeout_ms=timeout_ms)
            return _to_content(_envelope(
                tool=name, ok=result["ok"], daw=daw,
                requested={"mode": mode, "timeout_ms": timeout_ms},
                observed={"mode": result["snapshot"].get("mode")},
                verified=result["verified"], was_already_satisfied=result.get("was_already_satisfied"), source="closed_loop",
                freshness_ms=result["snapshot"].get("freshness_ms"),
                elapsed_ms=result["elapsed_ms"],
            ))

        if name == "force_track_mode":
            result = cl.set_mode("track", timeout_ms=DEFAULT_TIMEOUT_MS)
            return _to_content(_envelope(
                tool=name, ok=result["ok"], daw=daw,
                observed={"mode": result["snapshot"].get("mode")},
                verified=result["verified"], was_already_satisfied=result.get("was_already_satisfied"), source="closed_loop",
                freshness_ms=result["snapshot"].get("freshness_ms"),
                elapsed_ms=result["elapsed_ms"],
            ))

        if name == "transport_play":
            result = cl.transport("play", timeout_ms=DEFAULT_TIMEOUT_MS)
            return _to_content(_envelope(
                tool=name, ok=result["ok"], daw=daw,
                observed={"transport_state": result["snapshot"]["transport"]["state"]},
                verified=result["verified"], was_already_satisfied=result.get("was_already_satisfied"), source="closed_loop",
                freshness_ms=result["snapshot"].get("freshness_ms"),
                elapsed_ms=result["elapsed_ms"],
            ))

        if name == "transport_stop":
            result = cl.transport("stop", timeout_ms=DEFAULT_TIMEOUT_MS)
            return _to_content(_envelope(
                tool=name, ok=result["ok"], daw=daw,
                observed={"transport_state": result["snapshot"]["transport"]["state"]},
                verified=result["verified"], was_already_satisfied=result.get("was_already_satisfied"), source="closed_loop",
                freshness_ms=result["snapshot"].get("freshness_ms"),
                elapsed_ms=result["elapsed_ms"],
            ))

        if name == "transport_record":
            result = cl.transport("record", timeout_ms=DEFAULT_TIMEOUT_MS)
            return _to_content(_envelope(
                tool=name, ok=result["ok"], daw=daw,
                observed={"transport_state": result["snapshot"]["transport"]["state"]},
                verified=result["verified"], was_already_satisfied=result.get("was_already_satisfied"), source="closed_loop",
                freshness_ms=result["snapshot"].get("freshness_ms"),
                elapsed_ms=result["elapsed_ms"],
            ))

        if name == "set_track_volume":
            track_index = int(args["track_index"])
            value14 = int(args["value14"])
            cl.sender.set_fader(track_index, value14)
            return _to_content(_envelope(
                tool=name, ok=True, daw=daw,
                requested={"track_index": track_index, "value14": value14},
                observed={"sent_value14": value14, "approx_db": round(value14_to_db(value14), 2)},
                verified=False, source="sender",
                error=("Send durchgeführt, aber pitch_bend-Echo bei Cubase nicht garantiert "
                       "(Hardware-Mackie hat motorisierte Fader). Bei Ableton typisch echoed."),
            ))

        if name == "set_track_volume_db":
            track_index = int(args["track_index"])
            db = float(args["db"])
            dry_run = bool(args.get("dry_run", False))
            value14 = db_to_value14(db)
            if not dry_run:
                cl.sender.set_fader(track_index, value14)
            return _to_content(_envelope(
                tool=name, ok=True, daw=daw,
                requested={"track_index": track_index, "db": db, "dry_run": dry_run},
                observed={
                    "sent_value14": value14 if not dry_run else None,
                    "would_send_value14": value14 if dry_run else None,
                    "back_to_db": round(value14_to_db(value14), 2),
                    "dry_run": dry_run,
                },
                verified=False, source="sender_dry_run" if dry_run else "sender",
                error=(
                    "STC dry_run: kein Fader-Send, nur value14 berechnet"
                    if dry_run else
                    "Send durchgeführt, Verifikation eingeschränkt durch DAW-Echo-Verhalten."
                ),
            ))

        if name == "get_active_plugin":
            snap = cl.state.snapshot()
            return _to_content(_envelope(
                tool=name, ok=True, daw=daw,
                observed=snap.get("active_plugin"),
                verified=snap.get("active_plugin") is not None,
                source="state_mirror",
                freshness_ms=snap.get("freshness_ms"),
                error=None if snap.get("active_plugin") else "Nicht im Plugin-Mode oder keine Page-Info im LCD — vorher set_mode('plugin') aufrufen.",
            ))

        if name == "plugin_page_next":
            cl.sender.channel_right()
            await asyncio.sleep(0.3)  # Event-Loop nicht blockieren (async-Handler)
            snap = cl.state.snapshot()
            return _to_content(_envelope(
                tool=name, ok=True, daw=daw,
                observed=snap.get("active_plugin"),
                verified=snap.get("active_plugin") is not None,
                source="closed_loop",
                freshness_ms=snap.get("freshness_ms"),
            ))

        if name == "plugin_page_prev":
            cl.sender.channel_left()
            await asyncio.sleep(0.3)  # Event-Loop nicht blockieren (async-Handler)
            snap = cl.state.snapshot()
            return _to_content(_envelope(
                tool=name, ok=True, daw=daw,
                observed=snap.get("active_plugin"),
                verified=snap.get("active_plugin") is not None,
                source="closed_loop",
                freshness_ms=snap.get("freshness_ms"),
            ))

        if name == "start_session_log":
            cl.state.start_session_log()
            return _to_content(_envelope(
                tool=name, ok=True, daw=daw,
                observed={"active": True}, verified=True, source="state_mirror",
            ))

        if name == "get_session_summary":
            summary = cl.state.session_summary()
            return _to_content(_envelope(
                tool=name, ok=True, daw=daw,
                observed=summary, verified=True, source="state_mirror",
            ))

        if name == "get_session_report":
            summary = cl.state.session_summary()
            report = render_session_report(summary, daw=daw)
            return _to_content(_envelope(
                tool=name, ok=True, daw=daw,
                observed={"markdown": report, "events": summary.get("events", 0)},
                verified=True, source="state_mirror",
            ))

        if name == "ahk_list_actions":
            bridge = AhkBridge()
            actions = bridge.list_actions(daw)
            return _to_content(_envelope(
                tool=name, ok=True, daw=daw,
                observed=actions, verified=True, source="ahk_bridge",
            ))

        # ---------- Persona Sprint A: Mastering-Chain-Advisor ----------
        if name == "nicker_list_mastering_genres":
            from runtime.persona.mastering import list_genres
            return _to_content(_envelope(
                tool=name, ok=True, daw=daw,
                observed={"genres": list_genres()},
                verified=True, source="ymp_knowledge_base",
            ))

        if name == "nicker_list_mastering_platforms":
            from runtime.persona.mastering import list_platforms
            return _to_content(_envelope(
                tool=name, ok=True, daw=daw,
                observed={"platforms": list_platforms()},
                verified=True, source="ymp_knowledge_base",
            ))

        if name == "nicker_suggest_mastering_chain":
            from runtime.persona.mastering import suggest_mastering_chain
            genre_id = args.get("genre", "")
            platform_id = args.get("platform", "spotify")
            advice = suggest_mastering_chain(genre_id, platform_id)
            if not advice.get("ok"):
                return _to_content(_envelope(
                    tool=name, ok=False, daw=daw,
                    requested={"genre": genre_id, "platform": platform_id},
                    observed=advice,
                    verified=False, source="ymp_knowledge_base",
                    error=advice.get("error"),
                ))
            return _to_content(_envelope(
                tool=name, ok=True, daw=daw,
                requested={"genre": genre_id, "platform": platform_id},
                observed=advice,
                verified=True, source="ymp_knowledge_base",
            ))

        # ---------- YMP-Studium-Wissensbasis ----------
        if name == "nicker_list_studium_docs":
            from runtime.persona.ymp_loader import list_studium_docs, get_studium_index
            category_filter = args.get("category")
            docs = list_studium_docs()
            if category_filter:
                docs = [d for d in docs if d["category"] == category_filter]
            index = get_studium_index()
            return _to_content(_envelope(
                tool=name, ok=True, daw=daw,
                requested={"category": category_filter} if category_filter else None,
                observed={
                    "total_count": len(docs),
                    "docs": docs,
                    "studium_path": index.get("studium_path"),
                    "available": index.get("available", False),
                },
                verified=index.get("available", False),
                source="ymp_studium_loader",
                error=index.get("error"),
            ))

        if name == "nicker_search_studium":
            from runtime.persona.ymp_loader import search_studium, get_studium_index
            query = args.get("query", "")
            top_k = int(args.get("top_k", 5))
            results = search_studium(query, top_k=top_k)
            index = get_studium_index()
            return _to_content(_envelope(
                tool=name, ok=True, daw=daw,
                requested={"query": query, "top_k": top_k},
                observed={
                    "match_count": len(results),
                    "results": results,
                    "available": index.get("available", False),
                },
                verified=index.get("available", False),
                source="ymp_studium_loader",
                error=index.get("error"),
            ))

        if name == "nicker_get_studium_doc":
            from runtime.persona.ymp_loader import get_studium_doc, get_studium_index
            ymp_id = int(args.get("ymp_id", -1))
            include_body = bool(args.get("include_body", False))
            max_chars = int(args.get("max_chars", 2000))
            doc = get_studium_doc(ymp_id, include_body=include_body, max_chars=max_chars)
            index = get_studium_index()
            if doc is None:
                return _to_content(_envelope(
                    tool=name, ok=False, daw=daw,
                    requested={"ymp_id": ymp_id, "include_body": include_body, "max_chars": max_chars},
                    observed={"available": index.get("available", False)},
                    verified=False, source="ymp_studium_loader",
                    error=f"ymp_id {ymp_id} nicht in Wissensbasis",
                ))
            return _to_content(_envelope(
                tool=name, ok=True, daw=daw,
                requested={"ymp_id": ymp_id, "include_body": include_body, "max_chars": max_chars},
                observed=doc,
                verified=True, source="ymp_studium_loader",
            ))

        # ---------- Sprint E1: Audio-Analytics-Layer ----------
        if name == "nicker_analyze_audio_file":
            from runtime.persona.audio_analytics import analyze_audio_file
            path = args.get("path", "")
            try:
                result = analyze_audio_file(path)
                return _to_content(_envelope(
                    tool=name, ok=True, daw=daw,
                    requested={"path": path},
                    observed=result.to_dict(),
                    verified=True, source="audio_analytics",
                ))
            except FileNotFoundError as e:
                return _to_content(_envelope(
                    tool=name, ok=False, daw=daw,
                    requested={"path": path},
                    verified=False, source="audio_analytics",
                    error=str(e),
                ))

        if name == "nicker_audit_audio_file":
            from runtime.persona.audio_analytics import analyze_audio_file
            from runtime.persona.mastering_audit import audit_audio_analysis
            path = args.get("path", "")
            genre_id = args.get("genre")
            platform_id = args.get("platform", "spotify")
            try:
                analysis = analyze_audio_file(path)
                report = audit_audio_analysis(analysis, genre_id=genre_id, platform_id=platform_id)
                return _to_content(_envelope(
                    tool=name, ok=True, daw=daw,
                    requested={"path": path, "genre": genre_id, "platform": platform_id},
                    observed=report.to_dict(),
                    verified=True, source="audio_analytics",
                ))
            except FileNotFoundError as e:
                return _to_content(_envelope(
                    tool=name, ok=False, daw=daw,
                    requested={"path": path, "genre": genre_id, "platform": platform_id},
                    verified=False, source="audio_analytics",
                    error=str(e),
                ))

        if name == "nicker_suggest_track_settings":
            from runtime.persona.audio_analytics import analyze_audio_file
            from runtime.persona.pre_settings import suggest_track_pre_settings
            path = args.get("path", "")
            track_role = args.get("track_role", "harmonic")
            genre_id = args.get("genre")
            platform_id = args.get("platform", "spotify")
            try:
                analysis = analyze_audio_file(path)
                settings = suggest_track_pre_settings(
                    analysis, track_role=track_role,
                    genre_id=genre_id, platform_id=platform_id,
                )
                return _to_content(_envelope(
                    tool=name, ok=True, daw=daw,
                    requested={
                        "path": path, "track_role": track_role,
                        "genre": genre_id, "platform": platform_id,
                    },
                    observed=settings.to_dict(),
                    verified=True, source="audio_analytics+ymp_knowledge_base",
                ))
            except FileNotFoundError as e:
                return _to_content(_envelope(
                    tool=name, ok=False, daw=daw,
                    requested={"path": path, "track_role": track_role},
                    verified=False, source="audio_analytics",
                    error=str(e),
                ))

        if name == "nicker_list_track_roles":
            from runtime.persona.pre_settings import list_track_roles
            return _to_content(_envelope(
                tool=name, ok=True, daw=daw,
                observed={"roles": list_track_roles()},
                verified=True, source="pre_settings_knowledge",
            ))

        if name == "nicker_compare_audio_files":
            from runtime.persona.audio_analytics import compare_audio_files
            path_a = args.get("path_a", "")
            path_b = args.get("path_b", "")
            try:
                result = compare_audio_files(path_a, path_b)
                return _to_content(_envelope(
                    tool=name, ok=True, daw=daw,
                    requested={"path_a": path_a, "path_b": path_b},
                    observed=result.to_dict(),
                    verified=True, source="audio_analytics",
                ))
            except FileNotFoundError as e:
                return _to_content(_envelope(
                    tool=name, ok=False, daw=daw,
                    requested={"path_a": path_a, "path_b": path_b},
                    verified=False, source="audio_analytics",
                    error=str(e),
                ))

        # ---------- Sprint G: Reaction-Tagging-Layer ----------
        if name == "nicker_log_reaction":
            from runtime.persona.reaction_logger import log_reaction
            tag = args.get("tag", "")
            with_snap = bool(args.get("with_daw_snapshot", False))
            snap = None
            if with_snap:
                # DAW-State-Snapshot vom State-Mirror holen
                try:
                    snap_daw = args.get("daw", DEFAULT_DAW)
                    cl_snap = await _get_controller(snap_daw)
                    full_state = cl_snap.state.snapshot()
                    # Compact form: nur die wichtigsten Felder
                    snap = {
                        "daw": snap_daw,
                        "mode": full_state.get("mode"),
                        "transport_state": full_state.get("transport", {}).get("state"),
                        "active_track": full_state.get("active_track"),
                        "active_plugin": full_state.get("active_plugin"),
                        "freshness_ms": full_state.get("freshness_ms"),
                        "timestamp": full_state.get("timestamp"),
                    }
                except Exception as e:
                    snap = {"snapshot_error": f"{type(e).__name__}: {e}"}
            entry = log_reaction(
                tag=tag,
                note=args.get("note"),
                audio_position_s=args.get("audio_position_s"),
                track_name=args.get("track_name"),
                daw_state_snapshot=snap,
                session_id=args.get("session_id"),
                person_id=args.get("person_id", "P01"),
            )
            return _to_content(_envelope(
                tool=name, ok=True, daw=daw,
                requested={"tag": tag, "with_daw_snapshot": with_snap},
                observed=entry,
                verified=True, source="reaction_logger",
            ))

        if name == "nicker_reaction_summary":
            from runtime.persona.reaction_logger import reaction_summary
            summary = reaction_summary(
                person_id=args.get("person_id"),
                mode=args.get("mode"),
                session_id=args.get("session_id"),
            )
            return _to_content(_envelope(
                tool=name, ok=True, daw=daw,
                requested=dict(args) if args else None,
                observed=summary,
                verified=True, source="reaction_logger",
            ))

        if name == "nicker_list_reaction_tags":
            from runtime.persona.reaction_logger import list_known_tags
            return _to_content(_envelope(
                tool=name, ok=True, daw=daw,
                observed=list_known_tags(),
                verified=True, source="reaction_logger",
            ))

        # ---------- Sprint B: Frequenz-Advisor ----------
        if name == "nicker_freq_advice":
            from runtime.persona.freq_advisor import get_freq_advice
            track_role = args.get("track_role", "")
            advice = get_freq_advice(track_role)
            ok = advice.get("ok", False)
            return _to_content(_envelope(
                tool=name, ok=ok, daw=daw,
                requested={"track_role": track_role},
                observed=advice,
                verified=ok, source="ymp_knowledge_base",
                error=advice.get("error") if not ok else None,
            ))

        if name == "nicker_list_freq_track_roles":
            from runtime.persona.freq_advisor import list_track_roles as _ft
            return _to_content(_envelope(
                tool=name, ok=True, daw=daw,
                observed={"roles": _ft()},
                verified=True, source="ymp_knowledge_base",
            ))

        if name == "nicker_find_masking_conflicts":
            from runtime.persona.freq_advisor import find_masking_conflicts
            track_role = args.get("track_role", "")
            result = find_masking_conflicts(track_role)
            return _to_content(_envelope(
                tool=name, ok=result.get("ok", False), daw=daw,
                requested={"track_role": track_role},
                observed=result,
                verified=result.get("ok", False), source="ymp_knowledge_base",
                error=result.get("error") if not result.get("ok") else None,
            ))

        if name in ("save_project", "undo", "redo"):
            bridge = AhkBridge()
            result = bridge.send_action(name, daw)
            d = result.to_dict()
            return _to_content(_envelope(
                tool=name, ok=d["ok"], daw=daw,
                requested={"action": name, "daw": daw},
                observed={
                    "window_guard": d["window_guard"],
                    "target_window": d.get("target_window"),
                },
                verified=d["ok"], source="ahk_bridge",
                elapsed_ms=d["elapsed_ms"],
                error=d.get("error"),
            ))

        if name == "ahk_send_action":
            bridge = AhkBridge()
            action = args["action"]
            restore = bool(args.get("restore_focus", False))
            result = bridge.send_action(action, daw, restore_focus=restore)
            d = result.to_dict()
            return _to_content(_envelope(
                tool=name, ok=d["ok"], daw=daw,
                requested={"action": action, "daw": daw, "restore_focus": restore},
                observed={
                    "window_guard": d["window_guard"],
                    "target_window": d.get("target_window"),
                },
                verified=d["ok"], source="ahk_bridge",
                elapsed_ms=d["elapsed_ms"],
                error=d.get("error"),
            ))

        if name in ("bank_left", "bank_right", "channel_left", "channel_right"):
            direction = "left" if name.endswith("_left") else "right"
            channel_step = name.startswith("channel_")
            result = cl.bank_shift(direction, channel_step=channel_step)
            return _to_content(_envelope(
                tool=name, ok=result["ok"], daw=daw,
                requested={"direction": direction, "channel_step": channel_step},
                observed={
                    "tracks": [
                        {"index": t["index"], "name": t.get("name_resolved", "")}
                        for t in result["snapshot"]["tracks"]
                    ],
                    "lcd_changed": result["verified"],
                },
                verified=result["verified"], was_already_satisfied=result.get("was_already_satisfied"), source="closed_loop",
                freshness_ms=result["snapshot"].get("freshness_ms"),
                elapsed_ms=result["elapsed_ms"],
                error=None if result["verified"] else "LCD hat sich im Timeout-Fenster nicht geändert (möglich: Bank-Anfang/Ende oder kein Display-Echo).",
            ))

        return _error_envelope(name, daw, f"Unbekanntes Tool: {name!r}")

    except Exception as e:
        return _error_envelope(name, daw, f"{type(e).__name__}: {e}")


# ---------- Entry Point ----------

async def amain() -> None:
    async with stdio_server() as (read_stream, write_stream):
        await server.run(read_stream, write_stream, server.create_initialization_options())


def main() -> int:
    try:
        asyncio.run(amain())
    except KeyboardInterrupt:
        return 0
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
