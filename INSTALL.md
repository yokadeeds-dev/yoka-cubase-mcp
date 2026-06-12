# Installation

## Variante A — Claude Code installiert es für dich (empfohlen)

Wenn du [Claude Code](https://claude.com/claude-code) hast (Terminal, Desktop oder IDE),
ist der schnellste Weg, es die Installation übernehmen zu lassen: es erkennt dein OS,
baut die venv, behebt Build-Stolpersteine, registriert den MCP-Server in deiner Config
und führt dich durch das DAW-Setup.

**So geht's:** Starte Claude Code (am besten in einem leeren Ordner, in den das Repo
geklont werden soll) und gib ihm exakt diesen Prompt:

```text
Installiere und richte den MCP-Server "yoka-cubase-mcp" für mich ein. Arbeite die
Schritte der Reihe nach ab, zeig mir bei jedem das Ergebnis und stopp, wenn etwas
fehlschlägt, statt drüberzugehen:

1. Umgebung prüfen: Erkenne mein OS (Windows/macOS/Linux). Prüfe, ob Python >= 3.11
   und git installiert sind. Fehlt etwas, sag mir genau, wie ich es installiere, und
   warte, bis ich es erledigt habe.

2. Repo holen: Falls wir nicht schon im geklonten Repo sind, klone
   https://github.com/yokadeeds-dev/yoka-cubase-mcp und wechsle hinein.

3. venv + Abhängigkeiten:
   - Windows:  py -3.11 -m venv .venv ; .venv\Scripts\Activate.ps1
   - macOS/Linux:  python3.11 -m venv .venv ; source .venv/bin/activate
   Dann: pip install -r requirements.txt
   Falls python-rtmidi einen Build-Fehler wirft, installiere die nötigen Build-Tools
   (Windows: "Microsoft C++ Build Tools"; macOS: xcode-select --install; Linux:
   build-essential + libasound2-dev) und versuche es erneut.

4. Diagnose: Führe  python -m runtime.setup.doctor  aus und zeig mir das Ergebnis.
   Erkläre kurz: Warnungen zu MIDI-Ports / Cubase-Setup / Plugin-Inventar / YMP sind
   NORMAL, solange ich loopMIDI + Cubase noch nicht eingerichtet habe. Es darf aber
   KEIN Fehler (FAIL) bei Python, Dependencies oder Server-Import stehen.

5. Offline-Selftest:  python -m tests.selftests.listener_selftest  — erwartet wird
   "[OK] ... bestanden". Wenn nicht, zeig mir den Fehler.

6. MCP-Server in Claude Code registrieren: Trag den Server in meine Claude-Code-MCP-
   Konfiguration ein — mit dem ABSOLUTEN Pfad zur venv-Python und zum Repo. Nutze
   `claude mcp add` oder editiere die Config direkt. Schema:
     "yoka-cubase-mcp": {
       "command": "<ABSOLUTER_PFAD>/.venv/Scripts/python.exe   (macOS/Linux: .venv/bin/python)",
       "args": ["-m", "runtime.mcp.server"],
       "cwd": "<ABSOLUTER_PFAD_ZUM_REPO>",
       "env": { "MACKIE_DAW_DEFAULT": "cubase" }
     }
   WICHTIG (Windows): Nutze in command/cwd FORWARD-Slashes
   (z. B. C:/Users/.../yoka-cubase-mcp) — Backslashes werden von der
   `claude mcp add`-Validierung mitunter abgelehnt.
   Verifiziere danach die Verbindung: Der ueberzeugendste Beweis ist, dass Claude Code
   den Server als "Connected" listet. Ein manueller  python -m runtime.mcp.server  wartet
   bei stdio nur stumm auf Eingabe (kein Output = normal, KEIN Fehler) — Strg+C zum Beenden.

7. DAW-Setup anleiten (GUI-Schritte, die du NICHT für mich automatisieren kannst):
   - loopMIDI (Windows, https://www.tobias-erichsen.de/software/loopmidi.html) bzw.
     IAC (macOS: python -m runtime.setup.add_iac_ports) mit den Ports
     MACKIE_FROM_CUBASE, MACKIE_TO_CUBASE, AI_INPUT.
   - In Cubase ein Mackie-Control-Device auf diese Ports einrichten — Schritt für
     Schritt steht das in docs/01_setup_cubase_mcu.md.
   Führe mich durch diese Schritte und lass mich danach nochmal
   python -m runtime.setup.doctor  laufen, bis alles grün ist.
```

Claude Code zeigt dir jeden Schritt und fragt vor Änderungen nach — du behältst die Kontrolle.

## Variante B — manuell

Siehe [README → Quickstart](README.md#quickstart-windows). Kurzform:

```powershell
git clone https://github.com/yokadeeds-dev/yoka-cubase-mcp.git
cd yoka-cubase-mcp
py -3.11 -m venv .venv ; .venv\Scripts\Activate.ps1     # macOS: python3.11 -m venv .venv ; source .venv/bin/activate
pip install -r requirements.txt
python -m runtime.setup.doctor                          # Diagnose
python -m tests.selftests.listener_selftest             # erwartet: [OK] bestanden
```

## Was Claude Code (oder du) **nicht** automatisieren kann

Zwei Schritte brauchen GUI-Interaktion bzw. eine externe App:

1. **Virtuelle MIDI-Ports** — loopMIDI (Windows) ist eine separate App; IAC (macOS) wird
   über `python -m runtime.setup.add_iac_ports` angelegt. Benötigte Ports:
   `MACKIE_FROM_CUBASE`, `MACKIE_TO_CUBASE`, `AI_INPUT`.
2. **Mackie-Control-Device in Cubase** — Studio → Studio-Setup → Mackie Control, Input/
   Output auf die loopMIDI/IAC-Ports. Anleitung: [`docs/01_setup_cubase_mcu.md`](docs/01_setup_cubase_mcu.md).

Der Doctor (`python -m runtime.setup.doctor`) sagt dir jederzeit, welcher dieser
Schritte noch fehlt.
