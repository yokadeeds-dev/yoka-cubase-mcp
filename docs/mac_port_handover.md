# Mac-Port — Handover-Briefing für Mac-Claude

Diese Doku ist der Briefing-Brief für eine Claude-Code-Session auf macOS, die den Stack auf Tahoe (macOS 26) zum Laufen bringt.

---

## Stand bei Übergabe

**Windows-Stack (Hauptort `C:\Users\<user>\Documents\Claude\Projects\KI Studio 2026`):**
- 26 MCP-Tools live
- 42/42 Selftests grün
- Cubase 15 + Ableton Live 12 cross-DAW funktioniert
- 8 Etappen abgeschlossen (1, 2, 2.5, 3, 4, 4-Phase-A, 5, 6, Polish-Sprint)
- Repo gepusht zu `https://github.com/yokadeeds-dev/ki-studio-mackie` (privat)

**Was Mac-spezifisch ist (90 % portabel):**
- `runtime/ahk/_win_impl.py` — pywin32-basierte Window-Detection + Key-Send
- Restlicher Stack (parser, listener, sender, state, closedloop, mcp/server) ist plattform-agnostisch

**Was schon vorbereitet ist:**
- `runtime/ahk/_mac_impl.py` — Mac-Stub mit osascript-basierter Implementierung (UNGETESTET, blind aus Windows-Session geschrieben)
- `runtime/ahk/bridge.py` — Plattform-Dispatcher, lädt automatisch `_mac_impl` auf macOS, `_win_impl` auf Windows
- Tools-API ist plattform-agnostisch (`save_project(daw)` etc. funktioniert überall, intern wird Cmd statt Ctrl auf Mac genutzt)

---

## Mac-Setup-Checkliste

### 1. Python 3.11+ installieren

```bash
# via Homebrew
brew install python@3.11

# oder via uv (schneller, moderner)
brew install uv
uv venv -p 3.11 .venv
source .venv/bin/activate
```

### 2. Dependencies installieren

```bash
pip install -r requirements.txt
```

Auf Mac brauchen wir **kein pywin32**. Die Datei `requirements.txt` listet `mido`, `python-rtmidi`, `mcp` — alle drei laufen nativ auf macOS.

### 3. IAC-Driver für virtuelle MIDI-Ports

macOS hat einen integrierten loopMIDI-Äquivalent, den **IAC Driver**:

1. Öffne **Audio MIDI Setup** (`/Applications/Utilities/Audio MIDI Setup.app`)
2. Menü **Window → Show MIDI Studio**
3. Doppelklick auf **IAC Driver**
4. Häkchen bei **"Device is online"**
5. Im Bereich **"Ports"** mit `+` Ports anlegen:
   - `MACKIE_FROM_CUBASE`
   - `MACKIE_TO_CUBASE`
   - `MACKIE_FROM_ABLETON`
   - `MACKIE_TO_ABLETON`
   - (für Logic / Traktor analog später)
6. **Apply** klicken

Die Ports erscheinen system-weit als MIDI-Geräte und sind via `mido.get_input_names()` / `get_output_names()` ansprechbar.

### 4. DAW-Mackie-Konfiguration

**Cubase Mac:**
- Studio → Studio-Konfiguration → Mackie Control hinzufügen
- MIDI-Eingang: `MACKIE_TO_CUBASE`
- MIDI-Ausgang: `MACKIE_FROM_CUBASE`

**Ableton Live 12 Mac:**
- Live → Preferences → Tab Link/MIDI
- Control Surface: **MackieControl** (nicht Classic, nicht XT)
- Input: `MACKIE_TO_ABLETON`
- Output: `MACKIE_FROM_ABLETON`

**Logic Pro Mac (optional):**
- Logic Pro → Control Surfaces → Setup → New → Install...
- Mackie Control auswählen, In/Out auf IAC-Ports setzen

### 5. Selftests ausführen

```bash
python -m tests.selftests.listener_selftest
```

Erwartet: 42/42 grün. **AHK-Bridge-Tests laufen auf Mac mit `_mac_impl`** — die Tests prüfen Whitelist + Validation, sollten ohne reale Cubase-Window-Detection passieren.

⚠️ **Achtung:** der existierende Test `test_ahk_bridge_window_finder_returns_none_for_missing` heißt auf Windows so, weil dort find_daw_window via win32gui sucht. Auf Mac sucht er via osascript. Sollte trotzdem grün sein wenn keine Cubase läuft (returnt None statt PID).

### 6. MCP-Server testen

```bash
python -m tests.selftests.mcp_server_smoketest
```

Erwartet: Server startet, listet 26 Tools, `get_daw_state` antwortet (StateMirror initial-leer ohne MIDI-Verkehr).

### 7. Live-Test

```bash
python -m runtime.mackie.listener --list-ports
```

Sollte die IAC-Ports zeigen + DAW-konfigurierte Ports.

```bash
python -m runtime.mackie.listener --port MACKIE_FROM_CUBASE
```

Live-Stream der Cubase-Mackie-Events.

### 8. MCP-Server in Claude Code registrieren

In `~/.claude.json`:

```json
{
  "mcpServers": {
    "ki-studio-mackie": {
      "command": "/Users/<dein-user>/Code/ki-studio-mackie/.venv/bin/python",
      "args": ["-m", "runtime.mcp.server"],
      "cwd": "/Users/<dein-user>/Code/ki-studio-mackie",
      "env": {
        "MACKIE_DAW_DEFAULT": "cubase",
        "MACKIE_LISTENER_PORT_CUBASE": "MACKIE_FROM_CUBASE",
        "MACKIE_SENDER_PORT_CUBASE": "MACKIE_TO_CUBASE",
        "MACKIE_LISTENER_PORT_ABLETON": "MACKIE_FROM_ABLETON",
        "MACKIE_SENDER_PORT_ABLETON": "MACKIE_TO_ABLETON"
      }
    }
  }
}
```

Pfade auf eigene Installation anpassen.

---

## Was Mac-Claude verifizieren soll

### Pflicht
1. **`runtime/ahk/_mac_impl.py` greift live** — `save_project`, `undo`, `redo` gegen echtes Cubase Mac
2. **Window-Guard funktioniert** — andere App davorbringen, dann `save_project` aufrufen → muss die DAW vorholen, dann Cmd+S senden
3. **Selftests bleiben grün** — auf Mac: 42/42

### Optional / Bonus
1. **Logic-Adapter** in `_mac_impl.py` (Process-Names sind schon da) und in MCP-Tools `ahk_list_actions` ergänzen
2. **Etappe 7 — Traktor-Bridge** (TSI-Mapping)
   - Yokas Hauptort für Traktor ist Mac
   - 2 IAC-Ports `MIDI_FROM_TRAKTOR` / `MIDI_TO_TRAKTOR`
   - Generic-MIDI-Controller in Traktor's Controller Manager
   - Custom-Mappings für Deck Play, Cue, Crossfader, EQ
   - Neuer Modul-Tree `runtime/traktor/`

---

## Bekannte Risiken / Edge-Cases am Mac

1. **Permission-Dialoge:** macOS zeigt erstmalig Accessibility-Permissions-Dialog wenn Python via osascript Tasten sendet. Yoka muss in **System Settings → Privacy & Security → Accessibility** das Terminal/iTerm/Claude-Code-Bin freigeben. Sonst wird key-down ignoriert.
2. **Cmd vs. Ctrl:** auf Mac ist Cmd der Save-Modifier, nicht Ctrl. `_mac_impl.DAW_ACTIONS` mappt das. Wenn einzelne Cubase-Mac-Hotkeys abweichen (z. B. Yoka hat custom mappings), Whitelist anpassen.
3. **Process-Name-Drift:** Cubase 15 heißt evtl. einfach "Cubase" oder "Cubase 15", die Liste in `_mac_impl.DAW_PROCESS_NAMES["cubase"]` versucht beide. Falls die Mac-Version anders heißt, Liste erweitern.
4. **AppleScript-Timeouts:** `osascript` Calls haben 10 s Timeout im Stub. Bei träger DAW eventuell hochsetzen.
5. **Tahoe-Spezialitäten:** macOS 26 (Tahoe) hat möglicherweise neue Privacy-Restrictions auf System Events. Im Notfall fallback auf direktes pyobjc + Quartz für synthetische Events (mehr Code, aber unabhängig von osascript-Erlaubnis).

---

## Repo-Struktur (zur Orientierung)

```
ki-studio-mackie/
├── README.md
├── pipeline_state.json
├── requirements.txt
├── specs/
│   ├── KI_STUDIO_MACKIE_BRIEFING.md          # vollständige Architektur-Spec
│   ├── KISTUDIO_MACKIE_CONCEPT_SKETCH.md     # leichte Konzept-Skizze
│   ├── MCP_INVENTORY.md                       # MCPs im Yoka-System
│   ├── persona_nicker_knowledge_base.md       # YMP-Wissens-Manifest
│   └── mackie_spec.json                       # Mackie-Protokoll-Map
├── docs/
│   ├── 01_setup_cubase_mcu.md
│   ├── etappe1_status.md ... etappe6_status.md
│   ├── etappe25_status.md
│   ├── polish_sprint_status.md
│   ├── demo_workflows.md                      # ← lesen für Tool-Beispiele
│   ├── mac_port_handover.md                   # ← diese Datei
│   └── _history/chat-planungsverlauf-01.md
├── runtime/
│   ├── mackie/
│   │   ├── parser.py                          # Pure-Funcs MIDI → Events
│   │   ├── state.py                           # StateMirror
│   │   ├── listener.py                        # MIDI-Loop + CLI
│   │   ├── sender.py                          # Send + CLI
│   │   ├── closedloop.py                      # Sender + Listener-Thread
│   │   └── units.py                           # dB ↔ value14
│   ├── ahk/
│   │   ├── bridge.py                          # ← Dispatcher (plattform-agnostisch)
│   │   ├── _win_impl.py                       # Windows-Implementierung
│   │   └── _mac_impl.py                       # Mac-Implementierung (UNGETESTET)
│   └── mcp/
│       └── server.py                          # MCP-Server mit 26 Tools
└── tests/
    └── selftests/
        ├── listener_selftest.py               # 42 Tests
        ├── closedloop_smoketest.py            # Live gegen DAW
        ├── mcp_server_smoketest.py
        ├── multidaw_live_smoketest.py
        ├── plugin_mode_observer.py
        └── plugin_mode_pages_observer.py
```

---

## Erste Aktionen für Mac-Claude

1. **Repo lesen** — README, specs/KISTUDIO_MACKIE_CONCEPT_SKETCH.md, alle docs/etappe*_status.md
2. **`_mac_impl.py` reviewen** — pyobjc-Variante als Alternative zu osascript überlegen wenn osascript-Permissions zu sperrig sind
3. **Setup laufen lassen** — Steps 1-7 oben
4. **`save_project` live testen** — gegen Cubase Mac
5. **Iterieren** wenn was nicht greift
6. **Bei Erfolg:** Branch mergen + Status-Doc `docs/etappe9_mac_status.md` schreiben
7. **Optional weiter:** Logic-Support, Traktor-Bridge

---

## Cross-Reference zur Windows-Session

Beide Sessions arbeiten auf demselben Git-Repo:

```
git pull origin main    # vor jedem Commit
git push origin main    # nach jedem Commit
```

Wenn beide Seiten parallel committen, gibt's Merge-Konflikte. Empfehlung:
- **Mac-Branch:** `mac-port` für Mac-spezifische Arbeit
- **Auf Windows-main:** weiter Polish / Persona-Vorbereitung
- Merge erst wenn beide Seiten stabil

```bash
# Mac-Side
git checkout -b mac-port
# arbeiten, committen
git push -u origin mac-port

# später Merge:
git checkout main && git pull && git merge mac-port
```
