"""
Persona-Reports — Renderer für Session-Logs zu menschen-lesbaren Markdown-Berichten.

Erste Etappe-8-Vorarbeit. Die hier gerenderten Reports sind die Form, in der
Persona Nicker später Mix-Reports + Pre-Export-Checks ausgibt.

Pure Funcs, kein State, kein I/O — nimmt das `session_summary()`-Dict aus dem
StateMirror und formatiert es als Markdown.
"""

from __future__ import annotations

from typing import Any


# Mode-Beschreibungen in Klartext-Deutsch
_MODE_LABELS: dict[str, str] = {
    "track": "Track-Mode (Track-Namen + Volumes)",
    "send": "Send-Mode (Send-Levels)",
    "pan": "Pan-Mode (Stereo-Pan + Width)",
    "plugin": "Plugin-Mode (Insert-Plugin-Editing)",
    "eq": "EQ-Mode (Channel-EQ-Bänder)",
    "instrument": "Instrument-Mode (VSTi-Parameter)",
}


def _bullet_history(history: list[Any], max_items: int = 10) -> str:
    """Rendert eine Verlaufsliste als Bullet-Pfeile, gekürzt wenn zu lang."""
    if not history:
        return "—"
    if len(history) <= max_items:
        return " → ".join(str(x) for x in history)
    head = " → ".join(str(x) for x in history[:max_items])
    return f"{head} → … ({len(history) - max_items} weitere)"


def render_session_report(summary: dict[str, Any], daw: str = "cubase") -> str:
    """
    Rendert das `session_summary()`-Dict als Markdown-Report.

    Erwartetes Eingabe-Schema:
    {
      "active": bool,
      "events": int,
      "first_ts": str | None,
      "last_ts": str | None,
      "counts": { kind: int },
      "select_history": [int, ...],
      "mode_history": [str, ...],
      "transport_history": [str, ...]
    }
    """
    if not summary or summary.get("events", 0) == 0:
        if summary and summary.get("active"):
            return f"# Session-Report ({daw.upper()})\n\nLog ist aktiv, aber noch keine Events erfasst."
        return f"# Session-Report ({daw.upper()})\n\nKein Log aktiv. Erst `start_session_log` aufrufen."

    counts = summary.get("counts", {})
    events_total = summary.get("events", 0)
    first_ts = summary.get("first_ts", "?")
    last_ts = summary.get("last_ts", "?")

    # Header
    lines: list[str] = [
        f"# Session-Report ({daw.upper()})",
        "",
        f"**Zeitraum:** {first_ts} bis {last_ts}",
        f"**Gesamt-Events:** {events_total}",
        "",
    ]

    # Counts pro Event-Typ, sortiert nach Häufigkeit
    if counts:
        lines.append("## Aktivitäts-Übersicht")
        lines.append("")
        sorted_counts = sorted(counts.items(), key=lambda x: -x[1])
        for kind, count in sorted_counts:
            label = _kind_label(kind)
            lines.append(f"- **{label}:** {count}×")
        lines.append("")

    # Track-Selection-Verlauf
    select_history = summary.get("select_history", [])
    if select_history:
        unique_tracks = sorted(set(select_history))
        most_visited = max(set(select_history), key=select_history.count)
        most_visited_count = select_history.count(most_visited)
        lines.append("## Track-Wechsel")
        lines.append("")
        lines.append(f"- {len(select_history)} Track-Wechsel insgesamt, davon {len(unique_tracks)} verschiedene Tracks")
        lines.append(f"- Track {most_visited} am häufigsten aktiv ({most_visited_count}×)")
        lines.append(f"- Verlauf: {_bullet_history(select_history, 15)}")
        lines.append("")

    # Mode-Wechsel
    mode_history = summary.get("mode_history", [])
    if mode_history:
        lines.append("## Mode-Wechsel")
        lines.append("")
        lines.append(f"- {len(mode_history)} Mode-Wechsel")
        for mode in sorted(set(mode_history)):
            count = mode_history.count(mode)
            label = _MODE_LABELS.get(mode, mode)
            lines.append(f"  - **{mode}** ({label}): {count}×")
        lines.append(f"- Verlauf: {_bullet_history(mode_history)}")
        lines.append("")

    # Transport-Wechsel
    transport_history = summary.get("transport_history", [])
    if transport_history:
        plays = transport_history.count("play")
        stops = transport_history.count("stop")
        records = transport_history.count("record")
        lines.append("## Transport")
        lines.append("")
        if plays:
            lines.append(f"- Play: {plays}×")
        if stops:
            lines.append(f"- Stop: {stops}×")
        if records:
            lines.append(f"- Record: {records}×")
        lines.append(f"- Verlauf: {_bullet_history(transport_history)}")
        lines.append("")

    # Mute / Solo / Rec-Arm
    mute_count = counts.get("mute", 0)
    solo_count = counts.get("solo", 0)
    rec_arm_count = counts.get("rec_arm", 0)
    if any((mute_count, solo_count, rec_arm_count)):
        lines.append("## Track-State-Änderungen")
        lines.append("")
        if mute_count:
            lines.append(f"- Mute-Toggles: {mute_count}×")
        if solo_count:
            lines.append(f"- Solo-Toggles: {solo_count}×")
        if rec_arm_count:
            lines.append(f"- Rec-Arm-Toggles: {rec_arm_count}×")
        lines.append("")

    # Fader-Aktivität
    fader_count = counts.get("fader", 0)
    if fader_count:
        lines.append("## Fader-Aktivität")
        lines.append("")
        lines.append(f"- {fader_count} Fader-Bewegungen erfasst (throttled auf 250 ms pro Kanal)")
        lines.append("")

    # Persona-Voice-Anhang
    lines.append("---")
    lines.append("")
    lines.append(_voice_summary(summary, daw))

    return "\n".join(lines)


def _kind_label(kind: str) -> str:
    return {
        "select": "Track-Wechsel",
        "mute": "Mute-Toggles",
        "solo": "Solo-Toggles",
        "rec_arm": "Rec-Arm-Toggles",
        "transport_change": "Transport-Wechsel",
        "mode_change": "Mode-Wechsel",
        "fader": "Fader-Bewegungen",
    }.get(kind, kind)


def _voice_summary(summary: dict[str, Any], daw: str) -> str:
    """
    Persona-Voice-Stil — kurze narrative Zusammenfassung als Vorlage für Nicker.
    Aktuell rein algorithmisch, später durch echte Persona angereichert.
    """
    events = summary.get("events", 0)
    counts = summary.get("counts", {})
    select_history = summary.get("select_history", [])
    mode_history = summary.get("mode_history", [])
    transport_history = summary.get("transport_history", [])

    parts: list[str] = []

    if events > 50:
        parts.append("Aktive Session.")
    elif events > 10:
        parts.append("Mittlere Aktivität.")
    else:
        parts.append("Wenig Aktivität.")

    if select_history:
        unique = len(set(select_history))
        if unique > 5:
            parts.append(f"Viel hin-und-her zwischen {unique} Tracks — vielleicht Übersicht verloren?")
        elif unique <= 2:
            parts.append(f"Fokus auf nur {unique} Track{'s' if unique > 1 else ''} — tiefes Arbeiten.")

    if "plugin" in mode_history:
        parts.append("Plugin-Editing war Teil der Session.")

    if transport_history.count("play") > 5:
        parts.append("Häufiges Probehören — Mixing-Phase.")
    elif transport_history.count("record") > 0:
        parts.append("Aufnahme-Aktivität in der Session.")

    if counts.get("mute", 0) > 5 or counts.get("solo", 0) > 5:
        parts.append("Viel Mute/Solo-Toggling — A/B-Vergleiche?")

    if not parts:
        parts.append("Stabile Session ohne Auffälligkeiten.")

    return "**Quick Take:** " + " ".join(parts)
