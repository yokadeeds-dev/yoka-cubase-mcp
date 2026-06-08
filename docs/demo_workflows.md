# Demo Workflows — KI-Studio Mackie

Praktische Beispiele was Claude (oder ein anderer MCP-Client) mit dem 26-Tool-Stack machen kann. Sortiert nach typischer Studio-Phase.

---

## 1. Mix-Session-Inventur

**User:** *"Was läuft gerade in Cubase?"*

**KI-Sequenz:**
```
1. list_connected_daws         → sieht: cubase + ableton initialisierbar
2. get_daw_state(daw=cubase)    → kompletter Snapshot
   → mode, transport.state, active_track, sichtbare 8 Tracks, freshness_ms
```

**Antwort-Stil:** *"Cubase ist im Track-Mode, Track 3 'LeadSynth' ist aktiv und auf -3.2 dB, Transport gestoppt. Der State-Snapshot ist 47 ms alt."*

---

## 2. Cross-DAW Co-Start

**User:** *"Spiel beides parallel ab"*

**KI-Sequenz:**
```
1. transport_play(daw=cubase)
2. transport_play(daw=ableton)
3. (parallel innerhalb 50-100 ms)
4. get_daw_state(daw=cubase)    → verify
5. get_daw_state(daw=ableton)   → verify
```

**Antwort:** *"Beide DAWs laufen, Cubase verified, Ableton verified, Versatz <100 ms."*

---

## 3. Plugin-Inspektion

**User:** *"Zeig mir die Parameter vom aktiven Plugin"*

**KI-Sequenz:**
```
1. force_track_mode(daw=cubase)         → sicherstellen Track-Mode
2. set_mode(daw=cubase, mode=plugin)    → in Plugin-Mode wechseln
3. get_active_plugin(daw=cubase)        → Page 1 (Overview)
   → "UltraChannel, 11 Pages, overview"
4. plugin_page_next(daw=cubase)         → Page 2
5. get_active_plugin(daw=cubase)        → Page 2 mit Param-Namen
   → "Tempo, TempoSync, Session, InputGain, ..."
6. plugin_page_next ... bis page_count erreicht
```

**Antwort-Stil:** *"UltraChannel auf Track 'Kick 3'. 11 Pages, hier alle 88 Parameter:* `[strukturierte Liste]` *. Welchen willst du anpassen?"*

---

## 4. Mastering-Pre-Check

**User:** *"Sind alle Spuren sauber vor Export?"*

**KI-Sequenz:**
```
1. list_tracks(daw=cubase)
2. Filtere alle tracks[] mit:
   - mute=true → Spur stumm, evtl. ungewollt
   - solo=true → Spur solo'd, andere unhörbar
   - rec_arm=true → Spur scharfgeschaltet, kein Audio im Mixdown
3. get_daw_state(daw=cubase) → check transport.state
```

**Antwort-Stil:** *"Track 5 ist solo'd — alle anderen Tracks sind in dem Mixdown nicht zu hören. Track 7 ist gemutet — kann Absicht sein. Tracks 12-14 sind rec-armed, falls du nicht aufnimmst, kannst du das ausschalten."*

---

## 5. Volume-Adjustment in dB

**User:** *"Setze Lead Synth auf -3 dB"*

**KI-Sequenz:**
```
1. list_tracks(daw=cubase)
2. Findet Track mit name='LeadSynth' oder name_resolved
   → track_index=2 (Bank-Position)
3. set_track_volume_db(daw=cubase, track_index=2, db=-3)
4. → returned: sent_value14=11876, back_to_db=-3.0
```

**Antwort:** *"Track 'LeadSynth' auf -3 dB. Cubase echoed pitch_bend nicht zurück (Hardware-Mackie-Feature), daher kein verified-Confirm — der Send ging aber durch."*

---

## 6. Session-Logging + Mix-Report

**User:** *"Logge die nächsten 20 Min meine Session, dann fass zusammen"*

**KI-Sequenz:**
```
1. start_session_log(daw=cubase)        → Log aktiv, leer
2. ... Yoka arbeitet, Listener trackt automatisch ...
   - select-Events
   - mute/solo/rec_arm-Toggles
   - mode_change
   - transport_change
   - fader (throttled 250 ms pro Kanal)
3. get_session_summary(daw=cubase)
   → strukturierter Bericht
```

**Antwort-Stil:** *"In den letzten 20 Min: 12 Track-Wechsel (Schwerpunkt auf Tracks 1, 3, 5), 3 Mode-Wechsel (track→pan→track→plugin), 5 Mute-Toggles auf Track 7 (mehrfach probiert?), 2 Plays / 2 Stops, ca. 47 Fader-Bewegungen verteilt auf alle 8 Kanäle."*

---

## 7. Bank-Navigation in großen Sessions

**User:** *"Gib mir Tracks 17-24"*

**KI-Sequenz:**
```
1. list_tracks(daw=cubase)              → aktuell sichtbar: Tracks 1-8
2. bank_right(daw=cubase)               → +8 → 9-16
3. bank_right(daw=cubase)               → +8 → 17-24
4. list_tracks(daw=cubase)              → jetzt 17-24
```

**Antwort:** *"Tracks 17-24 sind jetzt sichtbar:* `[Liste mit name_resolved]`."

---

## 8. Project speichern

**User:** *"Speicher mal"*

**KI-Sequenz:**
```
1. save_project(daw=cubase)
   → AhkBridge: find_daw_window → SetForegroundWindow
   → Verify Foreground == Cubase
   → Send Ctrl+S (Win) / Cmd+S (Mac)
   → return: { window_guard: "passed", target_window: { ... } }
```

**Antwort:** *"Cubase-Fenster fokussiert, Ctrl+S gesendet. Das Plugin- oder Project-File ist gespeichert (Cubase hat keinen Echo-Mechanismus für 'gespeichert', aber der Window-Guard ist durchgelaufen)."*

---

## 9. Idempotente Operationen erkennen

**User:** *"Stell sicher, dass Cubase im Track-Mode ist"*

**KI-Sequenz:**
```
1. force_track_mode(daw=cubase)
   → was_already_satisfied=true, elapsed_ms=0
```

**Antwort:** *"Cubase war schon im Track-Mode (`was_already_satisfied=true`), keine Aktion nötig."*

vs. wenn Mode-Wechsel nötig war:
*"Cubase war im Pan-Mode, ich habe in Track-Mode gewechselt — innerhalb 23 ms verifiziert."*

---

## 10. Cross-DAW-Routing-Check

**User:** *"Welche DAWs sind grad ansprechbar?"*

**KI-Sequenz:**
```
1. list_connected_daws
   → cubase: { listener_port, sender_port, initialized: false }
     ableton: { listener_port, sender_port, initialized: false }
2. Optional: ein get_daw_state pro DAW als Live-Test
```

**Antwort:** *"Im Registry: cubase + ableton. Ports sind konfiguriert, aber noch keine ist initialisiert. Beim ersten Tool-Call öffnet der Server lazily die MIDI-Ports."*

---

## 11. AHK-Capabilities-Check

**User:** *"Was kannst du an Hotkey-Actions in Cubase?"*

**KI-Sequenz:**
```
1. ahk_list_actions(daw=cubase)
   → ['redo', 'save_project', 'save_project_as', 'undo']
```

**Antwort:** *"In Cubase via AHK: undo, redo, save_project, save_project_as. Die Whitelist verhindert generische 'Tippe Text'-Befehle. Wenn du Export-Mixdown haben willst, brauchen wir einen Custom-Hotkey in Cubase Studio Setup, dann erweitere ich die Whitelist."*

---

## 12. Reference-Track-Vergleich (Persona Nicker, Etappe 8 Vorschau)

**User:** *"Wie sieht mein Mix gegenüber 'Reference XY' aus?"*

**KI-Sequenz (zukünftig):**
```
1. get_daw_state(daw=cubase)            → Snapshot des Live-Mix
2. start_session_log(daw=cubase)        → ab jetzt loggen
3. transport_play(daw=cubase)           → Mix abspielen
4. (Audio-Analyzer-Layer aus AbletonMCP greift VU-/LUFS-Daten ab)
5. transport_stop(daw=cubase)
6. get_session_summary(daw=cubase)      → Verlauf
7. Vergleich gegen Reference-Daten aus mem0 / ChatGPT-Archiv
```

Komplette Implementierung dieser Persona-Workflows folgt mit Etappe 8.

---

## Patterns die sich aus den Demos ergeben

1. **Read-then-Act:** zuerst State lesen, dann gezielt eingreifen. Vermeidet blinde Sends.
2. **Verify-or-Acknowledge-Quirk:** Mackie-Echo-Verhalten ist inkonsistent zwischen DAWs. KI-Antworten sollten `verified=false` als "wahrscheinlich passiert, aber nicht bestätigt" interpretieren, nicht als Fehler.
3. **Idempotenz-Awareness:** `was_already_satisfied=true` heißt "State erreicht, keine Aktion nötig" — das ist eine *positive* Antwort, kein Skip.
4. **Cross-DAW-Sequencing:** Tool-Calls für mehrere DAWs in dichter Abfolge (innerhalb ~100 ms gesendet) — der Listener-Thread pro DAW läuft parallel.
5. **Persona-Tonfall:** technisch präzise, aber nicht sterile Logs vorlesen. Erklären, was die Daten *bedeuten*, nicht nur sie ausgeben.
