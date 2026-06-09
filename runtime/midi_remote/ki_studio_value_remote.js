//-----------------------------------------------------------------------------
// KI Studio 2026 — Value Remote (MIDI Remote API, Cubase 15)
// GENERIERT von outputs/generate_value_bindings.py — NICHT manuell editieren.
// Quelle: runtime/midi_bridge/cubase_plugin_param_map.json (sha256 ad7907f9207d…)
// Generiert: 2026-06-09 | Slots: 8 x 48 Params | Port: AI_VAL
//
// Bindet Plugin-Parameter der SELEKTIERTEN Spur an MIDI-CC:
//   Channel 1-8 (API 0-7) = Insert-Slot 0-7
//   CC 0-47 = Parameter-Index im Slot
// Plugin-agnostisch — welcher CC welchen Plugin-Param trifft, sagt
// runtime/midi_bridge/cubase_value_cc_map.json (KI/MCP-Seite).
//-----------------------------------------------------------------------------

var midiremote_api = require('midiremote_api_v1')

var deviceDriver = midiremote_api.makeDeviceDriver('KI Studio', 'Value Remote', 'KI Studio 2026')
var midiInput = deviceDriver.mPorts.makeMidiInput()

// Auto-Detection: laedt sobald ein Input-Port AI_VAL auftaucht.
deviceDriver.makeDetectionUnit().detectSingleInput(midiInput).expectInputNameContains('AI_VAL')

var surface = deviceDriver.mSurface
var page = deviceDriver.mMapping.makePage('Values')
var sel = page.mHostAccess.mTrackSelection.mMixerChannel

// Pro Insert-Slot ein InsertEffectViewer, fest auf den Slot gestellt;
// dessen mParameterBankZone liefert die Parameter via makeParameterValue().
// Knob-Koordinaten sind kosmetisch (nur fuer den Surface-Editor).
function bindSlot(slot, rowY) {
    var viewer = sel.mInsertAndStripEffects.makeInsertEffectViewer('slot' + slot)
    viewer.accessSlotAtIndex(slot)
    var bankZone = viewer.mParameterBankZone
    for (var p = 0; p < 48; p++) {
        var hostVal = bankZone.makeParameterValue()
        var knob = surface.makeKnob(p % 24, rowY + Math.floor(p / 24), 1, 1)
        knob.mSurfaceValue.mMidiBinding.setInputPort(midiInput).bindToControlChange(slot, p)
        page.makeValueBinding(knob.mSurfaceValue, hostVal)
    }
}

for (var s = 0; s < 8; s++) { bindSlot(s, s * 3) }
