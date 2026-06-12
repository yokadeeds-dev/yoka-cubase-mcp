# Changelog

Alle nennenswerten Änderungen an **yoka-cubase-mcp**. Format orientiert an
[Keep a Changelog](https://keepachangelog.com/de/1.1.0/), Versionierung nach [SemVer](https://semver.org/lang/de/).

## [0.2.0] — 2026-06-11

### Hinzugefügt
- **Voller Funktionsumfang öffentlich** (64 Tools): der gesamte **Nicker**-Mixing-/Mastering-Layer — Audio-Analyse (LUFS/Spektrum/True-Peak), Mastering-Chains pro Genre × Plattform, Frequenz-/Masking-Advice, Mix-Presets, Plugin-Registry — sowie die **volle Command-Belegung** (~1559 Commands), Traktor-Deck-Observer und DAWproject-Export.
- **Ableton Live 12** über MCU **live verifiziert** (Mode-Wechsel, Track-Select, State-Mirror closed-loop).
- **Installations-Doctor:** `python -m runtime.setup.doctor` — prüft Python-Version, Dependencies, MIDI-Ports, Cubase-Port-Setup, optionale Daten und den Server-Import.
- README: **„Erster Lauf"** (minimaler reproduzierbarer Workflow, read-only/`dry_run`) + **„Sicherheit & Zonen"** (grün/gelb/rot, Fenster-Fokus, graceful degradation).
- CI: harter Server-Import-Check + Doctor-Lauf (zusätzlich zu Selftests auf Windows + macOS).

### Geändert
- **Lizenz: MIT → AGPL-3.0 + kommerzielle Lizenz** (Dual-License). Verhindert Fremd-Kommerzialisierung; kommerzielle Ausnahme auf Anfrage (yoka@provolution.org).
- **Premium-Modell aufgelöst:** kein Open-Core-Gate mehr. Sponsoring ist freiwillige Unterstützung, kein Zugangsschlüssel. Code-Terminologie bereinigt (`OPTIONAL_MODULES_AVAILABLE` statt `PREMIUM_AVAILABLE`).
- `requirements.txt`: `pywin32` (Windows-AHK, Environment-Marker) + Audio-Deps (numpy/scipy/soundfile/pyloudnorm) ergänzt.

### Hinweis zu user-spezifischen Daten
- **Plugin-Inventar** + volle **Plugin-CC-Map** entstehen aus deinem eigenen Cubase-Scan (nicht mitgeliefert). Mitgeliefert ist eine Demo-CC-Map (1 Stock-Plugin je Kategorie).
- **YMP-Wissensbasis** (Volltexte) optional via `YMP_PATH` / Sibling-Repo.

## [0.1.0] — 2026-06-11

### Hinzugefügt
- Erste öffentliche Version: MCU-Kern (Mackie closed-loop-verifiziert, State-Mirror), AHK-Hotkey-Bridge, MIDI-Send/Recording, Plugin-Parameter-Steuerung (Demo-Map). Cubase produktiv getestet (Windows). macOS als Stub.
- Lizenz: AGPL-3.0 + kommerzielle Lizenz.

[0.2.0]: https://github.com/yokadeeds-dev/yoka-cubase-mcp/releases/tag/v0.2.0
[0.1.0]: https://github.com/yokadeeds-dev/yoka-cubase-mcp/releases/tag/v0.1.0
