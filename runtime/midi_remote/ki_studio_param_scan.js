//-----------------------------------------------------------------------------
// KI Studio 2026 — Plugin Parameter Scanner (MIDI Remote API, Cubase 15)
//
// ZWECK: Liest die vom Host veroeffentlichten VST-Parameter-Titel der Plugins
// auf der AKTUELL SELEKTIERTEN Spur aus und schreibt sie via console.log in die
// MIDI-Remote Script Console (Cubase Lower Zone -> Tab "MIDI Remote" ->
// Kontextmenue/Zahnrad -> "Script Console" bzw. "Open API Script Console").
//
// Die Ausgabe ist die Roh-Quelle fuer outputs/parse_param_scan.py, das daraus
// runtime/midi_bridge/cubase_plugin_param_map.json erzeugt — analog zur
// Command-Map (cubase_command_midi_map.json). Aus der Param-Map generiert dann
// der (Codex-)Value-Binding-Generator das eigentliche Steuer-JS.
//
// WARUM SO: Die MIDI Remote API ist gesandboxt (kein File-IO). Param-Titel sind
// nur zur Laufzeit ueber mOnTitleChange eines an den Host-Parameter gebundenen
// SurfaceValue erreichbar. console.log ist der einzige nach-aussen sichtbare
// Kanal ohne zusaetzliche loopMIDI/Listener-Infrastruktur. (SysEx-Variante als
// spaeteres Upgrade, falls Voll-Automatisierung gewuenscht — siehe Spec.)
//
// BEDIENUNG (einmalig pro Plugin-Typ):
//   1. loopMIDI-Port "AI_SCAN" muss existieren (eigener Detection-Port, NICHT
//      AI_CMD — der ist exklusiv vom Command-Remote belegt; Cubase bindet einen
//      Input-Port nur an EINE Surface. Der Scanner konsumiert KEIN MIDI, braucht
//      den Port nur, damit das Script ueberhaupt geladen + verbunden wird).
//   2. Dieses File nach
//        <User>/Documents/Steinberg/Cubase/MIDI Remote/Driver Scripts/Local/
//          ki_studio/param_scan/ki_studio_param_scan.js
//      kopieren (install_param_scan.py --install erledigt das).
//   3. Cubase neu starten ODER MIDI Remote Manager neu scannen.
//   4. Script Console oeffnen (Lower Zone, MIDI-Remote-Tab).
//   5. Ziel-Spur mit dem zu scannenden Plugin (z.B. Magneto 2 in Insert 1)
//      SELEKTIEREN. Beim Selektieren feuern die mOnTitleChange-Callbacks und
//      fuellen die Console mit [PARAMSCAN]-Zeilen.
//   6. Console-Text markieren + kopieren -> in eine .txt speichern ->
//      python outputs/parse_param_scan.py <txt> ausfuehren.
//
// HINWEIS: GENERIERT KEINE Steuerung — reine Lese-/Scan-Hilfe. Bindet pro
// Insert-Slot SCAN_BANK_SIZE Parameter nur, um deren Titel zu erfahren; die
// Bindings sind Wegwerf (CustomValueVariable ohne MIDI-Adresse).
//-----------------------------------------------------------------------------

var midiremote_api = require('midiremote_api_v1')

var deviceDriver = midiremote_api.makeDeviceDriver('KI Studio', 'Param Scanner', 'KI Studio 2026')
var midiInput = deviceDriver.mPorts.makeMidiInput()

// Eigener Detection-Port AI_SCAN (NICHT AI_CMD — der ist exklusiv vom
// Command-Remote belegt). Der Scanner empfaengt nichts darueber, braucht den
// Match nur als Lade-/Verbindungs-Bedingung.
deviceDriver.makeDetectionUnit().detectSingleInput(midiInput).expectInputNameContains('AI_SCAN')

var surface = deviceDriver.mSurface
var page = deviceDriver.mMapping.makePage('Scan')
var sel = page.mHostAccess.mTrackSelection.mMixerChannel

// Wieviele Insert-Slots und wieviele Parameter-Positionen je Slot abgetastet
// werden. 8 Slots deckt den ueblichen Cubase-Insert-Bereich; 48 Params decken
// alle gaengigen Stock-Plugins (Magneto 2 ~10, StudioEQ ~12, Compressor ~10,
// Frequency/Squasher mehr). Bei Bedarf erhoehen — kostet nur Scan-Last.
var SCAN_SLOTS = 8
var SCAN_BANK_SIZE = 48

// Factory bindet slot/idx fest in die Closure (ES5: var-Closures wuerden sonst
// nur den letzten Schleifenwert sehen).
function makeTitleLogger(slot, idx) {
    return function (activeDevice, objectTitle, valueTitle) {
        // Leere Titel = Position jenseits der echten Param-Zahl des Plugins.
        // Trotzdem loggen waere Rauschen — der Parser filtert leere ohnehin,
        // aber wir sparen Console-Spam, indem wir leere objectTitle ueberspringen.
        if (!objectTitle && !valueTitle) { return }
        console.log(
            '[PARAMSCAN] slot=' + slot +
            ' idx=' + idx +
            ' obj="' + objectTitle + '"' +
            ' val="' + valueTitle + '"'
        )
    }
}

// Korrekte API (verifiziert via Steinberg-API-Reference): pro Insert-Slot ein
// InsertEffectViewer, mit accessSlotAtIndex(n) fest auf Slot n gestellt; dessen
// mParameterBankZone liefert die Plugin-Parameter DIREKT via makeParameterValue()
// — es gibt KEIN makeParameterBank (die Zone managt die Bank selbst), und
// mInserts[n] existiert ebenfalls NICHT. Jeder makeParameterValue()-Aufruf
// belegt die naechste Bank-Position (0,1,2,…).
for (var slot = 0; slot < SCAN_SLOTS; slot++) {
    var viewer = sel.mInsertAndStripEffects.makeInsertEffectViewer('scanViewer' + slot)
    viewer.accessSlotAtIndex(slot)
    var bankZone = viewer.mParameterBankZone
    for (var i = 0; i < SCAN_BANK_SIZE; i++) {
        var hostVal = bankZone.makeParameterValue()
        var surfVal = surface.makeCustomValueVariable('scan_s' + slot + '_p' + i)
        page.makeValueBinding(surfVal, hostVal)
        surfVal.mOnTitleChange = makeTitleLogger(slot, i)
    }
}

console.log('[PARAMSCAN] scanner geladen — Ziel-Spur selektieren, dann Zeilen ablesen. ' +
            'SCAN_SLOTS=' + SCAN_SLOTS + ' SCAN_BANK_SIZE=' + SCAN_BANK_SIZE)
