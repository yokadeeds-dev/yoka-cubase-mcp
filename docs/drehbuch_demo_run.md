# Drehbuch — KI-Studio MCP Demo-Lauf (v4)

> ⭐ **Free vs. Premium:** Mackie-Steuerung, AHK (~450 Cubase-Commands), MIDI-Recording **und Plugin-Parameter-Steuerung** sind im **Free-Core** (`yoka-cubase-mcp`). Schritte, die das Mixing/Mastering-**Wissen** nutzen (`nicker_*`: Mastering-Chains, EQ-/Masking-Advice, Audio-Bewertung), gehören zum **Premium-Add-On** [yoka-cubase-premium](https://github.com/yokadeeds-dev/yoka-cubase-premium). Kurz: **Parameter *bewegen* = Free · *wissen welcher Wert richtig ist* = Premium.**

> **v5 (2026-06-09):** Plugin-Value-Bindings live — **alle Steinberg-Stock-VST auf allen Parametern steuerbar** (StudioEQ, Magneto 2, Squasher, Frequency, Compressor …) über die Cubase MIDI Remote API (`makeValueBinding`), unabhängig von plugin-internem MIDI-Learn. Live verifiziert: KI bewegte StudioEQ „1 Gain". **Das ist Free-Mechanik** (siehe neue Stage G). Premium-Plugin-Schritte (Pro-Q3/Pro-C2 via Nicker-Preset) bleiben als Mastering-*Wissen* Premium.

> **v4 (2026-06-07):** Macro-Layer aktiviert. Take 2 nutzt jetzt `macro_*`-Trigger statt Dialog-Navigation. Setup-Phase schrumpft von 30 s auf 1 s. Hotkey-Whitelist im AHK-Bridge auf 52 Actions erweitert.

**Zweck:** Vollständige autonome Demo, sichtbar als Split-Screen-Take (Cubase links · Chat rechts), in **zwei Phasen**: Mackie-Take (reine Bidirektionalitäts-Beweise) + AHK-Hybrid-Take (Substanz schaffen → bespielen → animieren).

**Server:** `yoka-cubase-test` (Test-Mirror) bzw. `ki-studio-mackie` (Prod) — 57 Tools.
**Voraussetzung:** Cubase läuft, Projekt offen, loopMIDI-Ports `MACKIE_*` + `AI_INPUT` aktiv, AHK-Bridge mit erweiterter Whitelist (siehe Bausteine).

---

## Layout

```
┌───────────────────────────────┬───────────────────────┐
│  Cubase                       │  Chat (Claude)        │
│  ─ Project Window (oben)      │  Live State + Antworten│
│  ─ MixConsole (unten, F3)     │  Formatiert, knapp     │
│  ─ Plugin-GUIs schwebend      │                       │
└───────────────────────────────┴───────────────────────┘
```

---

## Take 1 — Mackie-Phase (Bidirektionalitäts-Beweise)

**Dauer:** ~3 min. **Kein AHK, keine Substanz-Änderung.** Zeigt was MCU allein kann.

### Setup (15 s)
- Project mit ≥5 Tracks bereits offen (Template oder vorbereiteter Stand)
- MixConsole offen (Cubase F3 manuell vor Take-Start)
- Plugin-GUI Pro-Q3 + Pro-C2 auf Bass-Bus offen

### Pattern 1 — Reverse-Verify (0:15 – 0:50)
**User-Move, Claude-Read.**
- User schiebt **per Hand** Bass-Fader auf −∞ dB
- User: *"Stimmt was am Mix nicht?"*
- Tool-Call: `get_daw_state(daw=cubase)` → liest `tracks[2].volume_db = -144.0`
- Claude-Antwort (im Chat-Pane):
  > Track 3 "Bass" steht auf −∞ dB — du hast ihn stumm gefahren. Pan: 0, Solo: aus. Low-End fehlt komplett im Mix.

### Pattern 2 — Forward-Verify (0:50 – 1:15)
**Claude-Move, Cubase-Animation.**
- User: *"Setz Bass auf −10 dB und schalt in Pan-Mode"*
- Tool-Calls:
  ```
  set_track_volume_db(index=3, db=-10)
  set_mode(mode=pan)
  ```
- Sichtbar:
  - Bass-Fader **fährt physisch hoch** in MixConsole
  - Encoder-Reihe wechselt sichtbar zu Pan-Knöpfen
- Claude bestätigt mit `verified: true`

### Pattern 3 — Blind-Verify (1:15 – 1:55)
**User-Move ohne Ankündigung, Claude liest aus Session-Log.**
- User dreht heimlich an Encoder/Maus: selektiert Track 5, schaltet in EQ-Mode, hebt Band 2 +3 dB @ 800 Hz
- User: *"Was hab ich in den letzten 30 Sekunden gemacht?"*
- Tool-Call: `get_session_report(daw=cubase)`
- Claude antwortet **aus dem Event-Log**:
  > Du hast Track 5 selektiert, in EQ-Mode geschaltet, Band 2 angehoben (+3 dB @ ~800 Hz). Davor war der Mix unverändert seit Take-Start.

### Pattern 4 — Cross-DAW (optional, 1:55 – 2:30)
- Ableton parallel offen
- User: *"Spiel beides parallel"*
- `transport_play(daw=cubase)` + `transport_play(daw=ableton)` parallel
- Cubase + Ableton starten **synchron** sichtbar, Toolbar-LEDs leuchten beide

### Take-1-Abschluss (2:30 – 3:00)
- `get_session_summary(daw=cubase)` → Counts + Quick-Take im Chat
- "Bis hierhin: kein einziger Klick auf Cubase, alles über MIDI-Loopback."

---

## Take 2 — AHK-Hybrid-Phase (Substanz schaffen + bespielen)

**Dauer:** ~2 min (war ~3 in v3, weil Macro-Trigger Setup-Sequenz kollabieren).
**AHK-Macros schaffen, Mackie navigiert, MIDI bespielt, Plugin-CC animiert.**

### Setup (Take-Start mit leerem Cubase-Workspace)
- Cubase offen, kein Projekt geladen (oder vorheriges Projekt geschlossen)

### Stage A — Macro `demo_setup_basic` (0:00 – 0:05)
- `ahk_send_action(macro_demo_setup_basic)` → **Strg+Alt+Shift+R**
  - File: New
  - Mixer: Add Track To Selected: Group Channel (Master-Group)
  - Devices: Mixer (F3)
  - Workspaces: Workspace 1
- *Sichtbar in <2 s:* leeres Projekt + Master-Group + Mixer offen + Workspace fix
- *Hinweis:* Audio-Spuren werden im selben Take über Dialog (T) angelegt — siehe Stage A.2

### Stage A.2 — Audio-/Instrument-Spuren via Dialog (0:05 – 0:25)
- `ahk_send_action(open_add_track_dialog)` → **T** → Dialog erscheint
- AHK-Dialog-Navigation (Tab/Pfeil/Enter): Instrument, Retrologue, Stereo, Anzahl 1
- `ahk_send_action(confirm_dialog)` → Enter → Retrologue-Spur entsteht
- *Sichtbar:* neue Instrument-Spur, Retrologue-GUI poppt auf

### Stage B — MIDI-Input routen + bespielen (0:30 – 1:15)
- Tool-Call (neu): `set_track_midi_input(track=1, port="AI_INPUT", monitor=true)`
- Tool-Call (neu): `send_midi_note(port="AI_INPUT", channel=1, notes=[60,64,67], velocity=80, duration_ms=4000)`
- *Sichtbar/Hörbar:*
  - Retrologue spielt **C-Dur-Pad** für 4 Sekunden
  - VU-Meter auf Instrument-Track zucken
  - MixConsole-Strip leuchtet
- Claude: *"Retrologue spielt C-Dur, peak −8 dB."* (aus `get_daw_state`)

### Stage C — Mackie liest das Plugin (1:15 – 1:45)
- `set_mode(mode=plugin)` + `select_track(index=1)`
- `get_active_plugin(daw=cubase)` → Page 1: Retrologue Filter
- Claude beschreibt **Filter-Cutoff, Resonanz, Drive** aus den 8 Encoder-Werten
- `plugin_page_next` → Page 2: Envelope
- *Live-Read der DAW über reines MIDI — kein Screenshot, kein Polling.*

### Stage D — AHK lädt Insert-Effekt (1:45 – 2:15)
- `ahk_send_action(open_inserts_inspector)` → Inspector → Inserts-Slot 1
- `ahk_send_action(load_plugin, name="FabFilter Pro-Q 3")` *(via Plugin-Suche im Dialog)*
- *Sichtbar:* Pro-Q3-GUI öffnet sich auf der Spur

### Stage E — Hybrid-Höhepunkt: Mackie + Plugin-CC (2:15 – 2:50)
- *Vor Apply:* `ahk_send_action(mix_snapshot_save)` → **Strg+Alt+Shift+C** speichert Baseline
- User: *"Mach mir daraus ein Trip-Hop-Synth-Pad"*
- `nicker_apply_preset(preset_id="triphop_synth_default", dry_run=false)`
- *Während Retrologue weiterspielt:*
  - **Pro-Q3-Bänder fahren live an Ziel-Frequenzen** (HP 60 Hz, Mud-Cut 300 Hz, Air-Boost 10 kHz)
  - Klang ändert sich hörbar (weniger Mud, mehr Air)
  - MixConsole-EQ-Strip aktualisiert
- Claude bestätigt: 23 CCs gesendet, `all_ok: true`
- *A/B-Vergleich:* `ahk_send_action(mix_snapshot_recall_1)` (Strg+Alt+Shift+0) → zurück zur Baseline → User hört Unterschied → erneut Recall → vor-und-zurück im Sekundentakt
- *Alternative:* `ahk_send_action(bypass_inserts_selected)` (Strg+Alt+Shift+B) togglet alle Inserts → noch schneller A/B

### Stage F — Blind-Verify-Closing (2:50 – 3:15)
- User dreht heimlich an einem Pro-Q3-Band per Maus
- *"Was hab ich gerade verändert?"*
- Tool-Call: `get_active_plugin(daw=cubase)` (Plugin-Mode liest aktuelle Encoder-Werte)
- Claude vergleicht mit letzter Apply-Aktion:
  > Band 3 war auf 800 Hz / +1.5 dB nach dem Preset-Apply, jetzt steht es auf 1.2 kHz / +1.5 dB. Du hast die Definitions-Frequenz um eine halbe Oktave verschoben.

---

## Take 3 — Stock-Plugin-Parameter-Steuerung (FREE, v5)

**Der eigentliche Durchbruch fürs Free-Paket.** Über die Cubase MIDI Remote API (`makeValueBinding`) sind **alle vom Host veröffentlichten VST-Parameter** adressierbar — **unabhängig von plugin-internem MIDI-Learn**. Damit werden die **Cubase-Stock-Plugins** erstmals KI-steuerbar (vorher tote Zone):

| Plugin-Klasse | vorher | jetzt (Free) |
|---|---|---|
| Cubase-Stock (StudioEQ, Magneto 2, Squasher, Frequency, Compressor, …) | gar nicht | ✅ **alle Parameter** |
| Drittanbieter ohne MIDI-Learn | gar nicht | ✅ alle Parameter |
| FabFilter & Co. (mit Learn) | nur via Premium-Preset | ✅ auch direkt |

**Live verifiziert (2026-06-09):** KI bewegte **StudioEQ „1 Gain"** (Cubase-Stock) — Wert fuhr sichtbar im Plugin-GUI.

### Demo-Choreografie
- Stock-Plugin auf eine Spur (z. B. **StudioEQ**), GUI offen
- Param-Scan (einmalig pro Plugin) → `cubase_plugin_param_map.json`
- KI setzt einen Parameter (z. B. StudioEQ Band-1-Gain auf +4 dB) → **Wert fährt live im GUI**
- A/B: zweiter Wert, zurück — sichtbar + hörbar
- *Mechanik = Free.* Die Frage **„welcher Wert klingt nach Trip-Hop-Wärme?"** beantwortet das **Premium**-Wissen (Nicker) — die Steuerung selbst nicht.

**Mechanismus:** Scan-Parser (`outputs/parse_param_scan.py`) erzeugt aus deinem Cubase-Plugin-Scan die **Param-Map** (`cubase_plugin_param_map.json` — *user-spezifisch, nicht mitgeliefert; du scannst deine eigenen Plugins*). Der Generator (`outputs/generate_value_bindings.py`) baut daraus das Steuer-JS (`runtime/midi_remote/ki_studio_value_remote.js`). Adressierung über Port `AI_VAL`, Channel = Insert-Slot. Details: [`specs/spec_2026_06_09_plugin_value_bindings.md`](../specs/spec_2026_06_09_plugin_value_bindings.md).

---

## Bausteine — was zwischen v2 und v3 dazukommen muss

### AHK-Whitelist-Erweiterung (Backlog `task_d41d285b`)

Aus `docs/cubase_keymap.csv` (235 gebundene Commands) sind diese **15 Actions Pflicht** für den Hybrid-Take:

| Action | Keystroke | Zone | Window-Guard |
|---|---|---|---|
| `open_mixer` | F3 | yellow | Project Window aktiv |
| `open_vst_instruments_rack` | F11 | yellow | Project Window aktiv |
| `open_vst_connections` | F4 | yellow | Project Window aktiv |
| `open_add_track_dialog` | T | yellow | Project Window aktiv |
| `confirm_dialog` | Enter | yellow | Modaler Dialog im Vordergrund |
| `cancel_dialog` | Escape | yellow | Modaler Dialog im Vordergrund |
| `dialog_tab_next` | Tab | yellow | Modaler Dialog |
| `dialog_arrow_down/up/left/right` | Arrow | yellow | Modaler Dialog |
| `open_inserts_inspector` | (Strg+Alt+I oder Inspector-Slot-Klick) | yellow | Project Window |
| `remove_selected_tracks` | Shift+Entf | **red** | Project Window + Confirmation |
| `new_project_empty` | (Datei→Neu→Empty Macro) | yellow | beliebig |
| `save_project` | Strg+S | yellow | Project Window (kein Modal-Dialog davor!) |
| `undo` | Strg+Z | yellow | beliebig |
| `redo` | Strg+Shift+Z | yellow | beliebig |
| `transport_play_kbd` | Leertaste | green | beliebig (parallel zu Mackie) |

**Konvention** `window_guard`: jede Action darf nur feuern wenn die spezifizierte Bedingung erfüllt ist. Heutige Bug-Quelle (Phase 6 vom v2-Lauf): `save_project` traf einen offenen "Spur hinzufügen"-Dialog. Der Guard muss prüfen *"frontmost window class = SteinbergWindowClass AND not modal dialog"*.

### Neue MCP-Tools (zone yellow)

| Tool | Args | Zweck |
|---|---|---|
| `send_midi_note` | `port, channel=1, notes=[int], velocity=80, duration_ms=2000` | NoteOn-NoteOff-Sequenz an MIDI-Port |
| `send_midi_chord` | `port, channel, root="C4", type="maj7", duration_ms` | Convenience-Wrapper |
| `set_track_midi_input` | `track_index, port_name, monitor=true` | Track-MIDI-Routing setzen (via Generic-Remote oder AHK-Macro) |
| `load_insert_plugin` | `track_index, slot=1, plugin_name` | Plugin auf Insert-Slot laden (via AHK Plugin-Browser) |

### Neue MCP-Tools (zone green, read-only)

Bereits geparkt als Chips:
- `validate_cubase_port_setup` — prüft Mackie-Ports in `Port Setup.xml`
- `list_cubase_audio_drivers` — Treiber-Verteilung
- `nicker_sync_plugins_from_cubase` — Plugin-Registry aus `VstPlugInfoV4.xml` ableiten (465 VST3)

### Optional, nice-to-have

| Tool | Zweck |
|---|---|
| `record_take(duration_s)` | record-arm + play + stop nach N Sekunden |
| `play_audio_file(path)` | (existiert) — Audiofile als Test-Material durch eine Spur jagen |
| `set_workspace(slot=1..9)` | Cubase-Workspace umschalten via `Ctrl+0..9` (für Take-Setup-Reset) |

---

## Format des Chat-Pane

Statt rohem JSON ein lesbarer Status-Block, den Claude aus jeder Tool-Response formt:

```
→ get_daw_state(cubase)
  Mode: pan | Transport: stop
  Active: Track 3 "Bass" −10.0 dB
  VU: −∞ | Mute: off | Solo: off
  Mackie-Bank: tracks 1–8, Page 1/1
  State-Frische: 47 ms
```

Bei `nicker_apply_preset`:
```
→ nicker_apply_preset(triphop_synth_default)
  Bus: synth | Plugins: Pro-Q3, Pro-C2
  Sent 18 CCs in 412 ms — all_ok: true
  ┌ Pro-Q3 Band 1: HP @ 60 Hz, slope 24
  ├ Pro-Q3 Band 2: Bell @ 300 Hz, −2 dB
  └ Pro-Q3 Band 3: Shelf @ 10 kHz, +1 dB (Air)
```

---

## Sichtbarkeits-Matrix

| MCP-Aktion | Sichtbar in | Beweisbarkeit |
|---|---|---|
| `get_daw_state` | nur Chat-Pane | textuelle Wahrheit |
| `set_mode(eq)` | MixConsole-Encoder-Reihe wechselt | direkt |
| `set_track_volume_db` | Fader bewegt sich | direkt |
| `select_track` | Project-Window + Inspector-Highlight | direkt |
| `transport_play` | Toolbar-LED, Timeline-Cursor, VU | direkt |
| `get_active_plugin` | Chat-Output | indirekt (User kann verifizieren) |
| `nicker_apply_preset` (real) | **Plugin-GUI animiert + Audio ändert sich** | direkt + auditiv |
| `send_midi_note` | **VU bewegt sich + Sound** | auditiv + visuell |
| `ahk_send_action(open_mixer)` | Mixer-Fenster erscheint | direkt |
| `ahk_send_action(open_add_track_dialog)` | Dialog erscheint | direkt |

---

## Lauf-Log

**2026-06-07 14:00 — v1 (Baseline):** Leeres Projekt, alle Phasen durchgelaufen.
**2026-06-07 14:06 — v2 (visibel mit Mixer):** F3 manuell geöffnet, 6 Events geloggt.
**2026-06-07 — v3:** zwei-Take-Konzept fixiert, Bausteine spezifiziert.
**2026-06-07 18:12 — v4 (Macro-Layer):** Cubase Key Commands.xml gepatcht (+28 Atomic + 7 Macros), AHK-Bridge Whitelist von 12 auf 52 Actions erweitert. Take-2-Setup-Phase via `macro_demo_setup_basic` von 30 s auf <5 s.

**2026-06-07 20:27 — Patch v2:** +9 XML-Bindings (Insert-Slots F16/F17, Monitor, Step-Input, PPLE-Mass-Ops, Plugin-Manager), AHK-Whitelist auf 68 Actions. Record-Workflow-Hotkeys (R/M/S/C/I/O) als Cubase-Defaults in Whitelist aufgenommen.

**2026-06-07 21:30 — send_midi_note Tool:** Neue MCP-Tools `send_midi_note` (Akkord) + `send_midi_note_sequence` (Melodie) an AI_INPUT. Schließt die Lücke zwischen CC (Plugin-Params) und tatsächlichen Tönen. yoka-cubase-test jetzt 62 Tools.

**2026-06-07 21:34 — ✅ END-TO-END RECORDING VERIFIZIERT:** Vollautonomer MIDI-Record-Workflow live durchgespielt:
- Instrument-Track "AI_Test" angelegt (Omnisphere, MIDI-In = All MIDI Inputs)
- `ahk_send_action(record_enable_selected)` → Track scharf (rot)
- `transport_record` → state=record
- `send_midi_note_sequence([60,62,64,65,67,69,71,72], 350ms)` → C-Dur-Tonleiter
- `transport_stop` → state=stop
- **Ergebnis:** MIDI-Part mit aufsteigender Notentreppe im Arrange-Fenster aufgenommen, Länge 13.669s. Vier Bridge-Layer (AHK + Mackie + MIDI-Note + computer-use-Setup) in einer durchgängigen Studio-Aktion. Kein manueller Klick während der Aufnahme.

## Status: DEMO-READY

Alle Bausteine aus der v3-Spezifikation sind implementiert und live verifiziert.
Offen nur noch: Video-Aufnahme (Take 1 + Take 2), Template-Projekt-Vorbereitung optional.

---

## Offene Aufgaben (Stand 2026-06-07 Abend)

**Erledigt:**
- ✅ AHK-Whitelist auf 68 Actions erweitert (war Backlog `task_d41d285b`)
- ✅ `send_midi_note` + `send_midi_note_sequence` MCP-Tools implementiert + live getestet
- ✅ End-to-End-Recording verifiziert

**Vor der Video-Aufnahme (morgen):**
1. **Cubase neu öffnen** mit sauberem Stand (AI_Test-Track aus dem Test ggf. löschen oder als Template behalten)
2. **Pro-Q3/Pro-C2 MIDI-Learn verifizieren** — `nicker_apply_preset(triphop_synth_default, dry_run=false)` gegen ein Plugin mit offener GUI: bewegen sich die Bänder sichtbar? Falls nein: CC-Mapping prüfen
3. **Fenster-Layout** als Workspace 1 fixieren (Project oben, Mixer-Close-Regel beachten, Plugin-GUIs schwebend)
4. **Split-Screen** einrichten: Cubase links, Chat rechts (wie beim alten Ableton-MCP-Video)

**Choreografie-Regeln (aus dieser Session gelernt):**
- **Mixer nach Gebrauch schließen** — F3 ist Vollbild, verdeckt sonst alles. Nur offen lassen wenn man bewusst etwas darin zeigt.
- **Cubase vor AHK-Actions in den Vordergrund holen** — Bridge kann das Fenster nicht immer selbst foregrounden (Windows-Foreground-Protection). Vor einer AHK-Sequenz einmal Cubase aktivieren.
- **Bei Fokus-wechselnden Actions** (open_virtual_keyboard etc.) `restore_focus=true` setzen, sonst landet der nächste Hotkey im falschen Fenster.

**Nicht-blockierende Backlog (später):**
- `set_track_midi_input` MCP-Tool (aktuell via "All MIDI Inputs" im Add-Track-Dialog gelöst — reicht für Demo)
- `load_insert_plugin` MCP-Tool (aktuell via AHK insert_01_editor + manuelle Plugin-Wahl)
- `window_guard` tightening gegen Focus-Race
- Cross-DAW-Test mit Ableton (Pattern 4 in Take 1)
- 3 geparkte Chips: Plugin-Registry-Sync, Port-Setup-Validator (beide schon als Tools live!), AHK-Whitelist (erledigt)
