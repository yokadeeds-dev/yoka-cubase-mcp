# Skill: ki-studio-nicker

Persona Nicker als Claude-Code-Skill. Erster Pilot des Skill-Pattern-Adoption im KI-Studio (siehe ADR 2026-05-21).

## Was es ist

Eine **Workflow-Schale** über dem bestehenden MCP-Server `ki-studio-mackie`. Enthält:
- Persona-Direktiven (Tonfall, Wissensbasis-Vorrang, Zonen-Regeln, Suggest-then-Confirm)
- 6 etablierte Workflows (Mix-Inventur, Pre-Export-Audit, Mix-Report, Bus-Chain-Apply, Frequenz-Konflikt-Check, Reference-Vergleich)
- Tool-Mapping (welcher MCP-Tool für welchen Workflow)
- Error-Handling-Patterns
- Eskalations-Pfade

## Was es NICHT ist

- **Kein eigener Server-Prozess** — die Tool-Logik lebt im MCP-Server `ki-studio-mackie` (`runtime/mcp/server.py`)
- **Kein Code** — `scripts/` ist absichtlich leer, weil Nicker keine eigenen Skripte braucht
- **Kein YMP-Inhalt** — die echte Wissensbasis lebt im YMP-Repo, `references/ymp_doc_map.md` ist nur die Navigations-Hilfe

## Aktivierung

### In dieser Claude-Code-Session

Skills im Repo unter `skills/<name>/SKILL.md` werden von Claude Code **nicht automatisch** gefunden — die Anthropic-Konvention erwartet sie unter `~/.claude/skills/`.

Optionen:

```bash
# Option 1: Copy (einfach, aber muss bei Updates wiederholt werden)
cp -R skills/ki-studio-nicker ~/.claude/skills/

# Option 2: Symlink (Repo bleibt source-of-truth)
ln -s "$PWD/skills/ki-studio-nicker" ~/.claude/skills/ki-studio-nicker

# Option 3 (Windows PowerShell): Junction
New-Item -ItemType Junction -Path "$env:USERPROFILE\.claude\skills\ki-studio-nicker" -Target "$PWD\skills\ki-studio-nicker"
```

### Distribution via npx (sobald Repo public)

```bash
npx skills add git@github.com:yokadeeds-dev/ki-studio-mackie.git
```

## Trigger-Verhalten

Claude Code lädt SKILL.md auf Match von Trigger-Keywords aus dem `description:`-YAML-Feld. Beispiele die diesen Skill aktivieren:

- "Was läuft gerade in Cubase?"
- "Ist der Mix export-ready?"
- "Setup mastering chain für trip-hop"
- "Mach den Bass-Bus präsenter"
- "Welche Frequenzen kollidieren zwischen Drums und Bass?"
- "Wie ist mein Mix gegen [reference-track]?"
- "Analysiere die WAV in [pfad]"

## Pilot-Status (2026-05-21)

| Aspekt | Status |
|---|---|
| SKILL.md mit Persona-Direktiven + 6 Workflows | ✅ erstellt |
| Tool-Mapping zu MCP-Server | ✅ vollständig |
| YMP-Doc-Map | ✅ in references/ |
| YMP-Volltext-Integration | ⬜ wartet auf YMP-Wissensbasis-Migration |
| Pilot-Live-Test mit Yoka | ⬜ TODO — nach Activation |
| Suggest-then-Confirm-Tool-Schema-Erweiterung | ⬜ Task #16, separat |
| Plugin-Registry-DB-Lookup | ⬜ Task #15, separat |

## Cross-Reference

- [`SKILL.md`](SKILL.md) — der Skill selbst
- [`references/ymp_doc_map.md`](references/ymp_doc_map.md) — YMP-Wissens-Navigation
- [`../../specs/adr_2026_05_21_mureka_lessons.md`](../../specs/adr_2026_05_21_mureka_lessons.md) — ADR die Skill-Pattern eingeführt hat
- [`../../specs/persona_nicker_voice.md`](../../specs/persona_nicker_voice.md) — Original-Voice-Skelett (Quelle für SKILL.md)
- [`../../runtime/mcp/server.py`](../../runtime/mcp/server.py) — MCP-Server mit allen `nicker_*`-Tools
