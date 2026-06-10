# yoka-cubase-mcp

**Bidirektionaler semantischer Layer KI ↔ DAW** über das Mackie Control Universal (MCU) Protokoll. Eine KI versteht und steuert Cubase — verifiziert, in Echtzeit, ohne fragile UI-Automation.

> *Die KI muss nicht hören wie ein Mensch — sie muss verstehen: präzise, semantisch, kontinuierlich.*

> 🚧 **Das Premium-Add-On (Mixing-/Mastering-Wissen) erscheint in Kürze** — die GitHub-Sponsors-Seite wird gerade freigeschaltet (voraussichtlich Mitte Juni 2026). Der freie Kern hier ist ab sofort voll nutzbar; Details im Abschnitt [Premium-Add-On](#-premium-add-on-nicker-mixingmastering-wissen) unten.

---

## Was das ist

Ein **MCP-Server mit 40 Tools**, ansprechbar von Claude Code (oder jedem MCP-Client) aus. Die zentrale Idee: Statt eine DAW per fragiler UI-Automation oder geschlossener Hersteller-API zu steuern, sprechen wir das **MCU-Protokoll** — dasselbe, das physische Mixer-Controller (Mackie Control, Behringer X-Touch) seit 30 Jahren nutzen. Jede MCU-fähige DAW versteht es nativ, bidirektional und in Echtzeit.

Drei Bridge-Layer:

| Layer | Macht | Kanal |
|---|---|---|
| **Mackie (MCU)** | Mode, Track-Select, Volume, Transport, Plugin-Pages — **closed-loop-verifiziert** | MIDI via loopMIDI/IAC |
| **AHK** | Hotkey-Bridge für Cubase-**Standard-Commands** (die mit eigenem Hotkey) + Macros | synthetische Keystrokes |
| **MIDI-Send** | Note-On/Off für Recording + generische Command-/Plugin-Steuer-Mechanik via Cubase MIDI Remote API | MIDI via loopMIDI |

**Kerneigenschaften:**
- **Closed-Loop:** Jede Steuer-Aktion wartet auf das DAW-Echo und meldet `verified: true/false` — kein Hoffen, dass ein Befehl ankam.
- **State-Mirror:** `get_daw_state` liefert jederzeit Mode, Transport, aktive Spur, 8 sichtbare Strips mit Volume/Mute/Solo/VU — ohne Screenshot.
- **Command-Steuerung (Standards + Mechanik):** Cubase-**Standard-Commands** (die einen eigenen Hotkey haben) sind direkt nutzbar. Die **Generatoren** für die volle MIDI-Remote-Command-Belegung liegen bei (`generate_cubase_midi_remote.py`) — die **vorgefertigte volle Belegung** aller ~1559 ungebundenen Commands ist Teil des **Premium-Add-Ons**.
- **Plugin-Parameter-Steuerung (abgespeckt):** Über `makeValueBinding` (Cubase MIDI Remote API) ist **jeder vom Host veröffentlichte VST-Parameter** adressierbar — unabhängig von plugin-internem MIDI-Learn. Das MCP-Tool **`nicker_set_plugin_param`** (Plugin by name) ist **im Free dabei** — abgespeckt auf **1 echtes Stock-Plugin je Kategorie** (Demo-CC-Map: StudioEQ, Compressor, Magneto II, AutoFilter, Chorus, StereoDelay, REVerence, Pitch Correct, StereoEnhancer, Tuner). Plus rohe CC-Steuerung (`nicker_send_midi_cc`), Scanner + Generatoren für eigene Plugins. Live verifiziert (KI bewegte StudioEQ „1 Gain"). Die **volle Plugin-Abdeckung** (alle Plugins) und das Wissen „welcher Wert klingt richtig" liefert das **Premium-Add-On**.
- **Plattform-portierbar:** Windows produktiv getestet; macOS-Implementierung als Stub vorhanden.

## Architektur

```
┌─────────────────────────────────────────────────────────────┐
│  Claude Code (oder anderer MCP-Client)                       │
└──────────────────────┬──────────────────────────────────────┘
                       │ stdio MCP-Protokoll · 40 Tools
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

## Tools-Übersicht (40)

| Gruppe | Beispiele | Zone |
|---|---|---|
| **State (read-only)** | `get_daw_state`, `get_active_track`, `get_active_plugin`, `list_tracks`, `list_connected_daws` | grün |
| **Mackie-Steuerung** | `set_mode`, `select_track`, `bank_left/right`, `channel_left/right`, `transport_play/stop`, `plugin_page_next/prev` | gelb |
| **Volume** | `set_track_volume`, `set_track_volume_db` | gelb |
| **AHK** | `ahk_list_actions`, `ahk_send_action` (Cubase-Standard-Commands + Macros), `save_project`, `undo`, `redo` | gelb/rot |
| **MIDI-Send + Plugin** | `send_midi_note(_sequence)`, `send_cubase_command` (Command by name — volle Map = Premium), `nicker_send_midi_cc(_pct/_range)`, `nicker_set_plugin_param` (1 Stock-Plugin/Kategorie; volle Abdeckung = Premium) | gelb |
| **Session-Log** | `start_session_log`, `get_session_summary`, `get_session_report` | grün |
| **Cubase-Inspector** | `validate_cubase_port_setup`, `list_cubase_audio_drivers` | grün |
| **Transport (aufnehmend)** | `transport_record` | rot |
| **Audio** | `play_audio_file` | grün |

**Zone-Semantik:** grün = read-only, gelb = mutiert DAW-State (undobar), rot = destruktiv/explizite Intent nötig.

## ⭐ Premium-Add-On: Nicker (Mixing/Mastering-Wissen)

Dieser Kern liefert die **generische Steuer-Mechanik + Cubase-Standards + eine Demo-Plugin-Map (1 Stock-Plugin/Kategorie)**. Das optionale **[yoka-cubase-premium](https://github.com/yokadeeds-dev/yoka-cubase-premium)**-Add-On ergänzt die **volle Belegung + Abdeckung + das Mixing/Mastering-Wissen**:

- **Volle Command-Belegung:** alle ~1559 vormals nicht-zugewiesenen Cubase-Commands fertig per Hotkey/MIDI gemappt (statt nur der Standards)
- **Volle Plugin-Abdeckung:** komplette gescannte Param-/CC-Map (alle Stock- + Drittanbieter-Plugins) statt nur 1 Demo-Plugin je Kategorie
- Audio-Analyse (LUFS / Spektrum / True-Peak)
- Mastering-Chain-Empfehlungen pro Genre × Plattform
- EQ-/Masking-Advice pro Track-Rolle, `nicker_*`-Tools (~30)
- FabFilter Pro-Q3 / Pro-C2 per MIDI-Learn setzen
- Traktor-Deck-Observer, DAWproject-Writer

**Zugang — erscheint in Kürze 🚧:** Das Premium-Add-On kommt über **[GitHub Sponsors](https://github.com/sponsors/yokadeeds-dev)**; die Sponsors-Seite wird gerade freigeschaltet (vsl. Mitte Juni 2026). Geplant: ab **Producer-Tier (15 €/Monat)** automatischer Zugriff auf den privaten Premium-Repo inkl. aller Updates ([Tiers](SPONSORS.md)).

Der Server erkennt das Add-On automatisch (`_premium_in_same_runtime()`). Ohne Add-On läuft er als Free-Build: die Steuer-Tools (`nicker_send_midi_cc`, `nicker_set_plugin_param` mit Demo-CC-Map) bleiben aktiv, die `nicker_*`-Wissens-Tools (Audio/Mastering/EQ/Registry) sind ausgeblendet.

## Repo-Struktur

```
yoka-cubase-mcp/
├── README.md · LICENSE (MIT) · requirements.txt
├── runtime/
│   ├── mackie/        ← MCU-Kern: parser, state, listener, sender, closedloop, units
│   ├── ahk/           ← Hotkey-Bridge-Mechanik (Standard-Commands; volle Patch-Map = Premium)
│   ├── midi_bridge/   ← Note-Send + Command-Resolver + Demo-Plugin-Map (volle Maps = Premium)
│   ├── midi_remote/   ← Cubase-MIDI-Remote-Scripts (generisch: Command- + Value-Steuer-JS)
│   ├── osc/           ← OSC-Bridge
│   ├── setup/         ← Cubase Port-Setup-Parser
│   ├── audio/         ← Playback
│   └── mcp/server.py  ← 40 Core-Tools (Premium-Hook für Add-On)
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
| MCP-Server (40 Core-Tools) | ✅ produktiv |
| AHK-Bridge-Mechanik (Standard-Commands + Macros) | ✅ produktiv |
| Generische Command-/Plugin-Steuer-Mechanik (MIDI Remote) | ✅ live verifiziert (volle Belegungs-/Plugin-Maps = Premium) |
| MIDI-Note-Recording (autonom) | ✅ end-to-end verifiziert |
| macOS-Port | ⏳ Stub, ungetestet |

## Lizenz

[MIT](LICENSE) © 2026 Yoka. Frei nutzbar, fork- und modifizierbar — nur der Copyright-Hinweis muss erhalten bleiben.

## Credits

Konzeption: Yoka. Implementierung: Yoka + Claude Code. Mackie Control Universal Protokoll-Spezifikation: Mackie / LOUD Audio. Kein Bezug zu oder Endorsement durch Steinberg, Ableton oder Native Instruments.
