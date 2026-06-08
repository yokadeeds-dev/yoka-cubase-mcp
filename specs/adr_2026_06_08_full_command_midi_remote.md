# ADR 2026-06-08 — Voller Cubase-Command-Zugriff via MIDI Remote API

**Status:** Implementiert + **live verifiziert 2026-06-08** (`send_cubase_command("Devices/Mixer 2")` → ch3/cc79 → Cubase oeffnete MixConsole 2)
**Kontext-Etappe:** Voll-Command-Adressierung (jenseits Hotkey-Limit)
**Cross-Ref:** [`specs/cubase_midi_remote_api_notes.md`](cubase_midi_remote_api_notes.md),
[`specs/adr_2026_05_06_plugin_control_architecture.md`](adr_2026_05_06_plugin_control_architecture.md),
[`runtime/persona/knowledge/midi_channel_layout.json`](../runtime/persona/knowledge/midi_channel_layout.json)

---

## Problem

Die KI soll **alle** Cubase-Commands triggern koennen. Tastatur-Hotkeys sind
auf den freien Kombo-Raum limitiert (Cubase akzeptiert nur Ctrl/Alt/Shift als
Modifier). Realer Keymap-Stand: **656 gebunden / 1559 ungebunden** (Quelle:
`docs/cubase_keymap.csv`). Die ungebundenen sind ueber den Hotkey-Pfad nicht
erreichbar.

## Entscheidung 1 — MIDI Remote API, nicht Generic Remote

| Kriterium | Generic Remote | **MIDI Remote API** |
|---|---|---|
| Status Cubase 15 | Legacy / Editor entfernt | aktiv, supported, vollstaendig auf Platte (`Driver Scripts/.api/v1`) |
| Generierbar | nur per UI-Import | flaches JS — direkt aus Mapping-JSON erzeugbar |
| API verifiziert | — | `makeCommandBinding(surfaceValue, category, command)` + `mMidiBinding.setInputPort(in).bindToControlChange(ch, cc)` |

Der Generic-Remote-Editor existiert in Cubase 15 faktisch nicht mehr
([Steinberg-Forum](https://forums.steinberg.net/t/generic-remote-midi-devices-legacy-removed-no-idea-why/903122)).
MIDI Remote ist der einzige tragfaehige Pfad und zugleich der bessere
(scriptbar, versionierbar). Deckt sich mit der Vorab-Recherche von 2026-05-13.

## Entscheidung 2 — Dedizierter Port `AI_CMD`, getrennt von `AI_INPUT`

- `AI_INPUT` traegt Plugin-**Parameter**-CCs zu scharfgeschalteten MIDI-Spuren
  (Plugin-MIDI-Learn-Ebene, siehe `midi_channel_layout.json`).
- `AI_CMD` traegt **Command**-CCs. Der MIDI Remote konsumiert sie; sie
  erreichen nie eine Spur.
- → Die beiden Ebenen teilen sich **keinen** Adressraum. Kein Cross-Talk mit
  der Plugin-Param-Belegung (CC20-119 je Bus-Kanal).

## Entscheidung 3 — Scope + deterministische Allokation

- Gemappt werden alle **1559 ungebundenen** Commands. Die 656 bereits per
  Hotkey gebundenen bleiben auf dem AHK-Pfad (`ahk_send_action`). Zusammen =
  100 % aller 2215 Commands erreichbar.
- Sortierung `(Category, Command)`, Index i → `channel = i // 128`,
  `cc = i % 128`. 16 × 128 = 2048 Adressen, 1559 belegt, 489 Reserve.
- Trigger: CC-Wert **127** (Button-Press) → Command feuert.

## Architektur — Single Source of Truth

```
docs/cubase_keymap.csv                           (Quelle, versioniert)
        │  outputs/generate_cubase_midi_remote.py
        ├─► runtime/midi_bridge/cubase_command_midi_map.json   (kanonisches Mapping + Quell-Hash)
        └─► runtime/midi_remote/ki_studio_command_remote.js    (regeneriertes Artefakt)
                     │  --install (Backup)
                     └─► Documents/Steinberg/Cubase/MIDI Remote/Driver Scripts/Local/KI Studio/

runtime/midi_bridge/cubase_commands.py   resolve(name)→(ch,cc) + send_cubase_command()
runtime/mcp/server.py                    MCP-Tool send_cubase_command(command_name, port?)
tests/selftests/cubase_commands_selftest.py   Integritaet + Drift-Guard (Hash) in CI
```

Das JSON ist kanonisch; das JS ist jederzeit regenerierbar. Faellt die MIDI
Remote API kuenftig weg, wird aus demselben JSON ein anderer Cubase-seitiger
Adapter erzeugt — die KI-Seite (Resolver + MCP-Tool) bleibt unveraendert.

## Konsequenzen / offen

- **Manuelle Voraussetzung:** loopMIDI-Port `AI_CMD` muss existieren; das
  Script muss in Cubase (MIDI Remote Manager) aktiv sein. Kann nicht
  programmatisch angelegt werden (loopMIDI-GUI).
- **Pfad-/Namens-Falle (README_v1.html):** Pflicht-Struktur ist
  `Local/<vendor>/<device>/<vendor>_<device>.js`. Die JS-**Datei** MUSS exakt
  `<vendor>_<device>.js` heissen (lowercase, Underscore) — sonst ueberspringt
  der Scanner sie STILL (kein Listeneintrag, kein Fehler). Der Generator
  installiert nach `Local/ki_studio/command_remote/ki_studio_command_remote.js`.
  Die Anzeige-Namen (mit Leerzeichen) kommen aus `makeDeviceDriver()` und sind
  von Ordner/Datei unabhaengig. Rescan: Refresh-Button im Manager genuegt fuer
  neue Scripts; alternativ 'Reload Scripts' in der Script-Console.
- **Feedback:** Der Pfad ist fire-and-forget. `send_cubase_command` meldet
  `verified=false` — ob Cubase den Command ausfuehrte, ist ueber MIDI nicht
  rueckmeldbar. Verifikation nur via Live-Beobachtung (Schritt 5).
- **Command-Kategorie-Gueltigkeit:** Ungueltige (category, command)-Paare
  ueberspringt Cubase beim Script-Load still; bricht das Script nicht.
- **Bound-Commands:** `send_cubase_command` adressiert nur die MIDI-gemappten
  (ungebundenen). Ein vereinheitlichter Router (bound→AHK / unbound→MIDI) ist
  ein moeglicher Folgeschritt.

## Regeneration

```
python outputs/generate_cubase_midi_remote.py            # JSON + JS (Repo)
python outputs/generate_cubase_midi_remote.py --install  # + JS nach Cubase (Backup)
python -m tests.selftests.cubase_commands_selftest        # Integritaet pruefen
```
Nach jeder Aenderung an `docs/cubase_keymap.csv` neu generieren — sonst schlaegt
der Hash-Drift-Guard im Selftest/CI an.
