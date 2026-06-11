# Cubase-Macros für KI-Demo-Choreografien

> Die Macros (Setup, Transport, A/B-Snapshots), die Plugin-Parameter-Steuerung und die Nicker-Wissens-Schritte (`nicker_*`) sind **alle im vollen Funktionsumfang dabei** (AGPL-3.0). Deine volle Plugin-Abdeckung scannst du selbst (s. README → *User-spezifische Daten*).

**Position im Stack:**
- **Atomic-Layer:** Cubase-Defaults + KI-Hotkey-Cluster (35 Actions, siehe `drehbuch_hotkey_layout.md`)
- **Macro-Layer (dieses Dokument):** sequenzielle Verkettungen atomarer Commands, je 1 Hotkey-Trigger
- **Orchestration-Layer:** Claude/MCP feuert atomare Hotkeys *oder* Macro-Hotkeys via `ahk_send_action`

**Was Macros können / nicht können:**
- ✅ Beliebig viele atomare Commands sequenziell aneinanderketten (auch ungebundene aus den 1973)
- ✅ Cross-Category: Project + Mixer + MIDI + Edit + PPLE in einem Macro mischen
- ❌ Keine Conditionals (kein `if`)
- ❌ Keine Loops, kein Input-Prompt, keine Pause
- ❌ Kein Übergeben von Werten zwischen Schritten
- → **Sequenz nur, keine Logik.** Dafür gibt's Logical Editor und PPLE als atomare Bausteine.

**Hotkey-Reserve aus dem KI-Cluster** (`Strg+Alt+Shift+...`):
Frei: `C, F, R, T, Z` + F13–F24
Davon belegt dieses Dokument: `R, T, F, Z, C` + ggf. F13–F16

---

## Macro-Inventar (Demo-relevant)

### M1 — `demo_setup_basic`

**Hotkey:** `Strg+Alt+Shift+R` *(R = Reset/Restart)*
**Zweck:** Take-Start. Leeres Projekt → 4 Spuren + Master-Group + Mixer offen + Workspace fixiert.

```
Schritte:
  1. File: New Project (Empty)
  2. Mixer: Add Track To Selected: Audio        ─ Strip 1 wird "Audio 01"
  3. Mixer: Add Track To Selected: Audio        ─ Strip 2 "Audio 02"
  4. Mixer: Add Track To Selected: Audio        ─ Strip 3 "Audio 03"
  5. Mixer: Add Track To Selected: Audio        ─ Strip 4 "Audio 04"
  6. Mixer: Add Track To Selected: Group Channel ─ Master-Group
  7. Devices: Mixer                              ─ F3 öffnet MixConsole
  8. Workspaces: Workspace 1                     ─ Fenster-Layout fix
```

**Sichtbar:** 4 leere Audio-Spuren + Master-Group entstehen sichtbar im Project Window, Mixer poppt auf.

---

### M2 — `demo_setup_with_instrument`

**Hotkey:** `Strg+Alt+Shift+T` *(T = Track-Setup)*
**Zweck:** Wie M1, aber mit zusätzlicher Instrument-Spur für MIDI-Demo.

```
Schritte:
  1. ...M1-Sequenz (8 Schritte)...
  9.  AddTrack: OpenDialog               ─ T, Dialog öffnet sich
  10. (Dialog navigiert sich nicht automatisch — siehe Note unten)
```

**Note:** Schritt 9 öffnet den Dialog, der dann per AHK-Tab-Navigation gefüllt werden muss. Cubase hat aktuell keinen direkten Command *"Add Instrument Track with Retrologue"* — das muss über den Dialog. Alternative: Drag-Drop aus VST-Instruments-Rack (F11) → erzeugt automatisch Track. Das aber wieder nicht per Macro auslösbar.

**Workaround:** Macro M2 öffnet den Dialog, AHK-Bridge übernimmt Dialog-Navigation per `dialog_arrow_down/dialog_tab_next/confirm_dialog`.

---

### M3 — `ab_snapshot_baseline`

**Hotkey:** `Strg+Alt+Shift+0` *(belegt aus Hotkey-Layout, sinnvoll umgewidmet)*
**Zweck:** Save aktuellen Mix als "Snapshot 1 = Baseline" am Take-Start.

```
Schritte:
  1. MixConsole Snapshots: Save MixConsole Snapshot
  (Cubase fragt nicht nach — speichert in den nächsten freien Slot.
   Vorher Slot 1 manuell leeren oder mit überschreiben-akzeptiert-Default.)
```

**Verwendung:** wird **vor** Stage E der Demo (Preset-Apply) abgefeuert. Recall geht über die schon definierten `mix_snapshot_recall_1..3`.

---

### M4 — `ab_compare_toggle`

**Hotkey:** `Strg+Alt+Shift+C` *(C = Compare)*
**Zweck:** Zwischen Baseline-Snapshot und Current schnell hin-und-her.

**Cubase-Reality-Check:** Cubase hat kein eingebautes "Toggle A/B" für Snapshots. Workaround mit zwei Slots:

```
Schritte:
  1. MixConsole Snapshots: Recall Snapshot 1
  → höre Baseline
  (User feuert dieselbe Macro erneut)
  Aber das würde wieder 1 recall'en.

  → Lösung: zwei separate Hotkeys (recall_1 + recall_2 wie schon definiert),
     KI feuert abwechselnd.
```

**Konsequenz:** Macro M4 sparen. KI orchestriert direkt mit `mix_snapshot_recall_0` und `mix_snapshot_recall_2`.

---

### M5 — `solo_selected_loop`

**Hotkey:** `Strg+Alt+Shift+F` *(F = Focus)*
**Zweck:** Selektierte Spur solo + Locators auf Cycle-Marker + Loop an. Für gezielten A/B beim EQ-Tuning.

```
Schritte:
  1. Edit: Solo                          ─ Solo on (Toggle)
  2. Transport: Locators to Selection    ─ L/R Locators auf Selection
  3. Transport: Loop                     ─ Cycle On
  4. Transport: Locate Selection         ─ Cursor an L
  5. Transport: Start                    ─ Play
```

**Effekt:** Aus stehendem Mix → 1 Hotkey → die selektierte Spur spielt im Loop. KI-Workflow für Pro-Q3-Tuning: User selektiert Bass-Spur → `solo_selected_loop` → Loop läuft → KI feuert nicker_apply_preset → User hört direkt Vergleich.

---

### M6 — `prep_eq_demo`

**Hotkey:** `Strg+Alt+Shift+Z` *(Z = Zoom/Zero-In)*
**Zweck:** Pro-Q3 auf selektierter Spur öffnen + Fenster ranklicken + Pre-Bypass für sauberen Start.

```
Schritte:
  1. (Selektion vorausgesetzt)
  2. Mixer: Bypass: Inserts              ─ alle Inserts off
  3. (Manuell oder via PPLE: Pro-Q3-GUI öffnen — siehe Note)
  4. Edit: Solo                          ─ Solo on
```

**Note:** "Open Plug-in Editor on selected Track Insert 1" gibt es als Command nicht direkt. Workaround über `Open Inserts Panel` (`Strg+Alt+Shift+I`) + AHK-Doppelklick-Simulation auf Slot 1, oder über Cubase-eigene **MIDI-Remote Quick Controls** falls eingerichtet.

→ Realistisch für Take 2: User öffnet Pro-Q3-GUI vor Take-Start manuell, Macro M6 setzt nur den Pre-State (Bypass + Solo).

---

### M7 — `reset_take`

**Hotkey:** `Strg+Alt+Shift+F13` *(F13 = klar vom Setup-Hotkey getrennt)*
**Zweck:** Zwischen Takes sauber zurück zum Baseline-Zustand.

```
Schritte:
  1. Transport: Stop
  2. Transport: To Project Start
  3. MixConsole Snapshots: Recall Snapshot 1   ─ Baseline wieder
  4. Edit: Deactivate All Solo
  5. Workspaces: Workspace 1
```

**Effekt:** ein Tastendruck → Demo ist wieder bereit für nächsten Take.

---

### M8 — `finalize_and_save`

**Hotkey:** `Strg+Alt+Shift+F14`
**Zweck:** Take-Ende. Stop + alle Solos aus + Snapshot speichern + Projekt speichern.

```
Schritte:
  1. Transport: Stop
  2. Edit: Deactivate All Solo
  3. MixConsole Snapshots: Save MixConsole Snapshot
  4. File: Save
```

---

### M9 — `quantize_demo_show`

**Hotkey:** `Strg+Alt+Shift+F15`
**Zweck:** MIDI-Quantize-Demo als Live-Choreografie.

```
Schritte:
  1. Editors: Open Key Editor in Lower Zone     ─ Noten sichtbar
  2. Edit: Select All                            ─ alle Noten markieren
  3. MIDI Quantize: Set Quantize to 16th
  4. (Pause via separater zweiter Macro-Stufe — siehe Note)
```

**Note:** Echter A/B-Effekt wäre *vor Quantize → Loop hören → Quantize → Loop hören*. Das kriegt ein Macro nicht im Alleingang, weil es keine User-Pause kennt. KI feuert daher:
```
ahk_send_action(quantize_demo_show)   → öffnet Editor + selektiert + setzt 16th
transport_play_kbd                      → spielt 4s
ahk_send_action(ppl_quantize_16th_selected)   → quantisiert sichtbar
transport_play_kbd                      → spielt 4s
ahk_send_action(quantize_undo)          → zurück
```

Das ist die richtige Schichtung: **Macro = Setup-Sequenz**, **KI = Choreographie über Macros**.

---

### M10 — `cleanup_empty_tracks`

**Hotkey:** `Strg+Alt+Shift+F16`
**Zweck:** Nach Take 1 leere/kurze MIDI-Spuren ausblenden, damit MixConsole übersichtlich bleibt.

```
Schritte:
  1. PPLE: Switch MIDI Tracks Off and Hide if empty or short
```

**Note:** Ein-Schritt-Macro — eigentlich nur ein direkter Hotkey nötig (`ppl_hide_empty_midi` = `Strg+Alt+Shift+Y`). Kann gestrichen werden. Hier zur Vollständigkeit, falls man Aufräum-Workflow erweitern will.

---

## Hotkey-Matrix nach Macros

| Hotkey | Macro | Was passiert |
|---|---|---|
| `Strg+Alt+Shift+R` | M1 demo_setup_basic | leeres Projekt + 4 Audio + Group + Mixer |
| `Strg+Alt+Shift+T` | M2 demo_setup_with_instrument | M1 + Instrument-Dialog |
| `Strg+Alt+Shift+0` | M3 ab_snapshot_baseline | Snapshot 1 (Baseline) speichern |
| `Strg+Alt+Shift+F` | M5 solo_selected_loop | Solo + Locator + Loop + Play |
| `Strg+Alt+Shift+Z` | M6 prep_eq_demo | Insert-Bypass + Solo für EQ-Tuning |
| `Strg+Alt+Shift+F13` | M7 reset_take | zurück zur Baseline |
| `Strg+Alt+Shift+F14` | M8 finalize_and_save | Stop + Snapshot + Save |
| `Strg+Alt+Shift+F15` | M9 quantize_demo_show | Key Editor + Select All + 16th-Target |

Gestrichen: M4 (kein Toggle möglich), M10 (redundant zu atomaren Hotkey).

---

## Was Macros NICHT lösen — und wie wir's umgehen

| Bedarf | Macro? | Lösung |
|---|---|---|
| Conditionals (*wenn Mute aktiv, dann ...*) | nein | KI entscheidet via `get_daw_state`, feuert Variante A oder B |
| Loops (*alle Spuren durchiterieren*) | nein | PPLE — fast jeder PPLE-Eintrag IST schon eine Iteration |
| User-Input mid-flow | nein | KI feuert Macro-Sequenz mit `mcp__computer-use__wait` zwischen Schritten |
| Werte berechnen (*Bass auf −6 dB unter Master*) | nein | KI rechnet, sendet via Mackie `set_track_volume_db` |
| Plugin-Parameter setzen | nein | Mackie/Plugin-CC (`nicker_set_pro_q3_band`, `nicker_apply_preset`) |

→ Macros sind **Sequencer**, KI ist **Conductor**, Mackie/CC ist **Instrumentenspieler**, PPLE ist **vorgefertigte Bewegung**.

---

## Setup-Schritt für dich in Cubase

Pro Macro:
1. **Bearbeiten → Tastaturbefehle** → links unten Tab **"Makros"**
2. **Neu** → Name eingeben (z. B. `demo_setup_basic`)
3. Pro Schritt: links den Command suchen → **Hinzufügen**
4. Wenn fertig: ins Suchfeld den Macro-Namen tippen → in "Tasten eingeben" den Hotkey → **Zuweisen**

Wenn Macros + Hotkeys belegt sind, exportierst du erneut die `Key Commands.xml` → ich verifiziere.

---

## Implikation für das Drehbuch

In Drehbuch v3 / Take 2 ändern sich die Stage-Definitionen:

**Vorher (v3 Stage A):**
```
ahk_send_action(open_add_track_dialog) → T
AHK navigiert Dialog: Tab, Pfeil-runter (Instrument), Enter
...30 sec Setup-Schritte...
```

**Nachher mit Macro M2:**
```
ahk_send_action(macro_demo_setup_with_instrument)   → Strg+Alt+Shift+T
→ in <1 sec ist die ganze Setup-Substanz da
→ AHK übernimmt nur den letzten Dialog-Klick
```

Take-Tempo verdreifacht. Demo wird straighter, mehr Zeit für die eigentlichen Beweis-Patterns.

---

## Nächste Schritte

1. **Hotkey-Layout** in Cubase belegen (35 Atomic-Actions)
2. **Macros M1, M3, M5, M7, M8** anlegen — die 5 unmittelbar demo-relevanten
3. **Re-Export `Key Commands.xml`** → Diff-Verifikation
4. **AHK-Bridge** auf erweiterte Whitelist konfigurieren (Backlog-Task `task_d41d285b`)
5. **Drehbuch v4** schreiben — Take 1 + Take 2 mit Macro-Triggern statt Dialog-Navigation
6. **Take aufnehmen** — Split-Screen, Cubase + Chat
