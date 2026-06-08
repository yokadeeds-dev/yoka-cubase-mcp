"""OSC-Bridge-Layer fuer KI-Studio (Spike 2026-05-21, Markt-Scan-Pattern #4).

OSC (Open Sound Control) ist DAW-agnostischer Transport. Aktuelles MCP-Setup
spricht Cubase via Mackie-Control-Universal (MIDI-SysEx). OSC erweitert das
um:
- Cross-Platform-Faehigkeit (Win + Mac + Linux)
- Native Ableton-Unterstuetzung (via AbletonOSC)
- Token-effiziente externe Clients (TouchOSC, KI-Agents, Hardware)

Architektur:
    OSC-Client (Yokas KI / TouchOSC / Python-Client)
       v OSC over UDP, default Port 9000
    runtime/osc/server.py (Python-Bridge, dieser Layer)
       v Translator: OSC-Adresse -> Action
    Backend:
       - Cubase: via loopMIDI/MIDI-Send (Mackie-Format)
       - Ableton: via AbletonOSC direkt (oder via Mackie wenn nicht da)

Spike-Status: POC fuer Cubase ueber Mackie-Translator. AbletonOSC-direkte
Anbindung folgt in Spike-Phase 2.

Aufruf:
    python -m runtime.osc.server --port 9000 --backend mackie --daw cubase
"""

from runtime.osc.schema import OSCAction, OSCSchema, default_schema
from runtime.osc.translator import OSCTranslator

__all__ = ["OSCAction", "OSCSchema", "default_schema", "OSCTranslator"]
