# User Guide — yoka-cubase-mcp

How to actually *use* the server once it's installed. For install/setup see
[`INSTALL.md`](../INSTALL.md) and [`docs/01_setup_cubase_mcu.md`](01_setup_cubase_mcu.md).

This guide covers the **64-tool** MCP server as shipped: what to say to your agent, how
to read the results, the safety model, the tool groups, and day-to-day workflows.

---

## 1. The mental model

You don't call tools yourself — you talk to an **AI agent** (Claude Code, Cursor, …) that
has the server connected, and it calls the tools for you. The server speaks the **Mackie
Control (MCU)** protocol to your DAW, so it *understands and operates* a running Cubase
(or Ableton / Traktor) session: read state, select tracks, set volume, drive transport,
page through plugins, and give mixing/mastering advice.

Two ideas make it trustworthy:

- **Closed-loop verification** — after a control action the server waits for the DAW's own
  echo and reports `verified: true/false`. It never just assumes a command landed.
- **State mirror** — `get_daw_state` returns the live picture (mode, transport, the 8
  visible channel strips with volume/mute/solo/VU) with a `freshness_ms`, no screenshot.

---

## 2. Before your first session

1. The server is registered in your agent's MCP config (see INSTALL.md).
2. loopMIDI (Windows) / IAC (macOS) ports exist: `MACKIE_FROM_CUBASE` / `MACKIE_TO_CUBASE`
   (and the Ableton pair / `AI_INPUT` if you use them).
3. Your DAW has a **Mackie Control** device pointed at those ports.

Check the whole setup at once:

```
python -m runtime.setup.doctor
```

It verifies Python, dependencies, MIDI ports, the Cubase device, and optional data, and
tells you what's missing — run it first whenever something behaves oddly.

---

## 3. A safe first run

Reproducible and read-only (nothing is changed). Cubase open, a project with ≥3 tracks,
loopMIDI ports active. Just tell your agent:

1. *"Which DAWs can you reach?"* → `list_connected_daws`
2. *"What's the state of Cubase?"* → `get_daw_state` (mode, transport, 8 strips)
3. *"Select track 3."* → `select_track` — comes back `verified: true`
4. *"Preview setting track 3 to -6 dB."* → `set_track_volume_db(..., dry_run=true)` — shows
   the planned change without writing
5. *"Play, then stop."* → `transport_play` / `transport_stop` (visible in Cubase)

Every step reports `verified: true/false`. Only step 4 *without* `dry_run` actually
writes — and that's undoable in Cubase with Ctrl+Z.

---

## 4. Talking to it — example prompts

| You say | What happens |
|---|---|
| *"What's playing in Cubase?"* | `list_connected_daws` → `get_daw_state`: active track, transport, strips, freshness |
| *"Set the lead synth to -3 dB."* | `list_tracks` to resolve the name → `set_track_volume_db` |
| *"Give me tracks 17–24."* | `bank_right` ×2 → `list_tracks` (banks move the visible 8) |
| *"Show the active plugin's parameters."* | `set_mode(plugin)` → `get_active_plugin` → `plugin_page_next` through the pages |
| *"Is everything clean before export?"* | `list_tracks` → flags stray solo / mute / rec-arm; `get_daw_state` for transport |
| *"Log my session for 20 min, then summarize."* | `start_session_log` → (listener tracks automatically) → `get_session_summary` |
| *"Make sure Cubase is in track mode."* | `force_track_mode` → may report `was_already_satisfied: true` (no action needed) |
| *"Save."* | `save_project` — focuses the Cubase window (window-guard) and sends Ctrl+S |
| *"Which mastering chain for trip-hop on Spotify?"* | `nicker_suggest_mastering_chain(genre, platform)` |

Speak in plain language and name targets by track name or number; the agent resolves them.

---

## 5. Reading the result

Every tool returns a structured envelope. The fields that matter to you:

- **`ok`** — the call succeeded as a request.
- **`verified`** — the DAW echo confirmed the change (closed-loop). `false` isn't always a
  failure — see the Cubase quirk below.
- **`was_already_satisfied`** — the target state was already true, so nothing was sent
  (idempotent). *"Cubase was already in track mode."*
- **`freshness_ms`** — how old the state snapshot is. If it's large (> ~2 s), the DAW may
  have changed since; ask again.
- **`requested` / `observed`** — what you asked for vs. what the mirror now shows.
- **`elapsed_ms`**, **`error`** — timing and, on failure, a plain reason.

---

## 6. Safety — the three zones

Every tool carries a **zone** signalling its impact:

- 🟢 **Green — read-only.** `get_daw_state`, `list_tracks`, `get_active_plugin`, all
  `nicker_*` analysis. Risk-free, call freely.
- 🟡 **Yellow — mutates DAW state, undoable.** Volume, mode, track-select, plugin CC. Undo
  in Cubase with Ctrl+Z. A good agent sets these only when the target is unambiguous.
- 🔴 **Red — destructive / explicit intent.** `transport_record` (can overwrite takes),
  `save_project`. Never fired without your clear say-so.

What to keep in mind:

- **Window focus.** The AHK hotkey bridge sends synthetic keystrokes to the *focused*
  window. A window-guard checks Cubase is in front first — if another app has focus, the
  action is **not** sent (no blind keystrokes into other apps).
- **`dry_run` first.** State/plugin-mutating tools accept `dry_run=true` to preview the
  exact change before it's written.
- **Recording.** `transport_record` can overwrite a running take — deliberately red.
- **`verified: false` on bad setup.** If loopMIDI ports or the Cubase Mackie device are
  wrong, tools report `verified: false` instead of failing silently. Run the doctor.
- **Graceful degradation.** If optional modules are missing, the server still starts and
  offers the core tools instead of crashing.
- **Known Cubase quirk.** `set_track_volume` sometimes doesn't echo back (a hardware-Mackie
  pitch-bend detail) → reported as "sent, echo missing", not an error.

---

## 7. The tools, by group (64)

Most tools take an optional `daw="cubase"|"ableton"|"traktor"` (default `cubase`).

- **State (read-only):** `get_daw_state`, `get_active_track`, `get_active_plugin`,
  `list_tracks`, `list_connected_daws`, `get_traktor_state`
- **Mackie control:** `set_mode`, `select_track`, `bank_left/right`, `channel_left/right`,
  `transport_play/stop`, `plugin_page_next/prev`, `force_track_mode`
- **Volume:** `set_track_volume`, `set_track_volume_db`
- **Commands / AHK:** `ahk_list_actions`, `ahk_send_action`, `send_cubase_command` (any of
  ~1559 Cubase commands by name), `save_project`, `undo`, `redo`
- **MIDI / plugin params:** `send_midi_note`, `send_midi_note_sequence`,
  `nicker_send_midi_cc(_pct/_range)`, `nicker_set_plugin_param` (plugin params by name),
  `nicker_set_pro_q3_band`, `nicker_set_pro_c2`, `nicker_list_midi_ports`
- **Audio analysis:** `nicker_analyze_audio_file`, `nicker_audit_audio_file`,
  `nicker_compare_audio_files`, `play_audio_file`
- **Mastering & EQ knowledge:** `nicker_suggest_mastering_chain`,
  `nicker_list_mastering_genres/platforms`, `nicker_freq_advice`,
  `nicker_find_masking_conflicts`, `nicker_suggest_track_settings`,
  `nicker_list_track_roles`, `nicker_list_freq_track_roles`
- **Plugin registry:** `nicker_lookup_plugin`, `nicker_get_plugin_details`,
  `nicker_plugin_registry_stats`, `nicker_sync_plugins_from_cubase`
- **Session log:** `start_session_log`, `get_session_summary`, `get_session_report`
- **Setup inspector:** `validate_cubase_port_setup`, `list_cubase_audio_drivers`

---

## 8. Plugin control & the mixing knowledge layer (Nicker)

**Plugin parameters by name.** `nicker_set_plugin_param` drives a plugin's parameters over
the Cubase MIDI Remote API (`makeValueBinding`) — independent of the plugin's own
MIDI-Learn. Out of the box, **all Steinberg stock plugins (91) ship as a ready CC map**
(identical parameter indices on every Cubase 15). For your **third-party** plugins, scan
your own setup once with `nicker_sync_plugins_from_cubase`. FabFilter Pro-Q3 / Pro-C2 have
granular helpers (`nicker_set_pro_q3_band`, `nicker_set_pro_c2`), both with `dry_run`.

**Advice tools** read a built-in structured knowledge base and work with no setup:
mastering-chain suggestions per genre + platform, per-role frequency advice, and
masking-conflict detection. They *advise* — they don't silently change your mix.

**Structural, not perceptual.** The audio tools analyze LUFS, spectrum and stereo
correlation. They never claim a human "sounds like" judgment — trust your ears for that.

### Plugin control — practical gotchas (learned in the studio)

These save real debugging time when you drive plugin parameters, especially your own
third-party plugins:

- **Bindings act on the *selected* track.** Select the target track first, or values land
  in whatever plugin is on the currently selected one.
- **Restart Cubase after (re)installing the MIDI Remote scripts** — or after a loopMIDI
  port was created / reconnected while Cubase was running. Classic symptom: CCs report
  `ok: true` with the right port, but nothing moves in the plugin, because Cubase is
  holding a dead binding while still showing "connected". Save your project first, then
  fully restart Cubase.
- **Scanning your plugins (`nicker_sync_plugins_from_cubase`) only fires on a *real track
  switch*.** Re-clicking the same track, clicking empty space, or opening the plugin GUI
  does nothing. Switch to another track and back; if you only have one track, add a helper
  track first. Give the scan a generous time window. A whole insert chain is captured in
  one pass (all 8 slots are read) — no need to move plugins into slot 0.
- **Waves-style plugins expose MIDI-Learn placeholder parameters** ("Control 14", "Pitch
  Bend", …) next to their real ones — only the *named* parameters are useful. A few expose
  only Bypass (e.g. Waves Tune Real-Time) and can't be driven this way; set those by hand.
- **`value_pct` is the position along the control's travel, not a musical unit.** The map
  knows parameter *names*, not units or ranges. When calibrating, hover the control in the
  plugin GUI to read its real value.
- **Instruments (VST synths) aren't reachable this way** — the MIDI Remote API exposes
  instruments only through 8 Quick Controls, not insert-style parameter bindings. Use the
  synth's own MIDI-Learn for those.

---

## 9. Day-to-day workflows

- **Mix inventory** — *"What's playing?"* → `get_daw_state` (per DAW if several connected).
- **Pre-export audit** — *"Clean before bounce?"* → `list_tracks`, flag rec-armed / stray
  solo / near-silent; add `nicker_audit_audio_file(path, genre, platform)` on a master
  bounce for a LUFS / true-peak check.
- **Track + transport control** — resolve by name/index, `select_track` / banks, set volume
  in dB (preview with `dry_run`), play/stop freely, record only on explicit confirmation.
- **Plugin inspection / tweak** — `get_active_plugin`, page through params, then
  `nicker_set_plugin_param` (or the FabFilter helpers) with `dry_run` → confirm.
- **Mastering / EQ advice** — `nicker_suggest_mastering_chain`, `nicker_freq_advice`,
  `nicker_find_masking_conflicts`.
- **Session summary** — `start_session_log` → work → `get_session_summary` /
  `get_session_report` (Markdown).
- **Large sessions** — `bank_left/right` move the visible 8 strips in blocks of 8.
- **Cross-DAW** — the same calls with `daw="ableton"` drive a second DAW in parallel.

More detailed, phase-by-phase examples: [`docs/demo_workflows.md`](demo_workflows.md).

---

## 10. Troubleshooting

| Symptom | What to do |
|---|---|
| Tools report `verified: false` / "port offline" | loopMIDI port or Cubase Mackie device wrong — run `python -m runtime.setup.doctor` |
| Server won't import after an update | Ensure `mcp` stays on 1.x (`mcp>=1.0.0,<2`); 2.x dropped an API the server uses |
| State looks stale (`freshness_ms` large) | The snapshot is old — ask again; Cubase may have changed |
| `set_track_volume` shows `verified: false` | Known Cubase quirk (pitch-bend not echoed) — the send still went through |
| A `nicker_*` tool is missing | Optional modules weren't installed; the core tools still run |
| Hotkey action (save/undo) didn't happen | Window-guard blocked it because Cubase wasn't focused — bring it to front |
| CCs report `ok: true` but the plugin doesn't move | Cubase holds a dead MIDI Remote binding (port changed since launch) — save, then fully restart Cubase |
| Plugin scan produces no output | The scan only fires on a real track switch — switch to another track and back (add a helper track if you only have one) |
| Plugin parameter sets the wrong thing | A different track is selected — bindings act on the selected track; select the target first |

---

## 11. Where to look next

- [`INSTALL.md`](../INSTALL.md) · [`docs/01_setup_cubase_mcu.md`](01_setup_cubase_mcu.md) — install & DAW wiring
- [`docs/demo_workflows.md`](demo_workflows.md) — worked examples by studio phase
- [`docs/cubase_keymap.md`](cubase_keymap.md) — command / keymap reference
- [`README.md`](../README.md) — overview, architecture, tool list, safety zones
