# OSC-Bridge Spike — Setup + Test-Anleitung

**Datum:** 2026-05-21
**Status:** POC implementiert, wartet auf Live-Test mit Yoka
**Backlog:** Task #13
**Bezug:** Markt-Scan-Pattern #4 (OSC als DAW-agnostischer Transport)

---

## Was der Spike beweisen soll

**Frage:** Funktioniert OSC als zweiter Steuer-Layer parallel zum Mackie-Setup?
**Hypothese:** Ja — separater Python-Bridge-Prozess empfängt OSC, übersetzt zu Mackie-MIDI oder direktem plugin_control-Call.
**Wert:** Cross-Platform-Reach (TouchOSC, KI-Agents, Hardware-Controller), erweitert Mackie um eine offene Transport-Schicht.

---

## Vorbereitete Komponenten (was ich autonom gemacht habe)

| Datei | Inhalt |
|---|---|
| `runtime/osc/__init__.py` | Modul-Init mit Re-Exports |
| `runtime/osc/schema.py` | OSC-Adress-Schema (10 Adressen, Reaper/AbletonOSC-orientiert) |
| `runtime/osc/translator.py` | Translator mit 3 Backends: `mackie` / `mcp` / `dry_log` |
| `runtime/osc/server.py` | UDP-Server (python-osc), CLI mit `--port`, `--backend`, `--list-schema` |
| `tests/selftests/osc_bridge_selftest.py` | 11 Selftests — alle grün |
| `requirements.txt` | `python-osc>=1.9.0` ergänzt |

**Verifikation autonom:**
- 11/11 Selftests grün (Schema-Matching, Translator-Dispatch, dry_log + mcp Backends)
- Server-CLI funktioniert (`--list-schema` zeigt alle 10 Adressen)
- `mcp`-Backend triggert echte `apply_preset(...)`-Logik mit STC-Pattern integriert

**Was ich NICHT verifizieren konnte (braucht dich):**
- Cubase reagiert tatsächlich auf MIDI-Output aus dem `mackie`-Backend
- Latenz-Messung Cubase ↔ OSC-Bridge
- Cross-DAW: Ableton via direkter OSC (steht noch nicht im POC, würde Phase 2 sein)

---

## OSC-Adress-Schema (Stand POC)

```
/track/{idx}/volume_db      <float -144..12>    — Track-Volume in dB
/track/{idx}/volume         <float 0..1>         — normalisiert
/track/{idx}/select                              — selektieren
/transport/play
/transport/stop
/mode/{name}                                     — track/send/pan/plugin/eq/instrument
/bank/left
/bank/right
/plugin/preset/{id}         [<string bus?>]      — apply_preset
/plugin/preset/{id}/dry_run [<string bus?>]      — apply_preset mit STC dry_run
```

`idx` = Mackie-Bank-Position 0-7. `id` = preset_id aus `mix_presets.json` (z. B. `triphop_bass_default`).

---

## Test-Anleitung (für dich, ~10 Min)

### Schritt 1 — OSC-Server starten

```powershell
cd "C:\Users\<user>\Documents\Claude\Projects\KI Studio 2026"
.venv\Scripts\python.exe -m runtime.osc.server --port 9000 --backend dry_log
```

Erwartete Ausgabe:
```
OSC-Server laeuft auf 127.0.0.1:9000 (backend=dry_log, daw=cubase)
Strg+C zum Beenden.
```

Das ist der **harmloseste Test** — `dry_log` mutiert nichts, loggt nur. Reicht um zu sehen ob OSC-Empfang funktioniert.

### Schritt 2 — Aus zweitem Terminal Test-Message senden

Im **zweiten Terminal** (Server-Terminal weiter laufen lassen):

```powershell
cd "C:\Users\<user>\Documents\Claude\Projects\KI Studio 2026"
.venv\Scripts\python.exe -c "
from pythonosc.udp_client import SimpleUDPClient
c = SimpleUDPClient('127.0.0.1', 9000)
c.send_message('/transport/play', [])
c.send_message('/track/3/volume_db', [-12.5])
c.send_message('/plugin/preset/triphop_bass_default/dry_run', [])
print('OSC sent.')
"
```

Erwartete Ausgabe im **Server-Terminal**:
```
[OK] /transport/play -> mackie_transport_play  response={'dry_log': True}
[OK] /track/3/volume_db -> mackie_set_volume_db  extracted={'track_idx': 3}  args=[-12.5]  response={'dry_log': True}
[OK] /plugin/preset/triphop_bass_default/dry_run -> plugin_apply_preset_dry_run  extracted={'preset_id': 'triphop_bass_default'}  response={'dry_log': True}
```

Wenn das so kommt → **OSC-Empfang funktioniert**. Nächster Schritt: echte DAW-Aktion.

### Schritt 3 — `mcp`-Backend testen (STC dry_run, ohne DAW-Aktion)

Server neu starten mit:
```powershell
.venv\Scripts\python.exe -m runtime.osc.server --port 9000 --backend mcp
```

Dann im 2. Terminal:
```powershell
.venv\Scripts\python.exe -c "
from pythonosc.udp_client import SimpleUDPClient
c = SimpleUDPClient('127.0.0.1', 9000)
c.send_message('/plugin/preset/triphop_bass_default/dry_run', [])
"
```

Erwartete Server-Ausgabe (komplexer, weil echter dry_run-Plan):
```
[OK] /plugin/preset/triphop_bass_default/dry_run -> plugin_apply_preset_dry_run  extracted={...}  response={'ok': True, 'dry_run': True, 'preset_id': 'triphop_bass_default', 'bus': 'bass', 'plugin_results': [...]}
```

Wenn `plugin_results` mit den geplanten CCs erscheint → **STC funktioniert via OSC**.

### Schritt 4 (optional, mit echtem Cubase) — `mackie`-Backend

**Voraussetzung:** Cubase ist offen, der KI-Studio-Mackie-Setup läuft (loopMIDI `AI_INPUT`-Port da, Pro-Q3 auf Bass-Bus geladen, MIDI-Learn-Mapping aktiv).

```powershell
.venv\Scripts\python.exe -m runtime.osc.server --port 9000 --backend mackie --midi-port AI_INPUT
```

Dann:
```powershell
.venv\Scripts\python.exe -c "
from pythonosc.udp_client import SimpleUDPClient
c = SimpleUDPClient('127.0.0.1', 9000)
c.send_message('/plugin/preset/triphop_bass_default', [])
"
```

**Prüfen in Cubase:**
- Bass-Bus Pro-Q3 Band 1 → HP 30 Hz, Pro-C 2 Threshold -15
- Cubase-Undo sollte zurückrollen
- Wenn nicht: error-Output im Server-Terminal anschauen, evtl. Port-Name falsch

---

## Was ich von dir wissen will (Test-Report)

Nach dem Test bitte zurückmelden:

1. **Schritt 1+2** (dry_log) — funktioniert OSC-Empfang? Ja/Nein, falls Nein: welche Fehlermeldung?
2. **Schritt 3** (mcp+dry_run) — kommt der `plugin_results`-Plan korrekt zurück? Sind die CCs sinnvoll?
3. **Schritt 4** (mackie+echtes Cubase) — reagiert Cubase? Mit welcher Latenz fühlst du das (instant / merklich / unbrauchbar)?
4. **Crashes oder Hänger?**
5. **Was fehlt im Schema?** — Welche OSC-Adresse hättest du gerne zusätzlich?

---

## Bekannte POC-Limitierungen

- `mackie`-Backend hat aktuell nur `plugin_apply_preset` voll implementiert. Andere Aktionen (Transport, Bank, Volume) sind als Stubs vorhanden, geben `would_*` zurück ohne MIDI-Send. **Erweiterung in Phase 2** wenn Phase-1-POC bestätigt.
- Schema ist v1.0 — Yoka kann erweitern via Edit von `runtime/osc/schema.py`.
- Nur UDP, kein TCP-OSC (alle gängigen OSC-Clients nutzen UDP).
- Kein Auth/Security — bindet auf `127.0.0.1` (local-only). Bei Bedarf Bind-Host ändern via `--host 0.0.0.0`, aber dann firewallen.

---

## Phase 2 (nach Phase-1-Bestätigung)

Wenn Phase-1-POC mit `mackie`-Backend funktioniert:

1. Restliche Mackie-Aktionen (Transport, Bank, Volume, Select) voll implementieren mit echten MIDI-Sends
2. **AbletonOSC-direkt** als zweiter Translator-Pfad (Ableton hat natives OSC — `simon-kansara/ableton-live-mcp-server` als Referenz)
3. Logic-Pro über AppleScript + OSC-Receiver (Phase 3, Mac-only)
4. OSC-Tools im MCP-Server registrieren (LLM kann OSC-Messages senden lassen)
5. Echo zurück über OSC (Cubase-State per OSC ausgeben → externe Display-Sync)

---

## Cross-Reference

- [`runtime/osc/`](../runtime/osc/) — Source
- [`tests/selftests/osc_bridge_selftest.py`](../tests/selftests/osc_bridge_selftest.py) — 11 Tests grün
- [`markt_scan_2026_05_21.md`](markt_scan_2026_05_21.md) — Cluster D + E (Pattern-Quelle)
- [`adr_2026_05_21_mureka_adoption_decision.md`](adr_2026_05_21_mureka_adoption_decision.md) — Task #13 als Spike vorgesehen
