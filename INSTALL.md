# Installation

## Voraussetzungen — welcher Claude?

Wichtig vorab, damit niemand im falschen Weg aufläuft:

- **Variante A (automatisch)** braucht **Claude Code** — und das gibt es **nicht im Free-Tier**.
  Erforderlich ist ein Claude **Pro**- oder **Max**-Abo bzw. API-Guthaben. Der Free-Tier
  umfasst nur die Web-/Chat-Oberfläche, nicht den Terminal-Agenten.
- **Free-User / ohne Claude-Code-Abo:** Nutze **Variante B (manuell)**. Der Server selbst
  läuft anschließend auch in **Claude Desktop** (inkl. Free-Tier) — trag ihn dort in die
  `claude_desktop_config.json` ein (Einstellungen → Entwickler → Konfiguration bearbeiten),
  gleiches `mcpServers`-Schema wie unten.

Kurz: Den **agentischen Auto-Install gibt es nur mit bezahltem Claude Code**. Die Software
und der MCP-Server selbst sind nicht an einen Tarif gebunden und laufen auch im Free-Tier
von Claude Desktop — nur eben manuell eingerichtet.

## Voraussetzungen installieren (Windows)

Ein frisches Windows hat meist nicht alles. Prüfen und ggf. installieren (per winget):

```powershell
winget install --id Python.Python.3.11 -e        # Python 3.11 (zwingend)
winget install --id Git.Git -e                   # git (zwingend)
winget install --id TobiasErichsen.loopMIDI -e   # loopMIDI (für die MIDI-Ports, s. u.)
```

Für **Variante A** zusätzlich **Claude Code** (Pro/Max/API): Installation laut
[claude.com/claude-code](https://claude.com/claude-code), danach `claude` starten und einloggen.

macOS/Linux: Python 3.11 und git über den jeweiligen Paketmanager (Homebrew/apt/dnf).
loopMIDI ist Windows-only — auf macOS übernehmen das die IAC-Ports (s. u.).

## Orchestrator — wer steuert die 64 Tools?

Installation ist das eine, **Orchestrierung** das andere: Nach dem Setup muss ein MCP-Client
die Tools tatsächlich *fahren* — Zustand lesen, mehrere Tools verketten, Echo prüfen,
korrigieren. Hier gibt es eine bewusste Stufung:

| Ebene | Client | Erfahrung |
|-------|--------|-----------|
| **Boden — für alle** | Claude Desktop (inkl. Free) | Server läuft, Tools per Chat aufrufbar, Einzelaktionen („wähle Spur 3", „−3 dB auf den Lead"). Der kostenlose On-Ramp. |
| **Decke — empfohlen** | **Claude Code** (Pro/Max/API) | Volle agentische Orchestrierung, **Nicker-Skill** (`skills/ki-studio-nicker/`), Closed-Loop-Workflows („mastere diesen Track"). Die eigentliche Erfahrung. |

Warum Claude Code als Orchestrator empfohlen ist: Das Repo bringt eine **Claude-Code-Skill**
(Nicker-Persona) mit und die 64 Tools sind auf **Closed-Loop** (`verified: true/false`)
ausgelegt — beides will agentisch in einer Schleife gefahren werden, nicht turn-basiert.
Technisch geht **jeder MCP-Client** (eigener API-Agent, andere Agent-IDEs); ohne die
Skill-/Persona-Schicht fehlt aber der Komfort.

## Variante A — Claude Code installiert es für dich (empfohlen, benötigt Pro/Max/API)

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

7. DAW-Setup:
   a) loopMIDI installieren — das kannst du fuer mich uebernehmen:
      Windows:  winget install -e --id TobiasErichsen.loopMIDI --accept-package-agreements --accept-source-agreements
                (Falls winget fehlt: manueller Download https://www.tobias-erichsen.de/software/loopmidi.html)
      macOS:    python -m runtime.setup.add_iac_ports
   b) Virtuelle Ports anlegen (GUI — das musst DU klicken; loopMIDI hat KEINE CLI dafuer,
      versuch es gar nicht erst): Starte loopMIDI und lege drei Ports an, exakt benannt:
      MACKIE_FROM_CUBASE, MACKIE_TO_CUBASE, AI_INPUT.
   c) In Cubase ein Mackie-Control-Device auf diese Ports (Eingang MACKIE_TO_CUBASE,
      Ausgang MACKIE_FROM_CUBASE) — Schritt fuer Schritt in docs/01_setup_cubase_mcu.md.
   Installiere a) selbst, fuehre mich durch b) und c), und lass mich danach nochmal
   python -m runtime.setup.doctor  laufen, bis die MIDI-/Cubase-Warnungen weg sind.
```

Claude Code zeigt dir jeden Schritt und fragt vor Änderungen nach — du behältst die Kontrolle.

## Variante B — Bootstrap-Skript (für alle, ohne Claude-Abo)

Ein deterministisches Skript macht dasselbe Headless-Setup wie Variante A, nur ohne Agent —
für jeden, auch Free-User:

```powershell
git clone https://github.com/yokadeeds-dev/yoka-cubase-mcp.git
cd yoka-cubase-mcp
.\install.ps1                              # Umgebung prüfen, venv, Deps, doctor, selftest, Config-Block erzeugen
.\install.ps1 -RegisterDesktop             # + Server automatisch in Claude Desktop eintragen (mit Backup)
.\install.ps1 -RegisterDesktop -RegisterClaudeCode   # + zusätzlich in Claude Code (CLI) registrieren
.\install.ps1 -RegisterClaudeCode -InstallSkill      # + Nicker-Skill nach ~/.claude/skills/ verlinken (volle Erfahrung)
```

Das Skript **stoppt bei jedem echten Fehler** und sagt dir, was fehlt (z. B. Python 3.11 oder
C++-Build-Tools). Ohne `-RegisterDesktop` wird deine Claude-Config nicht angefasst — du bekommst
nur den fertigen Config-Block angezeigt. `install.sh` für macOS/Linux folgt.

## Variante C — vollständig manuell

Siehe [README → Quickstart](README.md#quickstart-windows). Kurzform:

```powershell
git clone https://github.com/yokadeeds-dev/yoka-cubase-mcp.git
cd yoka-cubase-mcp
py -3.11 -m venv .venv ; .venv\Scripts\Activate.ps1     # macOS: python3.11 -m venv .venv ; source .venv/bin/activate
pip install -r requirements.txt
python -m runtime.setup.doctor                          # Diagnose
python -m tests.selftests.listener_selftest             # erwartet: [OK] bestanden
```

## MCP-Server registrieren (manuell)

Bei Variante C trägst du den Server selbst ein (Variante A/B erledigen das). **Absolute Pfade,
Forward-Slashes** — die vermeiden JSON-Escaping und werden von Python/Windows akzeptiert.

> **Zwei verschiedene Configs — nicht verwechseln:**
> - **Claude Code** liest aus `~/.claude.json` (Windows: `C:\Users\<user>\.claude.json`) — am besten per `claude mcp add` setzen, nicht von Hand editieren.
> - **Claude Desktop** liest aus `%APPDATA%\Claude\claude_desktop_config.json`.
> Der `mcpServers`-JSON-Block unten (und in der README) ist das **Claude-Desktop-Format**; für Claude Code nutze den `claude mcp add-json`-Befehl weiter unten.

**Claude Desktop** (Windows) — Datei `%APPDATA%\Claude\claude_desktop_config.json`
(Einstellungen → Entwickler → Konfiguration bearbeiten; legt die Datei bei Bedarf an):

```json
{
  "mcpServers": {
    "yoka-cubase-mcp": {
      "command": "C:/Pfad/zum/repo/.venv/Scripts/python.exe",
      "args": ["-m", "runtime.mcp.server"],
      "cwd": "C:/Pfad/zum/repo",
      "env": { "MACKIE_DAW_DEFAULT": "cubase" }
    }
  }
}
```

Danach Claude Desktop neu starten. (`install.ps1 -RegisterDesktop` macht genau das automatisch.)

**Claude Code** (CLI) — den inneren Block (ohne `mcpServers`-Wrapper) als JSON übergeben:

```powershell
claude mcp add-json yoka-cubase-mcp '{"type":"stdio","command":"C:/Pfad/zum/repo/.venv/Scripts/python.exe","args":["-m","runtime.mcp.server"],"cwd":"C:/Pfad/zum/repo","env":{"MACKIE_DAW_DEFAULT":"cubase"}}' --scope user
```

> ⚠️ Wichtig: **Forward-Slashes** im Pfad — die `claude`-CLI lehnt Backslashes in der
> command-Angabe ab.

## Volle Nutzung in Claude Code — Nicker-Skill (optional)

Die 64 Tools funktionieren **ohne** Zusatz — weder Desktop Commander noch weitere Konnektoren
oder AutoHotkey sind nötig (MIDI/pywin32/OSC stecken in den Python-Deps).

Für die **volle Erfahrung** (Nicker-Persona + fertige Workflows wie Mix-Inventur,
Pre-Export-Audit, Mastering-Chain) aktivierst du die mitgelieferte Claude-Code-Skill. Sie wird
**nicht** automatisch gefunden — Claude Code erwartet Skills unter `~/.claude/skills/`:

```powershell
# Windows (PowerShell) — Repo bleibt Source-of-Truth (Junction):
New-Item -ItemType Junction -Path "$env:USERPROFILE\.claude\skills\ki-studio-nicker" -Target "$PWD\skills\ki-studio-nicker"
```
```bash
# macOS/Linux (Symlink):
ln -s "$PWD/skills/ki-studio-nicker" ~/.claude/skills/ki-studio-nicker
```

Danach triggert Claude Code die Skill bei Sätzen wie „Ist der Mix export-ready?" oder
„Setup Mastering-Chain für Trip-Hop". Details: [`skills/ki-studio-nicker/README.md`](skills/ki-studio-nicker/README.md).

## Was Claude Code (oder du) **nicht** automatisieren kann

Zwei Schritte brauchen GUI-Interaktion bzw. eine externe App:

1. **Virtuelle MIDI-Ports** — die loopMIDI-*Installation* läuft per winget
   (`winget install -e --id TobiasErichsen.loopMIDI`), das *Anlegen der Ports* in der
   loopMIDI-GUI ist aber manuell (loopMIDI bietet keine Port-CLI — getestet mit
   v1.0.16.27). IAC (macOS) wird über `python -m runtime.setup.add_iac_ports` angelegt.
   Benötigte Ports: `MACKIE_FROM_CUBASE`, `MACKIE_TO_CUBASE`, `AI_INPUT`.
2. **Mackie-Control-Device in Cubase** — Studio → Studio-Setup → Mackie Control, Input/
   Output auf die loopMIDI/IAC-Ports. Anleitung: [`docs/01_setup_cubase_mcu.md`](docs/01_setup_cubase_mcu.md).

Der Doctor (`python -m runtime.setup.doctor`) sagt dir jederzeit, welcher dieser
Schritte noch fehlt.
