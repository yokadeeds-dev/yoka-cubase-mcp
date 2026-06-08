# KI-Hotkey-Layout für Cubase 15

**Zweck:** Festlegung welche Cubase-Commands welche Tastenkombination bekommen, sodass die AHK-Bridge sie deterministisch feuern kann. Source-of-truth für drei Konsumenten:

1. **User (einmaliges Setup):** Cubase → Bearbeiten → Tastaturbefehle → Mapping eintragen
2. **AHK-Bridge:** Whitelist `action_name → keystroke`
3. **MCP-Server (`ki-studio-mackie`):** `ahk_send_action(action=<name>)` Tool

## Konvention

| Cluster | Modifier | Slots | Status |
|---|---|---|---|
| **KI-Demo-Cluster** | `Strg+Alt+Shift+<letter|digit>` | 36 (A–Z + 0–9) | weitgehend frei (nur 1 belegt: Ctrl+Alt+Shift+1 = Export Mixdown) |
| **F-Tasten erweitert** | `F13`–`F24` | 12 | physisch nicht auf jeder Tastatur, daher zweite Wahl |
| **Cubase-Defaults** | unverändert | — | F3, F11, T, Strg+S, etc. bleiben wie sie sind |

**Regel:** Wenn ein Cubase-Default-Shortcut bereits existiert und ausreicht, **nicht überschreiben**. KI-Cluster nur für ungebundene Commands oder solche, die ohne Modifier zu konfliktreich wären.

---

## Mapping

### A. Track-/Plugin-Setup (Take 2 Stage A + D)

| Action-Name | Cubase-Command | Keystroke | Quelle |
|---|---|---|---|
| `open_add_track_dialog` | AddTrack: OpenDialog | `T` | Cubase-Default |
| `confirm_dialog` | (Enter) | `Enter` | OS |
| `cancel_dialog` | (Escape) | `Escape` | OS |
| `add_audio_to_selected` | Mixer: Add Track To Selected: Audio | `Strg+Alt+Shift+A` | **neu** |
| `add_group_to_selected` | Mixer: Add Track To Selected: Group Channel | `Strg+Alt+Shift+G` | **neu** |
| `add_fx_to_selected` | Mixer: Add Track To Selected: FX Channel | `Strg+Alt+Shift+X` | **neu** |
| `add_vca_to_selected` | Mixer: Add Track To Selected: VCA Fader | `Strg+Alt+Shift+V` | **neu** |
| `open_vst_instruments_rack` | Devices: VST Instruments | `F11` | Cubase-Default |
| `open_mixer` | Devices: Mixer | `F3` | Cubase-Default |
| `open_mixer_lower` | Devices: MixConsole Lower Zone | `Alt+F3` | Cubase-Default |
| `open_vst_connections` | Devices: VST Connections | `F4` | Cubase-Default |
| `open_inserts_panel` | (Inspector Inserts Section toggle) | `Strg+Alt+Shift+I` | **neu** |

### B. MixConsole Snapshots (A/B-Switching, Take 2 Stage E + F)

| Action-Name | Cubase-Command | Keystroke | Status |
|---|---|---|---|
| `mix_snapshot_save` | MixConsole Snapshots: Save MixConsole Snapshot | `Strg+Alt+Shift+S` | **neu** |
| `mix_snapshot_recall_1` | Recall Snapshot 1 | `Strg+Alt+Shift+0` | **neu** *(0 = Reset-Slot)* |
| `mix_snapshot_recall_2` | Recall Snapshot 2 | `Strg+Alt+Shift+2` | **neu** |
| `mix_snapshot_recall_3` | Recall Snapshot 3 | `Strg+Alt+Shift+3` | **neu** |

### C. Bypass-Cluster (saubere A/B-Vergleiche)

| Action-Name | Cubase-Command | Keystroke | Status |
|---|---|---|---|
| `bypass_inserts_selected` | Mixer: Bypass: Inserts | `Strg+Alt+Shift+B` | **neu** |
| `bypass_eqs_selected` | Mixer: Bypass: EQs | `Strg+Alt+Shift+E` | **neu** |
| `bypass_sends_selected` | Mixer: Bypass: Sends | `Strg+Alt+Shift+N` | **neu** |
| `bypass_strip_selected` | Mixer: Bypass: Channel Strip | `Strg+Alt+Shift+H` | **neu** *(H = Channel-Hardware)* |
| `bypass_modulators_selected` | Mixer: Bypass: Modulators | `Strg+Alt+Shift+W` | **neu** |

### D. PPLE (Process Project Logical Editor) — projektweite Macros

| Action-Name | Cubase-Command | Keystroke | Status |
|---|---|---|---|
| `ppl_toggle_eq_bypass_selected` | PPLE: Toggle EQ Bypass of Selected Tracks | `Strg+Alt+Shift+Q` | **neu** |
| `ppl_toggle_inserts_bypass_selected` | PPLE: Toggle Inserts Bypass of Selected Tracks | `Strg+Alt+Shift+J` | **neu** |
| `ppl_toggle_sends_bypass_selected` | PPLE: Toggle Sends Bypass of Selected Tracks | `Strg+Alt+Shift+K` | **neu** |
| `ppl_hide_empty_midi` | PPLE: Switch MIDI Tracks Off and Hide if empty or short | `Strg+Alt+Shift+Y` | **neu** |
| `ppl_open_key_editor_selected` | PPLE: Open Key Editor of All MIDI Parts on Selected Tracks | `Strg+Alt+Shift+U` | **neu** |
| `ppl_open_sample_editor_selected` | PPLE: Open Sample Editor of All Selected Audio Events | `Strg+Alt+Shift+L` | **neu** |
| `ppl_quantize_16th_selected` | PPLE: Quantize Selected Data to Sixteenth | `Strg+Alt+Shift+6` | **neu** |
| `ppl_quantize_8th_selected` | PPLE: Quantize Selected Data to Eighth Note | `Strg+Alt+Shift+8` | **neu** |
| `ppl_quantize_4th_selected` | PPLE: Quantize Selected Data to Quarter Note | `Strg+Alt+Shift+4` | **neu** |

### E. Quantize-Live (für MIDI-Demo)

| Action-Name | Cubase-Command | Keystroke | Status |
|---|---|---|---|
| `quantize_iterative` | MIDI: Iterative Quantize | `Strg+Alt+Shift+5` | **neu** |
| `quantize_freeze` | MIDI: Freeze Quantize | `Strg+Alt+Shift+7` | **neu** |
| `quantize_undo` | MIDI: Undo Quantize | `Strg+Alt+Shift+9` | **neu** |

### F. Editor-Opener (Multi-Window-Demos)

| Action-Name | Cubase-Command | Keystroke | Status |
|---|---|---|---|
| `open_key_editor_lower` | Editors: Open Key Editor in Lower Zone | `Strg+Alt+Shift+P` | **neu** *(P = Piano-Roll)* |
| `open_drum_editor_lower` | Editors: Open Drum Editor in Lower Zone | `Strg+Alt+Shift+D` | **neu** |
| `open_sample_editor_lower` | Editors: Open Sample Editor in Lower Zone | `Strg+Alt+Shift+M` | **neu** *(M = Sample)* |
| `open_score_editor_lower` | Editors: Open Score Editor in Lower Zone | `Strg+Alt+Shift+O` | **neu** *(O = nOten)* |

### G. File & Edit (bestehend, hier zur Vollständigkeit)

| Action-Name | Cubase-Command | Keystroke | Status |
|---|---|---|---|
| `save_project` | File: Save | `Strg+S` | Cubase-Default |
| `save_project_as` | File: Save As | `Strg+Shift+S` | Cubase-Default |
| `undo` | Edit: Undo | `Strg+Z` | Cubase-Default |
| `redo` | Edit: Redo | `Strg+Shift+Z` | Cubase-Default |
| `select_all` | Edit: Select All | `Strg+A` | Cubase-Default |
| `delete` | Edit: Delete | `Entf` | Cubase-Default |
| `duplicate` | Edit: Duplicate | `Strg+D` | Cubase-Default |
| `transport_play_kbd` | Transport: Play/Stop | `Leertaste` | Cubase-Default |

### H. Export (bestehend Custom-Macro)

| Action-Name | Cubase-Command | Keystroke | Status |
|---|---|---|---|
| `export_mixdown_whole_song` | Macro: Export Audio Mixdown Whole Song | `Strg+Alt+Shift+1` | **bereits zugewiesen** |

---

## Tasten-Belegungs-Tabelle (kompakt)

Damit du beim Eintippen in Cubase nichts übersiehst:

| Taste | Action |
|---|---|
| `Strg+Alt+Shift+0` | mix_snapshot_recall_1 |
| `Strg+Alt+Shift+1` | export_mixdown_whole_song *(bereits)* |
| `Strg+Alt+Shift+2` | mix_snapshot_recall_2 |
| `Strg+Alt+Shift+3` | mix_snapshot_recall_3 |
| `Strg+Alt+Shift+4` | ppl_quantize_4th_selected |
| `Strg+Alt+Shift+5` | quantize_iterative |
| `Strg+Alt+Shift+6` | ppl_quantize_16th_selected |
| `Strg+Alt+Shift+7` | quantize_freeze |
| `Strg+Alt+Shift+8` | ppl_quantize_8th_selected |
| `Strg+Alt+Shift+9` | quantize_undo |
| `Strg+Alt+Shift+A` | add_audio_to_selected |
| `Strg+Alt+Shift+B` | bypass_inserts_selected |
| `Strg+Alt+Shift+D` | open_drum_editor_lower |
| `Strg+Alt+Shift+E` | bypass_eqs_selected |
| `Strg+Alt+Shift+G` | add_group_to_selected |
| `Strg+Alt+Shift+H` | bypass_strip_selected |
| `Strg+Alt+Shift+I` | open_inserts_panel |
| `Strg+Alt+Shift+J` | ppl_toggle_inserts_bypass_selected |
| `Strg+Alt+Shift+K` | ppl_toggle_sends_bypass_selected |
| `Strg+Alt+Shift+L` | ppl_open_sample_editor_selected |
| `Strg+Alt+Shift+M` | open_sample_editor_lower |
| `Strg+Alt+Shift+N` | bypass_sends_selected |
| `Strg+Alt+Shift+O` | open_score_editor_lower |
| `Strg+Alt+Shift+P` | open_key_editor_lower |
| `Strg+Alt+Shift+Q` | ppl_toggle_eq_bypass_selected |
| `Strg+Alt+Shift+S` | mix_snapshot_save |
| `Strg+Alt+Shift+U` | ppl_open_key_editor_selected |
| `Strg+Alt+Shift+V` | add_vca_to_selected |
| `Strg+Alt+Shift+W` | bypass_modulators_selected |
| `Strg+Alt+Shift+X` | add_fx_to_selected |
| `Strg+Alt+Shift+Y` | ppl_hide_empty_midi |

**Frei für spätere Erweiterung:** C, F, R, T, Z + alles ab F13.

---

## Workflow Mapping anlegen

1. Cubase öffnen → **Bearbeiten → Tastaturbefehle** (oder `Datei → Tastaturbefehle`)
2. Pro Zeile aus der Tabelle:
   - Im Suchfeld den Command-Namen tippen (z. B. *"Save MixConsole Snapshot"*)
   - In **"Tasten eingeben"**-Feld die Tastenkombination drücken (z. B. Strg+Alt+Shift+S)
   - **Zuweisen** klicken
3. Wenn Cubase eine Konflikt-Warnung zeigt: notieren und mir melden, dann passen wir die Belegung an
4. Am Ende: **Exportieren** → neue `Key Commands.xml` überschreibt die alte
5. Mir den Pfad nennen, dann re-parse ich und vergleiche Soll/Ist

## Konsequenz für die AHK-Bridge

Die Whitelist-JSON wird zu (Schema):

```json
{
  "cubase": {
    "open_mixer": {
      "key": "F3",
      "zone": "yellow",
      "window_guard": "frontmost=cubase, not_modal=true",
      "restore_focus": true
    },
    "mix_snapshot_save": {
      "key": "Ctrl+Alt+Shift+S",
      "zone": "yellow",
      "window_guard": "frontmost=cubase, not_modal=true",
      "restore_focus": true
    },
    "ppl_toggle_eq_bypass_selected": {
      "key": "Ctrl+Alt+Shift+Q",
      "zone": "yellow",
      "window_guard": "frontmost=cubase",
      "restore_focus": false
    }
    /* ... ~40 Einträge total */
  }
}
```

Damit kann jede Action über `ahk_send_action(action="mix_snapshot_save")` gefeuert werden, ohne dass die Bridge die Keys selbst kennen muss — sie nimmt sie aus der JSON. **Die JSON wird aus diesem Dokument generiert**, nicht handgepflegt.

---

## Vorsichtsmaßnahmen

- **`Strg+Alt+Shift+S` ist nahe an `Strg+Shift+S` (Save As)** — beim Eintippen aufpassen
- **`Strg+Alt+Shift+D` kollidiert nicht** mit `Strg+D` (Duplicate) — der Modifier-Cluster ist klar getrennt
- **PPLE-Commands sind oft destruktiv** (Quantize ändert Daten dauerhaft) — User sollte vor jeder PPLE-Aktion einen MixConsole-Snapshot speichern. KI muss das in der Choreografie machen.
- **`mix_snapshot_recall_0`** wäre ein guter Reset-Slot ("zurück zu Take-Start") — der zugehörige Cubase-Snapshot muss vor Take-Start manuell gespeichert werden

---

## Nächster Schritt: Macros

Sobald diese 35+ Actions liegen, kommt die nächste Abstraktionsstufe:

**Demo-Setup-Macros** — Cubase-eigene Macros, die mehrere dieser Hotkeys plus weitere atomare Commands ketten. Beispiel:

```
Macro "Demo Setup Bass Take":
  ─ New Project (Empty)
  ─ Add Track To Selected: Audio  (×4: Drums, Bass, Synth, FX-Send)
  ─ Add Track To Selected: Group Channel  (Master)
  ─ Open Mixer  (F3)
  ─ Workspace 1
```

Ein einziger Hotkey (z. B. `Strg+Alt+Shift+R` für "Reset/Restart") setzt das komplette Demo-Projekt auf.

Macros sind atomare Cubase-Commands aneinandergekettet — sie können **alles** was Cubase als Command hat, also auch die 1973 ungebundenen. Damit wird der KI-Bridge-Aufwand pro Demo-Punkt minimal.

**Geplant für die nächste Iteration dieses Dokuments:** Liste von 8–12 Demo-Macros mit konkreter Step-Sequenz, alle erreichbar über jeweils einen einzigen `Strg+Alt+Shift+...`-Hotkey aus dem oben definierten Cluster.
