# Cubase MIDI Remote API — Vorab-Notizen

**Stand:** 2026-05-13 (Notizen) · 2026-06-08 (Command-Ebene implementiert)
**Status:** Plugin-**Parameter**-Ebene = Recherche; **Command**-Ebene = implementiert
**Trigger:** Wenn wir Plugin-Parameter ohne internes MIDI-Learn ansprechen muessen (z.B. Cubase Stock Magneto 2, Squasher, andere)

> **Update 2026-06-08:** Die **Command**-Ebene (alle ungebundenen Cubase-Commands
> per MIDI triggern) ist jetzt umgesetzt — eigener dedizierter Port `AI_CMD`,
> generiertes Script `ki_studio_command_remote.js`, MCP-Tool `send_cubase_command`.
> Siehe [`adr_2026_06_08_full_command_midi_remote.md`](adr_2026_06_08_full_command_midi_remote.md).
> Die hier beschriebene Plugin-**Parameter**-Ebene (`makeValueBinding` auf `AI_INPUT`)
> ist davon getrennt und weiterhin offen.

---

## Was ist die MIDI Remote API

Cubase hat seit **Version 12 (2022)** eine **JavaScript-API** fuer Controller-Surfaces eingebaut. Das ist Steinbergs offizieller Ersatz fuer Generic Remote und der saubere Weg fuer KI-DAW-Kommunikation auf Cubase-Seite.

**Was sie kann:**
- Beliebige MIDI-Eingaenge auf DAW-Funktionen mappen (incl. Plugin-Parameter)
- Auch **Cubase Stock-Plugins** ansprechen (die kein internes MIDI Learn haben)
- Bidirektionales Feedback (DAW-Werte zur Hardware zurueck)
- Pages/Modi (1 Hardware-Knopf = mehrere Funktionen je Modus)
- Unbegrenzt viele Mappings (kein 8-QC-Limit)

**Was sie nicht kann:**
- Plugin in leeren Insert-Slot **laden** (das geht in Cubase grundsaetzlich nicht via MIDI)
- Plugins entfernen / Tracks erstellen

---

## Wo die Skripte liegen

```
%USERPROFILE%\Documents\Steinberg\Cubase\MIDI Remote\Driver Scripts\
  └── <VendorName>\<ProductName>\<ProductName>.js
```

Cubase scannt diesen Pfad beim Start. Skripte werden dort als JavaScript-Dateien abgelegt.

---

## Basic-Skript-Struktur

```javascript
// === KI-Studio MIDI Remote Surface ===
var midiremote_api = require('midiremote_api_v1')

var deviceDriver = midiremote_api.makeDeviceDriver(
    'YokaDeeds',           // Vendor
    'KI-Studio Surface',   // Product
    'YokaDeeds + Claude'   // Author
)

// === MIDI-Port-Definitionen ===
var midiInput  = deviceDriver.mPorts.makeMidiInput('AI_INPUT')
var midiOutput = deviceDriver.mPorts.makeMidiOutput('AI_FEEDBACK')  // optional, fuer Feedback

// Auto-Detection: Cubase findet die Surface wenn Port-Name matched
deviceDriver.makeDetectionUnit()
    .detectPortPair(midiInput, midiOutput)
    .expectInputNameContains('AI_INPUT')
    .expectOutputNameContains('AI_FEEDBACK')

// === Surface (visuell im MIDI Remote Manager) ===
var surface = deviceDriver.mSurface

// 14 Knoebe wie unser Universal-Channel-Strip
var knobs = []
for (var i = 0; i < 14; i++) {
    knobs.push(surface.makeKnob(i % 7, Math.floor(i / 7), 1, 1))
}

// === CC-Bindings ===
var ccVars = []
var ccNumbers = [20, 21, 22, 23, 24, 25, 26, 27, 28, 29, 30, 31, 32, 33]
ccNumbers.forEach(function(cc, idx) {
    var v = surface.makeCustomValueVariable('cc' + cc)
    v.mMidiBinding
        .setInputPort(midiInput)
        .bindToControlChange(0, cc)   // Channel 0 (= MIDI Ch 1)
    ccVars.push(v)
    knobs[idx].mSurfaceValue = v
})

// === Mapping-Page ===
var page = deviceDriver.mMapping.makePage('Universal Channel Strip')
var selChannel = page.mHostAccess.mTrackSelection.mMixerChannel

// Beispiel: CC32 -> Magneto 2 Drive auf der selektierten Spur
// Insert 3 = Magneto 2 (in unserer Universal-ChStrip-Konvention)
var insert3 = selChannel.mInsertAndStripEffects.mInserts[2]  // 0-indexed
var bank3 = insert3.mParameterBankZone.makeParameterBank(8)  // 8 Parameter pro Bank
var bank3Param0 = bank3.makeParameterValue()  // erster Plugin-Parameter (oft Drive)
page.makeValueBinding(ccVars[12], bank3Param0)  // ccVars[12] = CC32
```

---

## Yokas Use-Cases (Prioritaet)

### Tier 1 — Universal-Channel-Strip auf jeder Spur
- 14 CCs (CC20-33) auf 3 Plugins (EQ, Comp, Sat)
- Pro MIDI-Kanal = pro Bus (1=Bass, 2=Drums, ...)
- Selected-Track-Modus: aktiv ist die gerade fokussierte Spur

### Tier 2 — Plugin-spezifische Pages
- Page "Pro-MB" — wenn Pro-MB als Insert geladen, mehr CCs verfuegbar
- Page "Mastering" — Master-Bus-spezifische Mappings
- Wechselbar via Funktion-Knopf

### Tier 3 — Bidirektionales Feedback
- Cubase sendet aktuellen Plugin-Wert an AI_FEEDBACK-Port
- KI weiss in Echtzeit was im DAW gerade gesetzt ist
- Voraussetzung fuer Audio-Driven-Tuning (Sprint E2)

---

## Implementierungs-Roadmap

1. **Vorab-Test:** kleines Test-Skript schreiben, in `MIDI Remote\Driver Scripts\YokaDeeds\KI-Studio Surface\` ablegen, Cubase neu starten, im MIDI Remote Manager sichtbar?
2. **Universal-Channel-Strip-Skript** schreiben — mapped CC20-33 auf die Insert-Slots 1-3 der selektierten Spur
3. **Pro-Plugin-Pages** ergaenzen wenn spezialisierte Mappings noetig
4. **Feedback-Loop** wenn KI-Hoeren relevant wird (Tier-2 nach Studie)

---

## Existierende Community-Skripte als Referenz

- **bjoluc/cubase-mcu-midiremote** (GitHub) — emuliert Mackie Control via MIDI Remote API. Sehr gute Lern-Ressource.
- **Steinberg MIDI Remote Library** (im Cubase-MediaBay): vorgefertigte Surfaces fuer bekannte Controller (Behringer X-Touch, Faderport, NI Maschine, etc.)
- **Cubase Developer-Portal**: developer.steinberg.help/display/MIDIREMOTE/MIDI+Remote+API

---

## Was bisher Plugin-MIDI-Learn macht — vs MIDI Remote API

| Aspekt | Plugin-MIDI-Learn (heute) | MIDI Remote API (Zukunft) |
|---|---|---|
| Welche Plugins | nur Plugins mit eigenem Learn (FabFilter, Pro-MB) | **jedes Plugin**, auch Cubase Stock |
| Setup-Aufwand | Right-Click, CC senden, fertig | JavaScript schreiben/anpassen |
| Plugin-Wechsel | Mapping verloren wenn Plugin entfernt | Mapping ist Surface-Level, ueberlebt Plugin-Wechsel |
| Feedback | nein | ja, bidirektional |
| Parameter-Reach | nur was Plugin als MIDI-aufnehmbar published | **alle published Parameter** des Plugins |
| Komplexitaet | minimal | hoch |

---

## Wann wir die API einsetzen

**Sofort relevant:**
- Wenn Cubase Stock-Plugins wie **Magneto 2** ueber CC steuerbar gemacht werden sollen
- Wenn 8 Quick Controls pro Spur nicht reichen
- Wenn Multi-Page-Mappings sinnvoll sind (Bass-Edit-Modus vs Master-Modus)

**Spaeter (Tier-2):**
- KI-Hoeren — bidirektionales Feedback noetig
- DAW-Funktionen ueber Plugin-Parameter hinaus (Track-Mute, Send-Level via KI)

---

## Heutige Empfehlung

**Solange Yoka Plugin-MIDI-Learn fuer alle Inserts hat (3× FabFilter): MIDI Remote API noch nicht noetig.** Wir kommen mit dem einfachen Pfad sehr weit.

**Wenn Magneto 2 oder andere Cubase-Stock-Plugins eingebaut werden sollen → MIDI Remote API anpacken, ca. 2-3 Tage Setup.**

---

## Cross-Reference

- `runtime/midi_bridge/send_cc.py` — KI-MIDI-Sender (jetzt bereits funktional)
- `runtime/persona/knowledge/midi_channel_layout.json` — CC-Mappings
- `specs/adr_2026_05_06_plugin_control_architecture.md` — Architektur-ADR
