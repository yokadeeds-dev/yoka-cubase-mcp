# yoka-cubase-mcp

**Bidirektionaler semantischer Layer KI ↔ DAW** über das Mackie Control Universal (MCU) Protokoll. Eine KI versteht und steuert Cubase — verifiziert, in Echtzeit, ohne fragile UI-Automation.

> *Die KI muss nicht hören wie ein Mensch — sie muss verstehen: präzise, semantisch, kontinuierlich.*

---

## Was das ist

Ein **MCP-Server mit 33 Tools**, ansprechbar von Claude Code (oder jedem MCP-Client) aus. Die zentrale Idee: Statt eine DAW per fragiler UI-Automation oder geschlossener Hersteller-API zu steuern, sprechen wir das **MCU-Protokoll** — dasselbe, das physische Mixer-Controller (Mackie Control, Behringer X-Touch) seit 30 Jahren nutzen. Jede MCU-fähige DAW versteht es nativ, bidirektional und in Echtzeit.

Drei Bridge-Layer:

| Layer | Macht | Kanal |
|---|---|---|
| **Mackie (MCU)** | Mode, Track-Select, Volume, Transport, Plugin-Pages — **closed-loop-verifiziert** | MIDI via loopMIDI/IAC |
| **AHK** | ~450 whitelisted Cubase-Commands + Macros (Transport, Edit, MIDI, Quantize, Record-Arm …) | synthetische Keystrokes |
| **MIDI-Send** | Note-On/Off für Recording, voller Command-Zugriff via Cubase MIDI Remote API (1559 Commands) | MIDI via loopMIDI |

**Kerneigenschaften:**
- **Closed-Loop:** Jede Steuer-Aktion wartet auf das DAW-Echo und meldet `verified: true/false` — kein Hoffen, dass ein Befehl ankam.
- **State-Mirror:** `get_daw_state` liefert jederzeit Mode, Transport, aktive Spur, 8 sichtbare Strips mit Volume/Mute/Solo/VU — ohne Screenshot.
- **Voller Command-Zugriff:** Über die Hotkey-Whitelist (~450) hinaus sind via MIDI Remote alle ~1559 ungebundenen Cubase-Commands adressierbar.
- **Plattform-portierbar:** Windows produktiv getestet; macOS-Implementierung als Stub vorhanden.

## Architektur

```
┌─────────────────────────────────────────────────────────────┐
│  Claude Code (oder anderer MCP-Client)                       │
└──────────────────────┬──────────────────────────────────────┘
                       │ stdio MCP-Protokoll · 33 Tools
                       ▼
┌─────────────────────────────────────────────────────────────┐
│  yoka-cubase-mcp MCP-Server                                  │
│  gemeinsamer Result-Envelope · Multi-DAW-Registry            │
└───┬───────────────┬───────────────┬─────────────────────────┘
    ▼               ▼               ▼
┌────────┐   ┌────────────┐   ┌────────────┐
│ Mackie │   │ AHK-Bridge │   │ MIDI-Send  │
│ Closed │   │ Window-    │   │ Note +     │
│ Loop + │   │ Guard +    │   │ Command-   │
│ State  │   │ Hotkey/    │   │ MIDI-Remote│
│ Mirror │   │ Macro-Send │   │            │
└───┬────┘   └─────┬──────┘   └─────┬──────┘
    │ MIDI         │ synth keys     │ MIDI
    ▼              ▼                ▼
┌─────────────────────────────────────────────┐
│  Cubase 15 (jede MCU-fähige DAW)            │
└─────────────────────────────────────────────┘
```

## Tools-Übersicht (33)

| Gruppe | Beispiele | Zone |
|---|---|---|
| **State (read-only)** | `get_daw_state`, `get_active_track`, `get_active_plugin`, `list_tracks`, `list_connected_daws` | grün |
| **Mackie-Steuerung** | `set_mode`, `select_track`, `bank_left/right`, `channel_left/right`, `transport_play/stop`, `plugin_page_next/prev` | gelb |
| **Volume** | `set_track_volume`, `set_track_volume_db` | gelb |
| **AHK** | `ahk_list_actions`, `ahk_send_action` (~450 Cubase-Commands + Macros), `save_project`, `undo`, `redo` | gelb/rot |
| **MIDI-Send** | `send_midi_note`, `send_midi_note_sequence`, `send_cubase_command` (Voll-Command-Zugriff) | gelb |
| **Session-Log** | `start_session_log`, `get_session_summary`, `get_session_report` | grün |
| **Cubase-Inspector** | `validate_cubase_port_setup`, `list_cubase_audio_drivers` | grün |
| **Transport (aufnehmend)** | `transport_record` | rot |
| **Audio** | `play_audio_file` | grün |

**Zone-Semantik:** grün = read-only, gelb = mutiert DAW-State (undobar), rot = destruktiv/explizite Intent nötig.

## ⭐ Premium-Add-On: Nicker (Mixing/Mastering-Wissen)

Dieser Kern steuert die DAW. Das optionale **[yoka-cubase-premium](https://github.com/yokadeeds-dev/yoka-cubase-premium)**-Add-On macht daraus einen **KI-Mixing/Mastering-Kollegen** — ~30 zusätzliche `nicker_*`-Tools:

- Audio-Analyse (LUFS / Spektrum / True-Peak)
- Mastering-Chain-Empfehlungen pro Genre × Plattform
- EQ-/Masking-Advice pro Track-Rolle
- FabFilter Pro-Q3 / Pro-C2 per MIDI-Learn setzen
- Traktor-Deck-Observer, DAWproject-Writer

Der Server erkennt das Add-On automatisch (`_premium_in_same_runtime()`). Ohne Add-On läuft er als Core-only — die `nicker_*`-Tools sind dann ausgeblendet.

## Repo-Struktur

```
yoka-cubase-mcp/
├── README.md · LICENSE (MIT) · requirements.txt
├── runtime/
│   ├── mackie/        ← MCU-Kern: parser, state, listener, sender, closedloop, units
│   ├── ahk/           ← Hotkey-Bridge + ~450 generierte Cubase-Command-Actions
│   ├── midi_bridge/   ← Note-Send + Command-MIDI-Remote-Map
│   ├── midi_remote/   ← Cubase-MIDI-Remote-Script (1559 Commands)
│   ├── osc/           ← OSC-Bridge
│   ├── setup/         ← Cubase Port-Setup-Parser
│   ├── audio/         ← Playback
│   └── mcp/server.py  ← 33 Core-Tools (Premium-Hook für Add-On)
├── docs/              ← Setup-Guides, Demo-Workflows, Keymap-Export
├── specs/             ← Mackie-Map, Architektur-Notizen
└── tests/selftests/   ← Offline-Selftests + Live-Smoketests
```

## Quickstart (Windows)

```powershell
# Voraussetzung: Python 3.11+, loopMIDI mit Ports:
#   MACKIE_FROM_CUBASE / MACKIE_TO_CUBASE
#   AI_INPUT (für MIDI-Note-Recording)

py -3.11 -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements.txt

# Offline-Selftests (keine MIDI-Hardware nötig)
python -m tests.selftests.listener_selftest

# MCP-Server (sonst von Claude Code gestartet)
python -m runtime.mcp.server
```

DAW-seitiges Setup (Mackie-Control-Device in Cubase, loopMIDI): [`docs/01_setup_cubase_mcu.md`](docs/01_setup_cubase_mcu.md).

## MCP-Server in Claude Code aktivieren

```json
{
  "mcpServers": {
    "yoka-cubase-mcp": {
      "command": "C:\\Pfad\\zur\\.venv\\Scripts\\python.exe",
      "args": ["-m", "runtime.mcp.server"],
      "cwd": "C:\\Pfad\\zum\\repo",
      "env": {
        "MACKIE_DAW_DEFAULT": "cubase",
        "MACKIE_LISTENER_PORT_CUBASE": "MACKIE_FROM_CUBASE",
        "MACKIE_SENDER_PORT_CUBASE":   "MACKIE_TO_CUBASE"
      }
    }
  }
}
```

Danach sind Sätze möglich wie *„wechsle in Cubase auf Track 3"*, *„setze den Lead-Synth auf −3 dB"*, *„nimm eine C-Dur-Tonleiter auf der scharfgeschalteten Spur auf"*.

## Status

| Bereich | Stand |
|---|---|
| Mackie-Listener + Parser + State-Mirror | ✅ produktiv |
| Sender + Closed-Loop-Verifikation | ✅ produktiv |
| MCP-Server (33 Core-Tools) | ✅ produktiv |
| AHK-Bridge (~450 Cubase-Commands + Macros) | ✅ produktiv |
| Voll-Command-Zugriff (MIDI Remote, 1559) | ✅ live verifiziert |
| MIDI-Note-Recording (autonom) | ✅ end-to-end verifiziert |
| macOS-Port | ⏳ Stub, ungetestet |

## Lizenz

[MIT](LICENSE) © 2026 Yoka. Frei nutzbar, fork- und modifizierbar — nur der Copyright-Hinweis muss erhalten bleiben.

## Credits

Konzeption: Yoka. Implementierung: Yoka + Claude Code. Mackie Control Universal Protokoll-Spezifikation: Mackie / LOUD Audio. Kein Bezug zu oder Endorsement durch Steinberg, Ableton oder Native Instruments.
