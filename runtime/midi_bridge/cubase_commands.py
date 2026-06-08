"""
cubase_commands.py — Resolver + Sender fuer den vollen Cubase-Command-Adressraum
ueber MIDI Remote (Port AI_CMD).

Loest einen Command-Namen -> eindeutige (channel, cc) auf (aus dem versionierten
cubase_command_midi_map.json) und feuert via send_cc.send_cc() einen CC-127-
Button-Press. Cubases MIDI-Remote-Script (ki_studio_command_remote.js) faengt
den CC ab und triggert den Host-Command.

Aufloesungs-Reihenfolge fuer command_name:
  1. exakt "Category/Command"  (immer eindeutig)
  2. eindeutiger Slug          (z.B. "transport_start")
  3. eindeutiger Command-Name  (ohne Kategorie, falls projektweit eindeutig)
Mehrdeutigkeit -> Fehler mit Kandidaten-Liste statt Raten.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from runtime.midi_bridge.send_cc import send_cc, SendResult

MAP_PATH = Path(__file__).resolve().parent / "cubase_command_midi_map.json"


@dataclass
class CommandResolution:
    ok: bool
    key: str | None = None          # "Category/Command"
    category: str | None = None
    command: str | None = None
    channel: int | None = None
    cc: int | None = None
    error: str | None = None
    candidates: list[str] | None = None


@lru_cache(maxsize=1)
def _load_map() -> dict:
    if not MAP_PATH.exists():
        raise FileNotFoundError(
            f"Mapping fehlt: {MAP_PATH}. "
            f"Erst 'python outputs/generate_cubase_midi_remote.py' laufen lassen."
        )
    return json.loads(MAP_PATH.read_text(encoding="utf-8"))


def reload_map() -> None:
    """Cache leeren (nach Neugenerierung des Mappings)."""
    _load_map.cache_clear()


def map_info() -> dict:
    m = _load_map()
    return {
        "version": m.get("version"),
        "generated_at": m.get("generated_at"),
        "port": m.get("port"),
        "trigger_value": m.get("trigger_value"),
        "command_count": m.get("command_count"),
        "source_sha256": m.get("source_sha256"),
    }


def resolve(command_name: str) -> CommandResolution:
    """command_name -> (channel, cc). Siehe Modul-Docstring fuer Reihenfolge."""
    m = _load_map()
    commands: dict = m["commands"]
    slug_index: dict = m.get("slug_index", {})

    name = (command_name or "").strip()
    if not name:
        return CommandResolution(ok=False, error="command_name leer")

    # 1) exakte "Category/Command"
    if name in commands:
        c = commands[name]
        return CommandResolution(
            ok=True, key=name, category=c["category"], command=c["command"],
            channel=c["channel"], cc=c["cc"],
        )

    # 2) eindeutiger Slug
    nl = name.lower()
    if nl in slug_index:
        key = slug_index[nl]
        c = commands[key]
        return CommandResolution(
            ok=True, key=key, category=c["category"], command=c["command"],
            channel=c["channel"], cc=c["cc"],
        )

    # 3) eindeutiger Command-Name (ohne Kategorie)
    by_cmd = [k for k, c in commands.items() if c["command"] == name]
    if len(by_cmd) == 1:
        c = commands[by_cmd[0]]
        return CommandResolution(
            ok=True, key=by_cmd[0], category=c["category"], command=c["command"],
            channel=c["channel"], cc=c["cc"],
        )
    if len(by_cmd) > 1:
        return CommandResolution(
            ok=False, error=f"'{name}' mehrdeutig — gib 'Category/Command' an.",
            candidates=sorted(by_cmd),
        )

    # Fuzzy-Hinweise: Teilstring-Treffer als Kandidaten.
    hint = sorted(
        k for k, c in commands.items()
        if nl in k.lower() or nl in c["slug"]
    )[:15]
    return CommandResolution(
        ok=False,
        error=f"Command '{name}' nicht im MIDI-Mapping gefunden.",
        candidates=hint or None,
    )


def send_cubase_command(
    command_name: str,
    port: str | None = None,
) -> tuple[CommandResolution, SendResult | None]:
    """
    Loest command_name auf und feuert den Trigger-CC.

    Returns: (resolution, send_result). send_result ist None wenn schon die
    Aufloesung scheitert.
    """
    res = resolve(command_name)
    if not res.ok:
        return res, None

    m = _load_map()
    use_port = port or m.get("port", "AI_CMD")
    trigger = int(m.get("trigger_value", 127))

    send = send_cc(
        cc=res.cc, value=trigger, port=use_port, channel=res.channel,
    )
    return res, send
