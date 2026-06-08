"""
Read-only Parser fuer Cubase 15 Port Setup.xml.

Quelle: %APPDATA%/Steinberg/Cubase 15_64/Port Setup.xml

Port-ID-Format: "<I|O>|<Driver>|<Port-Name>"
  - I = MIDI/Audio Input
  - O = MIDI/Audio Output
"""

from __future__ import annotations

import os
import xml.etree.ElementTree as ET
from collections import Counter
from dataclasses import dataclass
from typing import Iterable


DEFAULT_PORT_SETUP_PATH = os.path.join(
    os.environ.get("APPDATA", ""),
    "Steinberg", "Cubase 15_64", "Port Setup.xml",
)

EXPECTED_MACKIE_PORTS: tuple[str, ...] = (
    "I|Windows MIDI|MACKIE_TO_CUBASE",
    "O|Windows MIDI|MACKIE_FROM_CUBASE",
    "I|Windows MIDI|MACKIE_FROM_ABLETON",
    "O|Windows MIDI|MACKIE_TO_ABLETON",
)


@dataclass(frozen=True)
class PortId:
    direction: str  # "I" or "O"
    driver: str
    port: str
    raw: str


def _parse(path: str) -> list[PortId]:
    tree = ET.parse(path)
    root = tree.getroot()
    out: list[PortId] = []
    for s in root.iter("string"):
        if s.get("name") != "ID":
            continue
        raw = s.get("value") or ""
        parts = raw.split("|", 2)
        if len(parts) != 3:
            continue
        out.append(PortId(direction=parts[0], driver=parts[1], port=parts[2], raw=raw))
    return out


def _filter_mackie(ports: Iterable[PortId]) -> list[str]:
    return sorted(p.raw for p in ports if "MACKIE" in p.port.upper())


def validate_port_setup(path: str | None = None) -> dict:
    """
    Parst Port Setup.xml und prueft auf erwartete Mackie-Ports.

    Returns: {
        ok, missing_ports, all_mackie_ports,
        drivers: [{name, count}, ...],
        total_ports, source_path, available
    }
    """
    src = path or DEFAULT_PORT_SETUP_PATH
    if not src or not os.path.isfile(src):
        return {
            "ok": False,
            "available": False,
            "source_path": src,
            "error": f"Port Setup.xml nicht gefunden: {src!r}",
            "missing_ports": list(EXPECTED_MACKIE_PORTS),
            "all_mackie_ports": [],
            "drivers": [],
            "total_ports": 0,
        }

    try:
        ports = _parse(src)
    except ET.ParseError as e:
        return {
            "ok": False,
            "available": True,
            "source_path": src,
            "error": f"XML parse error: {e}",
            "missing_ports": list(EXPECTED_MACKIE_PORTS),
            "all_mackie_ports": [],
            "drivers": [],
            "total_ports": 0,
        }

    raw_ids = {p.raw for p in ports}
    missing = [p for p in EXPECTED_MACKIE_PORTS if p not in raw_ids]
    driver_counts = Counter(p.driver for p in ports)
    drivers = [
        {"name": name, "count": cnt}
        for name, cnt in sorted(driver_counts.items(), key=lambda kv: (-kv[1], kv[0]))
    ]
    return {
        "ok": len(missing) == 0,
        "available": True,
        "source_path": src,
        "missing_ports": missing,
        "all_mackie_ports": _filter_mackie(ports),
        "drivers": drivers,
        "total_ports": len(ports),
        "expected_ports": list(EXPECTED_MACKIE_PORTS),
    }


def list_audio_drivers(path: str | None = None) -> dict:
    """
    Treiber-Verteilung (Inputs/Outputs getrennt + gesamt).
    """
    src = path or DEFAULT_PORT_SETUP_PATH
    if not src or not os.path.isfile(src):
        return {
            "ok": False,
            "available": False,
            "source_path": src,
            "error": f"Port Setup.xml nicht gefunden: {src!r}",
            "drivers": [],
            "total_ports": 0,
        }
    try:
        ports = _parse(src)
    except ET.ParseError as e:
        return {
            "ok": False,
            "available": True,
            "source_path": src,
            "error": f"XML parse error: {e}",
            "drivers": [],
            "total_ports": 0,
        }

    by_driver: dict[str, dict[str, int]] = {}
    for p in ports:
        d = by_driver.setdefault(p.driver, {"inputs": 0, "outputs": 0, "total": 0})
        if p.direction == "I":
            d["inputs"] += 1
        elif p.direction == "O":
            d["outputs"] += 1
        d["total"] += 1

    drivers = [
        {"name": name, **counts}
        for name, counts in sorted(by_driver.items(), key=lambda kv: (-kv[1]["total"], kv[0]))
    ]
    return {
        "ok": True,
        "available": True,
        "source_path": src,
        "drivers": drivers,
        "total_ports": len(ports),
    }
