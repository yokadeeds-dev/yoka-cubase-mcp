"""
State-Mirror — In-Memory-Quelle der Wahrheit für DAW-Zustand.

Thread-safe (eine Lock pro Instanz). `apply_event(event)` mutiert den State,
`snapshot()` liefert einen konsistenten Deep-Copy mit `freshness_ms`.
"""

from __future__ import annotations

import copy
import json
import threading
import time
from pathlib import Path
from typing import Any

import re

from runtime.mackie.parser import lcd_text_to_channel_strips
from runtime.mackie.units import value14_to_db


# Regex für Page-Indikator in Plugin/Send/EQ-Modes:
# Cubase pusht "Page :XX/YY" oder "Page:XX/YY" am Ende von row2.
# [\s:]* statt \s*:?\s*: eine einzelne Character-Klasse vermeidet die zwei
# ueberlappenden \s*-Quantoren (polynomiales Backtracking / ReDoS, SonarQube).
_PAGE_PATTERN = re.compile(r"Page[\s:]*(\d{1,3})\s*/\s*(\d{1,3})")


def _smart_split_plugin_and_track(row2: str) -> tuple[str, str]:
    """
    Splittet row2 (Edit-Page) in Plugin-Name und Track-Name.

    Standard-Layout (Cubase 15, kurze Plugin-Namen ≤ 14 Char):
        row2[0:14]  = Plugin-Name (Strips 0+1)
        row2[14:35] = Track-Name (Strips 2-4)

    Long-Plugin-Quirk: Plugin-Namen > 14 Zeichen überlaufen in Strip 2.
    Beispiel "DirectivityShaper" (17 Char) wird auf 16 Char getrimmt und
    geht ohne Trenner direkt in den Track-Namen über:
        row2[0:14]  = "DirectivitySha"
        row2[14:21] = "peDUNE "         ← hier "pe" gehört noch zum Plugin

    Heuristik: erkenne Overflow daran, dass row2[13] und row2[14] non-space
    sind und row2[14] lowercase ist (typisches Plugin-Name-Tail wie "pe",
    "er", "tor"). Suche im Strip-2-Bereich (chars 14..20) den ersten
    Großbuchstaben oder Whitespace — das ist die Boundary.

    Liefert (plugin_name, track_name), beide getrimmt.
    """
    default_plugin = row2[0:14].rstrip()
    default_track = row2[14:35].strip()

    if len(row2) <= 14 or row2[13] == " ":
        return default_plugin, default_track

    # row2[13] ist non-space → Plugin-Name geht ans Ende von Strip 1.
    # Wenn Strip 2 mit Großbuchstaben oder Space anfängt, ist die Boundary klar.
    if row2[14] == " " or row2[14].isupper():
        return default_plugin, default_track

    # row2[14] ist lowercase → Plugin-Name überflutet Strip 2.
    # Suche Boundary in 14..20: erster Großbuchstabe oder Space.
    for i in range(14, min(21, len(row2))):
        c = row2[i]
        if c.isupper() or c == " ":
            return row2[0:i].rstrip(), row2[i:35].strip()

    # Kein klarer Boundary gefunden — fallback.
    return default_plugin, default_track


def _extract_plugin_info(row1: str, row2: str, mode: str | None) -> dict[str, Any] | None:
    """
    Extrahiert das active_plugin-Schema aus dem rohen LCD-Inhalt.
    Beobachtet auf Cubase 15:
      - row1 auf Edit-Pages: 8 × 7-Zeichen Parameter-Namen
      - row1 auf Übersichts-Page 1: Insert-Slot + Pre/Post + Plugin-Name (spans)
      - row2 immer: PluginName (Strips 0-1) | TrackName (Strips 2-4) | Page-Indikator (Strips 6-7)

    Long-Plugin-Names werden via _smart_split_plugin_and_track aufgesplittet,
    damit ein Plugin wie "DirectivityShaper" nicht als "DirectivitySha" mit
    "peDUNE..." als Track-Name geparst wird.

    Liefert None wenn der Mode nicht plugin ist oder keine Page-Info zu finden ist.
    """
    if mode != "plugin":
        return None
    # Page-Indikator ist verlässlicher Marker für aktiven Plugin-Mode
    m = _PAGE_PATTERN.search(row2)
    if not m:
        return None
    page = int(m.group(1))
    page_count = int(m.group(2))

    # Plugin-Name + Track-Name:
    if page > 1:
        plugin_name, track_name = _smart_split_plugin_and_track(row2)
        if not plugin_name:
            plugin_name = row1[14:35].strip()
    else:
        # Übersichts-Page: Plugin-Name in row1 Strip 2-4, "Inserts"-Label in row2 Strip 0
        plugin_name = row1[14:35].strip() or row2[0:14].strip()
        track_name = row2[14:35].strip()

    # Encoders: nur auf Edit-Pages (Page > 1) hat row1 strukturierte Parameter-Namen.
    # Auf Page 1 sind die Strips eine Übersicht (IFX-Slot, Plugin-Name-Spans).
    encoders: list[dict[str, Any]] = []
    if page > 1:
        strips = lcd_text_to_channel_strips(row1)
        for i, name in enumerate(strips):
            encoders.append({
                "encoder_index": i,
                "name": name,
                "value_str": None,  # wird vom StateMirror-Post-Processing befüllt
            })

    return {
        "plugin_name": plugin_name,
        "track_name": track_name,
        "page": page,
        "page_count": page_count,
        "encoders": encoders,
        "is_overview_page": page == 1,
    }


# Mode-Awareness — welche LCD-Reihe enthält die Track-Namen je nach Cubase-Mode?
# Beobachtung am echten Cubase 15:
#   - Track-Mode (default):    row1 = Track-Namen, row2 = Volumes/Werte
#   - Pan/Send/EQ/Plugin/Inst: row1 = Mode-Labels (z. B. "Pan", "Left-", "Right"),
#                              row2 = Track-Namen oder Parameter-Namen
# Annahme bis Mode-Button signalisiert: "track" (Cubase-Default).
_MODE_USES_ROW1_FOR_NAMES = {"track", None}  # None = Mode unbekannt → Track-Mode-Default


def _resolve_track_name(track: dict, mode: str | None) -> str:
    """
    Liefert den effektiven Track-Namen je nach Cubase-Mode.
    - Track-Mode / unbekannt: row1 (mit Fallback auf row2 falls leer)
    - Encoder-Modes (Pan, Send, EQ, Plugin, Instrument): row2 — KEIN Fallback,
      weil row1 = Mode-Label ist und keinen Track-Namen enthält. Leer = leer.
    """
    if mode in _MODE_USES_ROW1_FOR_NAMES:
        return track["name"] or track["name_lower_lcd"]
    return track["name_lower_lcd"]


def _now_iso() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime()) + time.strftime("%z")


def _empty_state(daw: str = "cubase") -> dict[str, Any]:
    return {
        "daw": daw,
        "transport": {
            "state": "stop",
            "position_bars": None,
            "position_smpte": None,
            "tempo": None,
            "loop_active": False,
        },
        "active_track": None,
        "tracks": [
            {
                "index": i + 1,
                "name": "",
                "name_lower_lcd": "",
                "selected": False,
                "mute": False,
                "solo": False,
                "rec_arm": False,
                "volume_db": None,
                "vu": 0,
            }
            for i in range(8)
        ],
        "mode": "track",  # Default-Annahme: Cubase startet im Track-Mode
        "two_char_display": None,
    }


class StateMirror:
    SESSION_LOG_MAX = 5000  # Ring-Buffer-Limit, um Memory zu beschränken

    # Plugin-Mode-Encoder-Werte: TTL für transient pushed values auf row1.
    # Cubase pusht beim Encoder-Drehen den Wert (z. B. "12.5 dB") in den
    # Strip-Slot, ersetzt temporär den Param-Namen. Nach ~2 s ohne weitere
    # Updates kommt der Param-Name zurück. Wir geben pushed values ~2 s im
    # Snapshot aus, danach verwerfen.
    PLUGIN_VALUE_STR_TTL_S = 2.0

    def __init__(self, daw: str = "cubase") -> None:
        self._lock = threading.Lock()
        self._state = _empty_state(daw)
        self._last_update_monotonic = time.monotonic()
        # 56-Zeichen-Buffer pro LCD-Reihe. Cubase patcht das Display partiell;
        # wir halten beide Reihen vollständig vor und re-derivieren Track-Strips
        # bei jedem Update. Initial mit Spaces gefüllt.
        self._lcd_row1 = [" "] * 56
        self._lcd_row2 = [" "] * 56
        # Timecode-Display: 10 7-Segment-Stellen, CC 64..73. Index 0 = rechte
        # Stelle (LSB der Frames), Index 9 = linke Stelle. Beim Lesen
        # umkehren, um die menschliche Reihenfolge zu bekommen.
        self._timecode_digits = [" "] * 10
        # VU-Decay: Mackie liefert nur Pegel-Updates ohne automatischen Abfall.
        # Wir simulieren in Software: jeder VU-Wert verfällt linear gegen 0,
        # ein Schritt alle DECAY_INTERVAL_MS. Damit wirken Pegel-Anzeigen wie
        # echte Meter (typische Studio-Decay ~300ms/Stufe).
        self._vu_last_update_monotonic = [time.monotonic()] * 8
        # Session-Log: Liste signifikanter Events mit Timestamp.
        # Aktiviert via start_session_log(); ausgelesen via session_summary().
        self._session_log: list[dict[str, Any]] | None = None
        # Plugin-Mode Baselines: erste gesehene row1-Strip-Werte pro
        # (plugin_name, page) — das sind die Param-Namen. Werden beim ersten
        # LCD-Update für die jeweilige Page gefüllt, später gegen aktuelle
        # Strips diff'ed um transient pushed values zu erkennen.
        self._plugin_baselines: dict[tuple[str, int], list[str]] = {}
        # Transient Encoder-Werte: encoder_index -> (value_str, monotonic_ts).
        # Wird in _track_plugin_state gesetzt wenn ein Strip vom Baseline-Namen
        # abweicht. Im snapshot innerhalb TTL als value_str ausgegeben.
        self._plugin_value_strs: dict[int, tuple[str, float]] = {}

    VU_DECAY_INTERVAL_MS = 100  # 100ms pro Stufe → volles Decay (12→0) in ~1.2s

    # ---------- Mutation ----------

    def apply_event(self, event: dict[str, Any]) -> None:
        kind = event.get("kind")
        with self._lock:
            if kind == "lcd":
                self._apply_lcd(event["offset"], event["text"])
            elif kind == "select":
                self._apply_select(event["channel"], event["pressed"])
                if event["pressed"]:
                    self._session_log_event("select", {"channel": event["channel"]})
            elif kind == "mute":
                if event["pressed"]:
                    self._state["tracks"][event["channel"]]["mute"] = not self._state["tracks"][event["channel"]]["mute"]
                    self._session_log_event("mute", {"channel": event["channel"], "now": self._state["tracks"][event["channel"]]["mute"]})
            elif kind == "solo":
                if event["pressed"]:
                    self._state["tracks"][event["channel"]]["solo"] = not self._state["tracks"][event["channel"]]["solo"]
                    self._session_log_event("solo", {"channel": event["channel"], "now": self._state["tracks"][event["channel"]]["solo"]})
            elif kind == "rec_arm":
                if event["pressed"]:
                    self._state["tracks"][event["channel"]]["rec_arm"] = not self._state["tracks"][event["channel"]]["rec_arm"]
                    self._session_log_event("rec_arm", {"channel": event["channel"], "now": self._state["tracks"][event["channel"]]["rec_arm"]})
            elif kind == "fader":
                ch = event["channel"]
                if 0 <= ch < 8:
                    self._state["tracks"][ch]["volume_db"] = self._fader_to_db(event["value14"])
                    # Fader-Events nur bei "Loslassen-Punkt" loggen wäre besser, aber wir
                    # haben hier nur kontinuierliche Werte. Loggen mit Throttling: nur jeden
                    # 250ms eine Meldung pro Kanal.
                    self._maybe_log_fader(ch, event["value14"])
            elif kind == "vu":
                ch = event["channel"]
                if 0 <= ch < 8:
                    self._state["tracks"][ch]["vu"] = event["level"]
                    self._vu_last_update_monotonic[ch] = time.monotonic()
            elif kind == "transport_button" and event["pressed"]:
                action_map = {"play": "play", "stop": "stop", "record": "record"}
                if event["action"] in action_map:
                    self._state["transport"]["state"] = action_map[event["action"]]
                    self._session_log_event("transport_change", {"state": action_map[event["action"]]})
            elif kind == "two_char_display":
                self._state["two_char_display"] = event["text"]
            elif kind == "mode_button" and event["pressed"]:
                old_mode = self._state["mode"]
                self._state["mode"] = event["mode"]
                if old_mode != event["mode"]:
                    self._session_log_event("mode_change", {"from": old_mode, "mode": event["mode"]})
            elif kind == "timecode_digit":
                self._apply_timecode_digit(event["digit_index"], event["ascii"])
            self._last_update_monotonic = time.monotonic()

    def _maybe_log_fader(self, channel: int, value14: int) -> None:
        """Throttled Fader-Logging — nur jeden 250ms pro Kanal eine Meldung."""
        if self._session_log is None:
            return
        now = time.monotonic()
        last_attr = f"_last_fader_log_{channel}"
        last = getattr(self, last_attr, 0.0)
        if now - last >= 0.25:
            setattr(self, last_attr, now)
            self._session_log_event("fader", {"channel": channel, "value14": value14})

    def _apply_timecode_digit(self, digit_index: int, ascii_val: int) -> None:
        if not (0 <= digit_index < 10):
            return
        # Mackie-Timecode-Bytes: Bits 0..6 = ASCII-Code, Bit 7 = Punkt rechts.
        # Bit 7 strippen wir hier — den Punkt-Marker können wir später
        # separat behandeln, wenn wir ihn wirklich brauchen.
        ch = chr(ascii_val & 0x7F) if 0x20 <= (ascii_val & 0x7F) <= 0x7E else " "
        self._timecode_digits[digit_index] = ch
        # Reihenfolge umkehren (links→rechts statt rechts→links).
        raw = "".join(reversed(self._timecode_digits))
        self._state["transport"]["position_smpte"] = raw.rstrip()

    def _apply_lcd(self, offset: int, text: str) -> None:
        # Reihe 1: Offset 0..55 = Track-Namen. Reihe 2: Offset 56..111 = Werte.
        # Cubase sendet sowohl volle 56-Char-Updates als auch partielle (z. B.
        # 7 Zeichen ab Offset 7 für Track 2). Wir patchen den Reihen-Buffer
        # zeichenweise und re-deriven die Track-Strips danach.
        for i, ch in enumerate(text):
            pos = offset + i
            if 0 <= pos < 56:
                self._lcd_row1[pos] = ch
            elif 56 <= pos < 112:
                self._lcd_row2[pos - 56] = ch
            else:
                break  # über das Display hinaus, ignorieren

        row1_str = "".join(self._lcd_row1)
        row2_str = "".join(self._lcd_row2)
        for i, name in enumerate(lcd_text_to_channel_strips(row1_str)):
            self._state["tracks"][i]["name"] = name
        for i, val in enumerate(lcd_text_to_channel_strips(row2_str)):
            self._state["tracks"][i]["name_lower_lcd"] = val

        # Falls aktive Spur bekannt ist, ihren Namen synchron halten.
        active = self._state.get("active_track")
        if active is not None:
            idx = active["index"] - 1
            if 0 <= idx < 8:
                active["name"] = self._state["tracks"][idx]["name"]

        # Phase 2 active_plugin: Baselines + transient encoder values pflegen.
        # Muss innerhalb der Lock laufen → wird hier gleich nach dem Buffer-Update
        # mit aufgerufen.
        self._track_plugin_state(row1_str, row2_str)

    def _track_plugin_state(self, row1: str, row2: str) -> None:
        """
        Pflegt Plugin-Mode-Baselines + transient Encoder-Werte.

        Beim ERSTEN Sichten einer (plugin_name, page)-Kombi werden die
        aktuellen row1-Strips als Baseline (= Param-Namen) gespeichert.
        Bei späteren LCD-Updates werden Strips, die vom Baseline-Namen
        abweichen, als transient pushed value mit Zeitstempel registriert.
        Strips, die wieder mit dem Baseline-Namen übereinstimmen, löschen
        den value-Cache.

        Annahme: bei der allerersten Sichtung dreht der User keinen Encoder,
        sodass row1 die "ruhigen" Param-Namen zeigt. Wenn doch, wird die
        Baseline ggf. mit einem Wert kontaminiert — Cubase korrigiert das
        nach ~2 s, und das nächste Diff dreht Name/Wert wieder gerade.
        """
        mode = self._state["mode"]
        if mode != "plugin":
            return
        m = _PAGE_PATTERN.search(row2)
        if not m:
            return
        page = int(m.group(1))
        if page <= 1:
            # Overview-Page hat keine Param-Strips
            return

        plugin_name, _ = _smart_split_plugin_and_track(row2)
        if not plugin_name:
            return

        key = (plugin_name, page)
        strips = lcd_text_to_channel_strips(row1)

        if key not in self._plugin_baselines:
            # Erste Sichtung dieser Page → Baseline einfangen.
            self._plugin_baselines[key] = list(strips)
            return

        baseline = self._plugin_baselines[key]
        # Self-Healing: wenn die aktuelle row1 STRIKT MEHR gefüllte Strips hat
        # als die bestehende Baseline, war die Baseline mit Stale-Content
        # kontaminiert (z. B. wenn Cubase row2-Page-Indikator vor row1-Param-
        # Namen pushed → erste Sichtung captured noch das alte Page-Layout).
        # Bei einem typischen Encoder-Push wird ein gefüllter Strip durch
        # einen anderen gefüllten Strip ersetzt, also bleibt Anzahl konstant.
        # Nur wenn echte Param-Namen die leeren Strips füllen, ersetzen wir.
        non_empty_now = sum(1 for s in strips if s)
        non_empty_base = sum(1 for s in baseline if s)
        if non_empty_now > non_empty_base:
            self._plugin_baselines[key] = list(strips)
            # Cache leeren — alte Werte gehörten zur falschen Baseline
            self._plugin_value_strs.clear()
            return

        now = time.monotonic()
        for i, strip in enumerate(strips):
            if i >= len(baseline):
                break
            base = baseline[i]
            if strip == base:
                # Strip = Baseline → kein transient value mehr aktiv
                self._plugin_value_strs.pop(i, None)
            elif strip:
                # Strip differs and non-empty → transient pushed value
                self._plugin_value_strs[i] = (strip, now)
            # Wenn strip leer ist, behandeln wir's neutral (kein Update am Cache)

    def _apply_baselines_and_values(self, plugin_info: dict[str, Any]) -> None:
        """
        Read-only-Post-Processing: ersetzt encoder["name"] durch den Baseline-
        Param-Namen und füllt encoder["value_str"] mit dem aktuell gepushten
        Wert (oder cached Wert innerhalb TTL).

        Wird vom snapshot() aufgerufen, ohne den State zu mutieren.
        """
        if not plugin_info or plugin_info.get("is_overview_page"):
            return
        key = (plugin_info["plugin_name"], plugin_info["page"])
        baseline = self._plugin_baselines.get(key)
        if not baseline:
            return
        now = time.monotonic()
        for i, enc in enumerate(plugin_info["encoders"]):
            if i >= len(baseline):
                break
            base = baseline[i]
            current = enc["name"]
            if current and current != base:
                # Encoder-Bewegung: row1-Strip zeigt aktuell den Wert
                enc["name"] = base
                enc["value_str"] = current
            else:
                # Strip = Baseline (oder leer) → name korrekt, evtl. cached value
                enc["name"] = base
                cached = self._plugin_value_strs.get(i)
                if cached:
                    value_str, ts = cached
                    if now - ts < self.PLUGIN_VALUE_STR_TTL_S:
                        enc["value_str"] = value_str
                    else:
                        enc["value_str"] = None

    def _apply_select(self, channel: int, pressed: bool) -> None:
        if not pressed:
            return
        for t in self._state["tracks"]:
            t["selected"] = False
        self._state["tracks"][channel]["selected"] = True
        self._state["active_track"] = {
            "index": channel + 1,
            "name": self._state["tracks"][channel]["name"],
            "selected": True,
        }

    @staticmethod
    def _fader_to_db(value14: int) -> float:
        """
        Mackie-Fader nach dB. Konvertierung in runtime/mackie/units.py
        (piecewise-linear, kalibriert auf 0 dB @ value14=12286).
        """
        return value14_to_db(value14)

    # ---------- Read ----------

    def snapshot(self) -> dict[str, Any]:
        now = time.monotonic()
        with self._lock:
            snap = copy.deepcopy(self._state)
            freshness_ms = int((now - self._last_update_monotonic) * 1000)
            # VU-Decay: für jeden Track berechnen, wie viele Decay-Schritte
            # seit dem letzten echten VU-Update vergangen sind, und Pegel
            # entsprechend zurückgeben (ohne den internen Wert zu mutieren —
            # Mackie kann jederzeit ein neues Level pushen).
            for ch in range(8):
                ms_since = (now - self._vu_last_update_monotonic[ch]) * 1000
                steps = int(ms_since // self.VU_DECAY_INTERVAL_MS)
                if steps > 0:
                    decayed = max(0, snap["tracks"][ch]["vu"] - steps)
                    snap["tracks"][ch]["vu"] = decayed
            # Snapshot der LCD-Reihen unter demselben Lock — kein Race
            row1 = "".join(self._lcd_row1)
            row2 = "".join(self._lcd_row2)

        # Mode-aware: Track-Namen abhängig vom aktuellen Mode auflösen.
        mode = snap.get("mode")
        for t in snap["tracks"]:
            t["name_resolved"] = _resolve_track_name(t, mode)

        # active_plugin: nur in plugin-mode rekonstruiert. Post-Processing
        # via _apply_baselines_and_values füllt Param-Namen aus Baseline und
        # value_str aus aktuellem row1-Strip oder dem TTL-Cache.
        plugin_info = _extract_plugin_info(row1, row2, mode)
        if plugin_info:
            with self._lock:
                self._apply_baselines_and_values(plugin_info)
        snap["active_plugin"] = plugin_info

        # active_track.name aus dem Resolver — auch wenn der Listener den
        # SELECT vor dem ersten LCD-Update sieht, bekommt der Snapshot später
        # den korrekten Namen, sobald LCD reinkommt.
        active = snap.get("active_track")
        if active is not None:
            idx = active["index"] - 1
            if 0 <= idx < 8:
                active["name"] = snap["tracks"][idx]["name_resolved"]

        snap["freshness_ms"] = freshness_ms
        snap["timestamp"] = _now_iso()
        return snap

    # ---------- Session-Logging ----------

    def start_session_log(self) -> None:
        """Aktiviert oder resetet den Event-Log."""
        with self._lock:
            self._session_log = []

    def stop_session_log(self) -> None:
        """Deaktiviert den Event-Log (bisherige Einträge bleiben für Summary)."""
        # Kein Reset — nur kein weiteres Anhängen mehr
        # via Markierung: wir setzen einen Flag-Eintrag, prüfen beim Append
        with self._lock:
            if self._session_log is not None:
                self._session_log.append({
                    "kind": "session_log_stopped",
                    "ts": _now_iso(),
                })

    def _session_log_event(self, kind: str, payload: dict[str, Any] | None = None) -> None:
        """Append-only, ring-buffer mit SESSION_LOG_MAX. Erwartet Lock gehalten."""
        if self._session_log is None:
            return
        # Wenn schon stop-Marker drin, nicht mehr anhängen
        if self._session_log and self._session_log[-1].get("kind") == "session_log_stopped":
            return
        entry = {"kind": kind, "ts": _now_iso()}
        if payload:
            entry["payload"] = payload
        self._session_log.append(entry)
        # Ring-Buffer
        if len(self._session_log) > self.SESSION_LOG_MAX:
            self._session_log = self._session_log[-self.SESSION_LOG_MAX:]

    def get_session_log(self) -> list[dict[str, Any]]:
        with self._lock:
            return list(self._session_log) if self._session_log is not None else []

    def session_summary(self) -> dict[str, Any]:
        """Aggregiert den Log zu einer kompakten Übersicht: Counts, Span, Highlights."""
        with self._lock:
            log = list(self._session_log) if self._session_log is not None else []

        if not log:
            return {"active": self._session_log is not None, "events": 0, "summary": "Kein Log."}

        # Count by kind
        counts: dict[str, int] = {}
        for ev in log:
            counts[ev["kind"]] = counts.get(ev["kind"], 0) + 1

        # Track-Selections-Verlauf
        selects = [ev for ev in log if ev["kind"] == "select"]
        select_history = [ev["payload"]["channel"] + 1 for ev in selects if "payload" in ev]

        # Mode-Wechsel
        modes = [ev for ev in log if ev["kind"] == "mode_change"]
        mode_history = [ev["payload"]["mode"] for ev in modes if "payload" in ev]

        # Transport-Wechsel
        transport_changes = [ev for ev in log if ev["kind"] == "transport_change"]
        transport_history = [ev["payload"]["state"] for ev in transport_changes if "payload" in ev]

        return {
            "active": self._session_log is not None,
            "events": len(log),
            "first_ts": log[0]["ts"],
            "last_ts": log[-1]["ts"],
            "counts": counts,
            "select_history": select_history[:50],
            "mode_history": mode_history[:50],
            "transport_history": transport_history[:50],
        }

    # ---------- JSON Persistence ----------

    def write_json(self, path: Path) -> bool:
        """
        Atomic Write: erst .tmp schreiben, dann replace.
        Fault-tolerant: Windows kann das Replace verweigern, wenn ein Reader
        gerade die Zieldatei offen hat (cat/editor/anderer Prozess).
        Wir geben False zurück, der Listener läuft weiter.
        """
        snap = self.snapshot()
        tmp = path.with_suffix(path.suffix + ".tmp")
        try:
            tmp.write_text(json.dumps(snap, indent=2, ensure_ascii=False), encoding="utf-8")
            tmp.replace(path)
            return True
        except (OSError, PermissionError):
            # Beim nächsten Tick noch mal probieren.
            return False
