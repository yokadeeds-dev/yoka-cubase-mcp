# Setup: Cubase + loopMIDI für den Mackie-Listener

**Ziel:** Cubase sendet Mackie-Control-Messages auf einen virtuellen MIDI-Port, den unser Listener lesen kann. Ein zweiter Port übernimmt die Senderichtung (Steuerung).

---

## 1. loopMIDI installieren

Per winget (empfohlen — Claude Code kann das selbst):

```powershell
winget install -e --id TobiasErichsen.loopMIDI
```

Oder manueller Download: [tobias-erichsen.de/software/loopmidi.html](https://www.tobias-erichsen.de/software/loopmidi.html)

Kostenlos, nur Windows. Nach der Installation startet loopMIDI automatisch in der Tray.

## 2. Zwei virtuelle Ports anlegen

In loopMIDI im Feld **"New port-name"** zwei Ports anlegen:

1. `MACKIE_FROM_CUBASE` (Cubase → Listener)
2. `MACKIE_TO_CUBASE` (Sender → Cubase, für Etappe 2)

Jeweils auf **"+"** klicken. Die Liste oben sollte beide Ports zeigen.

> ⚠️ **Namen exakt so übernehmen** — der Listener-CLI verwendet den Port-Namen direkt.

## 3. Cubase: Mackie Control hinzufügen

1. Cubase öffnen (Studio-Hauptrechner VLAGSCHIVV).
2. **Studio → Studio-Konfiguration**.
3. Links auf **+** → **Mackie Control** auswählen.
4. Im rechten Bereich:
   - **MIDI-Eingang:** `MACKIE_TO_CUBASE` (Cubase liest, was wir senden)
   - **MIDI-Ausgang:** `MACKIE_FROM_CUBASE` (Cubase sendet, was wir lesen)

> Die Richtung ist aus Cubase-Sicht: was Cubase **ausgibt**, geht an `MACKIE_FROM_CUBASE` (= Listener-Eingang). Was Cubase **empfängt**, kommt aus `MACKIE_TO_CUBASE` (= Sender-Ausgang).

5. **OK / Übernehmen.** Cubase aktiviert den MCU.

## 4. Listener-Port verifizieren

Im Repo-Root:

```powershell
py -3.11 -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements.txt
python -m runtime.mackie.listener --list-ports
```

In der Liste muss `MACKIE_FROM_CUBASE` auftauchen. Wenn nicht: loopMIDI prüfen, ggf. neu starten.

## 5. Selftest ohne MIDI-Verkehr

```powershell
python -m tests.selftests.listener_selftest
```

Erwartet: `[OK] alle Selftests bestanden`. Dieser Test braucht **keine** Cubase- oder loopMIDI-Verbindung — er füttert synthetische mido-Messages in den Parser.

## 6. Live-Listener starten

```powershell
python -m runtime.mackie.listener --port "MACKIE_FROM_CUBASE"
```

Optional mit JSON-State-Mirror auf Disk:

```powershell
python -m runtime.mackie.listener --port "MACKIE_FROM_CUBASE" --json-out runtime\state\snapshots\cubase.json
```

## 7. Erfolgskriterium Etappe 1

In Cubase eine Spur per Klick auswählen → Listener-Konsole zeigt:

```
[SELECT] track_index=N name='SPUR_NAME'
```

Wenn das passiert, ist **Etappe 1 grün**.

---

## Fehlerbilder

| Symptom | Wahrscheinliche Ursache | Fix |
|---|---|---|
| Port nicht in `--list-ports` | loopMIDI nicht aktiv oder Tippfehler | loopMIDI öffnen, Ports prüfen |
| `OSError` beim Open | Port von einem anderen Programm belegt | Cubase neu starten, Listener neu starten |
| Track-Name leer in `[SELECT]` | LCD-Update kam noch nicht | Track in Cubase neu klicken nach Listener-Start |
| Nur `[LCD]`-Logs, keine `[SELECT]` | Cubase ist im falschen Mackie-Mode (z. B. EQ-Page) | In Cubase auf Mixer-Ansicht wechseln |
| `[ENCODER]` flutet die Konsole beim Track-Wechsel | Cubase initialisiert die Display-Encoder; harmlos | ignorieren oder Filter im Listener ergänzen |

---

## Was als Nächstes (Etappe 2)

- Vollständiges Display-Parsing inkl. Reihe 2 (Werte) und 2-Char-Display (Bank/Mode)
- Timecode-Display
- Mode-Erkennung (Plugin / Send / Pan / EQ)
- VU-Meter aufnehmen und mit Decay-Logik darstellen
- State-Mirror um `active_plugin` mit Encoder-Werten erweitern

Siehe [`specs/KI_STUDIO_MACKIE_BRIEFING.md`](../specs/KI_STUDIO_MACKIE_BRIEFING.md) §3.3.
