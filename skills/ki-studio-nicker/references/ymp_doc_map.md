# YMP-Doc-Map — Nicker-Wissensbasis-Index

**Zweck:** Schnelles Lookup welche YMP-Doc-ID für welches Thema relevant ist. Nicker konsultiert hier zuerst, bevor er via `nicker_search_studium(query)` oder `nicker_get_studium_doc(doc_id)` gezielt zugreift.

**Stand:** 2026-05-21 (Snapshot, Volltext lebt in [YMP-Repo](https://github.com/yokadeeds-dev/YMP))

---

## Themen-Cluster

### Foundation (Theoretischer Hintergrund)

| Doc | Thema | Use für Nicker |
|---|---|---|
| 0  | Musteranalyse Universalprinzip | Tiefere Begründungen bei "Warum klingt das so?" |
| 9  | Ritual / Trance / Systeme | Genre-Kontext bei Psy-/Trance-/Ritual-Music |
| 10 | Mathematik der Musik | Intervall-/Akkord-Theorie bei Komposition |
| 11 | Physik des Schalls | Akustik-Fragen, Raum-Verhalten |
| 12 | Neurologie / Bewusstsein | Wahrnehmungs-Limits (Ear-Brain) |
| 13 | Geometrie / Fraktale / Cymatics | Visualisierungs- + Klang-Strukturen |
| 14 | Informationstheorie Musik | Komplexitäts-/Entropie-Fragen |
| 15 | Chaos / Komplexität | Non-Linear-Behaviour, Mix-Stability |
| 16 | Linguistik / Phonetik / Mantra | Vocal-Phonetik, Sprach-Klang |
| 17 | Physiologie / Biofeedback | Performer-Reaktionen, Live-Kontext |
| 18 | Psychoakustik / Binaural | Stereo-Width, 3D-Sound, Frequenz-Wahrnehmung |

### DAW-Werkzeuge

| Doc | Thema | Use für Nicker |
|---|---|---|
| 19 | Eventide Effects Studio | Eventide-Plugin-Wahl (H910, Blackhole, etc.) |
| 20 | MIDI Programming Tools | MIDI-CC-Mapping, Controller-Frage |
| 22 | VST Instrumente | Synth-/Sampler-Auswahl |
| 23 | VST Effekte | Plugin-Inventar-Lookup |
| 24 | Sampling / Sound Design | Sample-basierte Workflows |
| 25 | Sonifikation / Semantik | Wenn User über "Bedeutung" klingt |
| 26 | Live Performance Effekte | Live-FX bei Performance-Kontext |
| 28 | Der Dritte Raum DeepDive | Wide-Stereo / Räumlichkeit |

### Produktions-Handwerk (KERN für Nicker)

| Doc | Thema | Use für Nicker | Priorität |
|---|---|---|---|
| **21** | **Mastering / Finalizing** | LUFS-Targets, Limiter, Streaming-Platforms | ⭐⭐⭐ (Sprint A live) |
| 27 | Ott Production DeepDive | Multiband-Comp, Spectrum-Balance | ⭐⭐ |
| 29 | Vocal Recording / Processing | Vocal-Chain, Pre-Mix-RX-Workflow | ⭐⭐ |
| **30** | **Mixing Fundamentals** | Pegel-Konventionen, Headroom | ⭐⭐⭐ |
| 31 | Studio Hardware / Equipment | Hardware-Empfehlungen | ⭐ |
| 32 | Recording Techniques | Aufnahme-Setup, Mic-Wahl | ⭐ |
| 33 | Arrangement / Composition | Song-Struktur, Section-Aufbau | ⭐⭐ |
| **34** | **Kick / Bass Mastery** | Sub-Bass-Frequenzen, Kick-Bass-Trennung | ⭐⭐⭐ |
| **35** | **EQ / Frequency Management** | EQ-Strategien pro Track-Rolle | ⭐⭐⭐ (Sprint B Quelle) |
| **36** | **Compression / Dynamics** | Comp-Settings pro Use-Case | ⭐⭐⭐ |

### Specs (Architektur-Referenzen, kein Mix-Wissen)

| Doc | Thema |
|---|---|
| `specs/ymp_core_spec.md` | Mackie-Protokoll-Vision |
| `specs/persona_nicker_detail_spec.md` | Persona-Spec v0.2 (Tonfall, Zonen, Workflows) |

---

## Lookup-Patterns für Nicker

### Mastering-Frage
→ erst Doc 21 (Mastering/Finalizing), dann ggf. Doc 30 (Mixing-Fundamentals) für Headroom-Kontext.

### EQ-Frage pro Track-Rolle
→ erst Doc 35 (EQ-Management), dann Doc 34 (für Bass-Tracks) oder Doc 29 (für Vocals).

### Comp-Frage
→ erst Doc 36 (Compression-Dynamics), dann Doc 30 (für allgemeine Mix-Headroom).

### Sub-Bass-Konflikt
→ Doc 34 (Kick/Bass-Mastery) + Doc 18 (Psychoakustik-Sub-Wahrnehmung).

### "Warum klingt der Mix so dicht?"
→ Doc 14 (Informationstheorie), Doc 35 (EQ-Management — Masking), Doc 27 (Ott DeepDive für Multiband-Lösungen).

### Vocal-Chain-Frage
→ Doc 29 (Vocal-Processing) + Doc 16 (Phonetik für Sprach-Klang).

### Genre-spezifische Konventionen
→ erst Doc 33 (Arrangement) für Struktur, dann Doc 9 (Ritual/Trance) oder Doc 27 (Ott für Psy-Genre).

### Reference-Track-Vergleich
→ Doc 33 (Arrangement) + Doc 27/28 für Genre-Tiefe.

---

## Aktuell strukturiert geladen (Sprint A)

| Datei | Quelle | Verfügbarkeit |
|---|---|---|
| `runtime/persona/knowledge/mastering_chains.json` | Doc 21 | ✅ live, Sprint A |
| `runtime/persona/knowledge/freq_advice.json` | Doc 35, 34, 36 | 🟡 Sprint B (geplant) |
| Reference-Track-DB | Doc 27, 28 + Spotify-MCP | ⬜ Sprint C+ |
| Studium-Volltext-Index | alle Studium-Docs | ⬜ Phase 2 (RAG via mem0 oder ChromaDB) |

---

## Hinweis zu MCP-Tools

Diese Doc-Map ist nur die **Navigations-Hilfe**. Konkrete YMP-Inhalts-Abfrage immer via:

- `nicker_list_studium_docs()` — Übersicht über verfügbare Docs
- `nicker_search_studium(query)` — Volltext-Suche
- `nicker_get_studium_doc(doc_id, include_body=true)` — Volltext einer Doc

Bei großen Docs `include_body=false` zuerst für Outline, dann gezielt.
