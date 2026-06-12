# yoka-cubase-mcp

**Bidirektionaler semantischer Layer KI ↔ DAW** über das Mackie Control Universal (MCU) Protokoll. Eine KI versteht und steuert Cubase — verifiziert, in Echtzeit, ohne fragile UI-Automation.

> *Die KI muss nicht hören wie ein Mensch — sie muss verstehen: präzise, semantisch, kontinuierlich.*

---

## Was das ist

Ein **MCP-Server mit 64 Tools**, ansprechbar von Claude Code (oder jedem MCP-Client) aus. Die zentrale Idee: Statt eine DAW per fragiler UI-Automation oder geschlossener Hersteller-API zu steuern, sprechen wir das **MCU-Protokoll** — dasselbe, das physische Mixer-Controller (Mackie Control, Behringer X-Touch) seit 30 Jahren nutzen. Jede MCU-fähige DAW versteht es nativ, bidirektional und in Echtzeit. Obendrauf sitzt **Nicker** — ein Mixing-/Mastering-Wissens-Layer (Audio-Analyse, Mastering-Chains, Frequenz-/Masking-Advice, Plugin-Steuerung).

**Voller Funktionsumfang, offen.** Es gibt kein Premium-Gate — der komplette Code steht unter AGPL-3.0 (+ kommerzielle Lizenz). [Sponsoring](#sponsoring) ist freiwillige Unterstützung, kein Zugangsschlüssel.

Drei Bridge-Layer:

| Layer | Macht | Kanal |
|---|---|---|
| **Mackie (MCU)** | Mode, Track-Select, Volume, Transport, Plugin-Pages — **closed-loop-verifiziert** | MIDI via loopMIDI/IAC |
| **AHK** | Hotkey-Bridge für Cubase-**Commands** (Standards + volle Belegung) + Macros | synthetische Keystrokes |
| **MIDI-Send** | Note-On/Off für Recording + Command-/Plugin-Steuerung via Cubase MIDI Remote API | MIDI via loopMIDI |

**DAW-Kompatibilität — nach Layer:**

- **Mackie/MCU** (Mode, Track-Select, Volume, Transport, Plugin-Pages, State-Mirror): reines MCU-Protokoll → jede MCU-fähige DAW. **Live verifiziert: Cubase + Ableton Live 12** (Mode-Wechsel, Track-Select, State-Mirror closed-loop bestätigt). Sollte ebenso mit Nuendo, Studio One, Reaper, Bitwig, Logic, FL Studio laufen — ungetestet, Feedback willkommen. Der MCU-Funktionsumfang variiert je nach DAW.
- **AHK-Hotkey-Bridge** (Commands, Macros): Hotkeys sind **DAW-spezifisch** — Maps für Cubase + Ableton vorhanden, andere DAWs brauchen eine eigene Map.
- **Plugin-/Command-Steuerung via MIDI Remote**: **Cubase-spezifisch** (Cubase MIDI Remote API).

**Kerneigenschaften:**
- **Closed-Loop:** Jede Steuer-Aktion wartet auf das DAW-Echo und meldet `verified: true/false` — kein Hoffen, dass ein Befehl ankam.
- **State-Mirror:** `get_daw_state` liefert jederzeit Mode, Transport, aktive Spur, 8 sichtbare Strips mit Volume/Mute/Solo/VU — ohne Screenshot.
- **Command-Steuerung:** Cubase-**Standard-Commands** (mit eigenem Hotkey) direkt nutzbar; für die **volle Belegung** aller ~1559 ungebundenen Commands liegen die Generatoren *und* die fertige MIDI-Remote-Map bei.
- **Plugin-Parameter-Steuerung:** Über `makeValueBinding` (Cubase MIDI Remote API) ist **jeder vom Host veröffentlichte VST-Parameter** adressierbar — unabhängig von plugin-internem MIDI-Learn (`nicker_set_plugin_param`, Plugin by name). Live verifiziert (KI bewegte StudioEQ „1 Gain"). Mitgeliefert ist eine **Demo-CC-Map** (1 Stock-Plugin je Kategorie); deine volle Plugin-Abdeckung **scannst du selbst** mit `nicker_sync_plugins_from_cubase` (siehe [User-Daten](#user-spezifische-daten)).
- **Nicker-Wissens-Layer:** Audio-Analyse (LUFS/Spektrum/True-Peak), Mastering-Chains pro Genre×Plattform, EQ-/Masking-Advice pro Track-Rolle, Mix-Presets, Plugin-Registry.
- **Plattform-portierbar:** Windows produktiv getestet; macOS-Implementierung als Stub vorhanden.

## Architektur

```
┌─────────────────────────────────────────────────────────────┐
│  Claude Code (oder anderer MCP-Client)                       │
└──────────────────────┬──────────────────────────────────────┘
                       │ stdio MCP-Protokoll · 64 Tools
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

## Tools-Übersicht (64)

| Gruppe | Beispiele | Zone |
|---|---|---|
| **State (read-only)** | `get_daw_state`, `get_active_track`, `get_active_plugin`, `list_tracks`, `list_connected_daws` | grün |
| **Mackie-Steuerung** | `set_mode`, `select_track`, `bank_left/right`, `channel_left/right`, `transport_play/stop`, `plugin_page_next/prev` | gelb |
| **Volume** | `set_track_volume`, `set_track_volume_db` | gelb |
| **AHK** | `ahk_list_actions`, `ahk_send_action` (Commands + Macros), `save_project`, `undo`, `redo` | gelb/rot |
| **MIDI-Send + Plugin** | `send_midi_note(_sequence)`, `send_cubase_command` (Command by name), `nicker_send_midi_cc(_pct/_range)`, `nicker_set_plugin_param` | gelb |
| **Nicker — Mastering** | `nicker_suggest_mastering_chain`, `nicker_list_mastering_genres`, `nicker_list_mastering_platforms` | grün/gelb |
| **Nicker — Mix/Frequenz** | `nicker_freq_advice`, `nicker_find_masking_conflicts`, `nicker_suggest_track_settings`, `nicker_apply_preset`, `nicker_list_mix_presets` | grün/gelb |
| **Nicker — Audio-Analyse** | `nicker_analyze_audio_file`, `nicker_audit_audio_file`, `nicker_compare_audio_files` | grün |
| **Nicker — Plugin-Registry** | `nicker_lookup_plugin`, `nicker_get_plugin_details`, `nicker_plugin_registry_stats`, `nicker_sync_plugins_from_cubase` | grün/gelb |
| **Nicker — Wissensbasis** | `nicker_search_studium`, `nicker_get_studium_doc`, `nicker_list_studium_docs` *(optionales YMP-Repo)* | grün |
| **FabFilter / Reaktionen** | `nicker_set_pro_q3_band`, `nicker_set_pro_c2`, `nicker_log_reaction`, `nicker_reaction_summary` | gelb/grün |
| **Traktor / DAWproject** | `get_traktor_state`, DAWproject-Export | grün |
| **Session-Log** | `start_session_log`, `get_session_summary`, `get_session_report` | grün |
| **Cubase-Inspector** | `validate_cubase_port_setup`, `list_cubase_audio_drivers` | grün |
| **Transport (aufnehmend)** | `transport_record` | rot |
| **Audio** | `play_audio_file` | grün |

**Zone-Semantik:** grün = read-only, gelb = mutiert DAW-State (undobar), rot = destruktiv/explizite Intent nötig.

## User-spezifische Daten

Der **Code** deckt den vollen Funktionsumfang ab — zwei Datensätze sind aber an *dein* Setup gebunden und werden nicht mitgeliefert:

- **Plugin-Inventar / volle CC-Map:** Jede Cubase-Installation hat ein anderes Plugin-Arsenal. Scanne deins mit `nicker_sync_plugins_from_cubase` (bzw. `python -m runtime.persona.cubase_plugin_sync --apply`). Ohne Scan läuft der Server normal, die Plugin-Registry ist nur leer. Mitgeliefert ist eine Demo-CC-Map (1 Stock-Plugin/Kategorie) zum Ausprobieren.
- **YMP-Wissensbasis (Volltexte):** Die `nicker_search/get_studium_*`-Tools lesen aus einem separaten Wissens-Repo. Setze `YMP_PATH` oder lege es als Sibling-Verzeichnis ab; fehlt es, sind nur diese drei Tools inaktiv. Die strukturierten Wissens-JSONs (Mastering-Chains, Frequenz-Advice, Mix-Presets) sind dagegen dabei.

## Repo-Struktur

```
yoka-cubase-mcp/
├── README.md · LICENSE (AGPL-3.0) · LICENSING.md · CONTRIBUTING.md · requirements.txt
├── runtime/
│   ├── mackie/        ← MCU-Kern: parser, state, listener, sender, closedloop, units
│   ├── ahk/           ← Hotkey-Bridge (Standard-Commands + volle Patch-Map)
│   ├── midi_bridge/   ← Note-Send + Command-Resolver + Command-MIDI-Map + Demo-Plugin-Map
│   ├── midi_remote/   ← Cubase-MIDI-Remote-Scripts (generisch: Command- + Value-Steuer-JS)
│   ├── persona/       ← Nicker: Mastering, Frequenz-Advice, Audio-Analyse, Plugin-Registry, Wissens-Loader
│   ├── traktor/       ← Traktor-Deck-Observer
│   ├── dawproject/    ← DAWproject-Export
│   ├── osc/           ← OSC-Bridge
│   ├── setup/         ← Cubase Port-Setup-Parser
│   ├── audio/         ← Playback
│   └── mcp/server.py  ← 64 MCP-Tools
├── skills/ki-studio-nicker/  ← Nicker-Persona als Claude-Code-Skill
├── docs/              ← Setup-Guides, Demo-Workflows, Keymap-Export
├── specs/             ← Mackie-Map, Architektur-Notizen
└── tests/selftests/   ← Offline-Selftests + Live-Smoketests
```

## Installation

Drei Wege — Details und Voraussetzungen in [`INSTALL.md`](INSTALL.md):

- **Für alle (tarifunabhängig):** Bootstrap-Skript `install.ps1` (Windows) bzw. `install.sh` (macOS/Linux) — prüft die Umgebung, baut die venv, installiert die Deps, läuft Doctor/Selftest und erzeugt den fertigen Config-Block. Braucht kein Claude-Abo.
- **Komfort (Pro/Max/API):** [Claude Code](https://claude.com/claude-code) erledigt es agentisch über den Installer-Prompt in [`INSTALL.md`](INSTALL.md).
- **Manuell:** Quickstart unten.

> **Orchestrator:** Nach dem Setup steuert ein MCP-Client die 64 Tools. **Boden für alle** = Claude Desktop (inkl. Free, Einzelaktionen). **Empfohlen** = **Claude Code** für die volle agentische Orchestrierung inkl. Nicker-Skill und Closed-Loop. Mehr in [`INSTALL.md` → Orchestrator](INSTALL.md#orchestrator--wer-steuert-die-64-tools).

## Quickstart (Windows)

```powershell
# Voraussetzung: Python 3.11+, loopMIDI mit Ports:
#   MACKIE_FROM_CUBASE / MACKIE_TO_CUBASE
#   AI_INPUT (für MIDI-Note-Recording)

py -3.11 -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements.txt

# Installation prüfen (Python, Deps, MIDI-Ports, Cubase-Setup, optionale Daten)
python -m runtime.setup.doctor

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

Danach sind Sätze möglich wie *„wechsle in Cubase auf Track 3"*, *„setze den Lead-Synth auf −3 dB"*, *„welche Mastering-Chain für Trip-Hop?"*, *„nimm eine C-Dur-Tonleiter auf der scharfgeschalteten Spur auf"*.

## Erster Lauf (minimaler Workflow)

Reproduzierbar und ohne etwas zu verändern (read-only bzw. `dry_run`). Voraussetzung: Cubase offen, Projekt mit ≥ 3 Spuren, loopMIDI-Ports aktiv.

```
1. list_connected_daws                         → bestätigt: cubase initialisierbar
2. get_daw_state(daw="cubase")                 → Snapshot: Mode, Transport, 8 Strips (Vol/Mute/Solo/VU)
3. select_track(track_index=2)                 → wählt Spur 3 — verified: true (Echo vom DAW)
4. set_track_volume_db(index=2, db=-6, dry_run=true)  → zeigt die geplante Änderung, ohne zu schreiben
5. transport_play(daw="cubase") … transport_stop(daw="cubase")  → Transport an/aus, sichtbar in Cubase
```

Jeder Schritt meldet `verified: true/false` (Closed-Loop). Schritt 4 mit `dry_run=false` schreibt real (in Cubase mit Strg+Z rücknehmbar).

## Sicherheit & Zonen

Jedes Tool trägt eine **Zone**, die seinen Wirkungsgrad signalisiert:

- 🟢 **grün — read-only:** liest nur DAW-State (`get_daw_state`, `list_tracks`, `nicker_*`-Analyse). Risikolos.
- 🟡 **gelb — mutiert DAW-State (undobar):** Volume, Mode, Track-Select, Plugin-CC. In Cubase mit Strg+Z rücknehmbar.
- 🔴 **rot — destruktiv / explizite Intent nötig:** `transport_record` (kann Takes überschreiben), `save_project`.

**Worauf du achten solltest:**
- **Fenster-Fokus:** Die AHK-Hotkey-Bridge sendet synthetische Tastenanschläge an das *fokussierte* Fenster. Ein Window-Guard prüft vorher, ob Cubase vorne ist — steht ein anderes Fenster im Fokus, wird die Aktion **nicht** gesendet (kein Blindschuss in fremde Apps).
- **`dry_run` zuerst:** State-/Plugin-mutierende Tools unterstützen `dry_run=true` zur Vorschau, bevor real geschrieben wird.
- **Aufnahme:** `transport_record` kann laufende Takes überschreiben — bewusst rote Zone.
- **Keine Garantie bei falschem Setup:** Stimmen loopMIDI-Ports oder das Cubase-Mackie-Device nicht, melden Tools `verified: false` statt stillschweigend zu scheitern. `python -m runtime.setup.doctor` prüft das Setup vorab.
- **Graceful degradation:** Fehlen optionale Module (`runtime/persona`, `runtime/traktor`, z. B. nach Teilcheckout), startet der Server trotzdem und bietet die Kern-Tools an, statt zu crashen.

## Status

| Bereich | Stand |
|---|---|
| Mackie-Listener + Parser + State-Mirror | ✅ produktiv |
| Sender + Closed-Loop-Verifikation | ✅ produktiv |
| MCP-Server (64 Tools) | ✅ produktiv |
| AHK-Bridge (Standard-Commands + volle Belegung + Macros) | ✅ produktiv |
| Command-/Plugin-Steuer-Mechanik (MIDI Remote) | ✅ live verifiziert |
| Nicker (Mastering/Frequenz/Audio-Analyse) | ✅ produktiv |
| MIDI-Note-Recording (autonom) | ✅ end-to-end verifiziert |
| macOS-Port | ⏳ Stub, ungetestet |

## Sponsoring

Der volle Funktionsumfang ist frei (AGPL-3.0). Wenn dir das Projekt hilft, kannst du die Entwicklung über **[GitHub Sponsors](https://github.com/sponsors/yokadeeds-dev)** unterstützen — das ist eine freiwillige Spende, **kein** Zugangs-Gate und schaltet nichts zusätzlich frei. Details: [`SPONSORS.md`](SPONSORS.md).

## Lizenz

**Dual-Lizenz** (Details in [`LICENSING.md`](LICENSING.md)):

- **[AGPL-3.0](LICENSE)** für offene Nutzung — Copyleft + Netzwerk-Klausel (§13): wer eine modifizierte Version als Netzwerk-Dienst betreibt, muss den Quellcode offenlegen.
- **Kommerzielle Lizenz** für proprietäre Einbettung ohne AGPL-Pflichten — auf Anfrage (yoka@provolution.org).

© 2026 Yoka. Beiträge: siehe [`CONTRIBUTING.md`](CONTRIBUTING.md).

## Credits

Konzeption: Yoka. Implementierung: Yoka + Claude Code. Mackie Control Universal Protokoll-Spezifikation: Mackie / LOUD Audio. Kein Bezug zu oder Endorsement durch Steinberg, Ableton oder Native Instruments.
