"""
Parser fuer Cubase Plug-in-Report.txt (Studio Setup -> Plug-In Manager -> Report).

Liest Yokas Cubase-Plugin-Report ein und erzeugt:
  - JSON-Wissensbasis (runtime/persona/knowledge/yoka_plugins.json)
  - Hersteller-/Kategorie-Statistik
  - Quick-Lookup-Tabellen

Aufruf:
    python -m runtime.persona.parse_plugin_report \\
        --input "C:\\Users\\<user>\\Documents\\##### cubase projekte #####\\
                 The new era 2026\\System Reboot Cubase KI Stuidos\\Plug-in report.txt" \\
        --output runtime/persona/knowledge/yoka_plugins.json

Cubase-Report-Format (fixed-width-Spalten, ~40 Zeichen):
    Name | Vendor | Type | Version | SDK Version | Architecture | ASIO-Guard | Instances | Path

Sektionen im Report:
    - Header (Produkt, Version, Build, OS, Plugin-Counts)
    - "VST2 Plug-in Paths"  (Suchpfade)
    - "Plug-ins that have been added to the blocklist"  (deaktivierte)
    - "VST3 Plug-ins"
    - "VST2 Plug-ins"
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter, defaultdict
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any


SECTION_VST3 = "VST3 Plug-ins"
SECTION_VST2 = "VST2 Plug-ins"
SECTION_BLOCKLIST = "Plug-ins that have been added to the blocklist"


@dataclass
class PluginEntry:
    """Ein Plugin-Eintrag im Report."""
    name: str
    vendor: str
    type: str         # "Fx", "Instrument|Synth", "Fx|Reverb", "Fx|Dynamics|EQ", etc.
    version: str
    sdk_version: str
    architecture: str
    asio_guard: str
    instances: int
    path: str
    vst_format: str   # "VST3" oder "VST2"


@dataclass
class PluginInventory:
    """Vollstaendige Inventarisation."""
    source_file: str
    cubase_version: str
    cubase_build: str
    report_date: str
    total_plugins: int
    effect_plugins: int
    instrument_plugins: int
    vst3_count: int
    vst2_count: int
    blocklisted_count: int
    plugins: list[PluginEntry] = field(default_factory=list)
    blocklist: list[str] = field(default_factory=list)
    vst2_paths: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "source_file": self.source_file,
            "cubase_version": self.cubase_version,
            "cubase_build": self.cubase_build,
            "report_date": self.report_date,
            "summary": {
                "total_plugins": self.total_plugins,
                "effect_plugins": self.effect_plugins,
                "instrument_plugins": self.instrument_plugins,
                "vst3_count": self.vst3_count,
                "vst2_count": self.vst2_count,
                "blocklisted_count": self.blocklisted_count,
            },
            "vst2_paths": self.vst2_paths,
            "blocklist": self.blocklist,
            "plugins": [asdict(p) for p in self.plugins],
        }


def parse_header(lines: list[str]) -> dict[str, Any]:
    """Parsed die Header-Sektion (Cubase-Version, Counts, etc.)."""
    info: dict[str, Any] = {}
    for line in lines[:30]:  # erste 30 Zeilen genügen
        m = re.match(r"^([A-Za-z][A-Za-z /-]+?):\s+(.+?)\s*$", line)
        if m:
            key = m.group(1).strip()
            val = m.group(2).strip()
            info[key] = val
    return info


def parse_plugin_line(line: str, vst_format: str) -> PluginEntry | None:
    """
    Parsed eine einzelne Plugin-Zeile aus der Tabelle.

    Cubase-Report nutzt fixed-width-Spalten. Die Spalten sind:
        Name (40) Vendor (40) Type (40) Version (18) SDK (18) Arch (18) ASIO (18) Inst (18) Path (rest)

    Wir nutzen >=2-space-Split (mehr als ein Whitespace = Spalten-Trenner),
    weil Cubase die Spalten mit Padding fuellt.
    """
    if not line.strip():
        return None

    # Skip Header-Zeile "Name  Vendor  Type  ..."
    if line.lstrip().startswith("Name"):
        return None

    # Split bei 2+ aufeinanderfolgenden Whitespaces
    parts = re.split(r"\s{2,}", line.rstrip())
    if len(parts) < 9:
        return None  # nicht alle Spalten vorhanden = keine Plugin-Zeile

    try:
        name, vendor, ptype, version, sdk, arch, asio, instances_str, path = parts[:9]
        instances = int(instances_str) if instances_str.isdigit() else 0
        return PluginEntry(
            name=name.strip(),
            vendor=vendor.strip(),
            type=ptype.strip(),
            version=version.strip(),
            sdk_version=sdk.strip(),
            architecture=arch.strip(),
            asio_guard=asio.strip(),
            instances=instances,
            path=path.strip(),
            vst_format=vst_format,
        )
    except (ValueError, IndexError):
        return None


def parse_report(report_path: Path) -> PluginInventory:
    """Liest den Cubase-Report ein und liefert eine PluginInventory."""
    text = report_path.read_text(encoding="utf-8", errors="replace")
    lines = text.splitlines()

    # Header
    header = parse_header(lines)
    inv = PluginInventory(
        source_file=str(report_path),
        cubase_version=header.get("Version", "unknown"),
        cubase_build=header.get("Build", "unknown"),
        report_date=header.get("Date/Time", "unknown"),
        total_plugins=int(header.get("Total Plug-ins", "0")),
        effect_plugins=int(header.get("Effect Plug-ins", "0")),
        instrument_plugins=int(header.get("Instrument Plug-ins", "0")),
        vst3_count=int(header.get("VST3 Plug-ins", "0")),
        vst2_count=int(header.get("VST2 Plug-ins", "0")),
        blocklisted_count=int(header.get("Blocklisted Plug-ins", "0")),
    )

    # Sektion-Walking
    current_section: str | None = None
    section_subline: int = 0
    for line in lines:
        stripped = line.strip()

        # Section-Header-Detection
        if SECTION_VST3 == stripped:
            current_section = SECTION_VST3
            section_subline = 0
            continue
        if SECTION_VST2 == stripped:
            current_section = SECTION_VST2
            section_subline = 0
            continue
        if SECTION_BLOCKLIST == stripped:
            current_section = SECTION_BLOCKLIST
            section_subline = 0
            continue
        if stripped.startswith("===="):
            current_section = None
            continue

        # VST2 Paths Section
        if "VST2 Plug-in Paths" in line:
            current_section = "vst2_paths"
            section_subline = 0
            continue

        # Section-Content
        if current_section == SECTION_VST3:
            section_subline += 1
            entry = parse_plugin_line(line, "VST3")
            if entry:
                inv.plugins.append(entry)
        elif current_section == SECTION_VST2:
            section_subline += 1
            entry = parse_plugin_line(line, "VST2")
            if entry:
                inv.plugins.append(entry)
        elif current_section == SECTION_BLOCKLIST:
            if stripped and not stripped.startswith("===="):
                inv.blocklist.append(stripped)
        elif current_section == "vst2_paths":
            if stripped and not stripped.startswith("===="):
                inv.vst2_paths.append(stripped)

    return inv


def make_statistics(inv: PluginInventory) -> dict[str, Any]:
    """Aggregiert Statistik: Plugins pro Hersteller und pro Kategorie."""
    by_vendor = Counter(p.vendor for p in inv.plugins)
    by_category = Counter(p.type for p in inv.plugins)

    # Erste Sub-Kategorie ("Fx|EQ" -> "EQ", "Fx" -> "Fx", "Instrument|Synth" -> "Instrument")
    def first_subcategory(t: str) -> str:
        parts = t.split("|")
        if len(parts) >= 2:
            return parts[1]  # z.B. "EQ", "Reverb", "Synth"
        return parts[0]

    by_primary_category = Counter(first_subcategory(p.type) for p in inv.plugins)

    # Vendor -> Plugins (sortiert nach Vendor-Anzahl)
    vendor_plugins: dict[str, list[str]] = defaultdict(list)
    for p in inv.plugins:
        vendor_plugins[p.vendor].append(p.name)

    return {
        "by_vendor": dict(by_vendor.most_common()),
        "by_full_category": dict(by_category.most_common()),
        "by_primary_category": dict(by_primary_category.most_common()),
        "vendor_plugins": {
            vendor: sorted(set(plugs))  # dedupliziert
            for vendor, plugs in sorted(vendor_plugins.items())
        },
    }


def main() -> int:
    p = argparse.ArgumentParser(description="Parsed Cubase Plug-in-Report -> JSON Inventory.")
    p.add_argument(
        "--input", "-i", required=True,
        help="Pfad zur Cubase Plug-in report.txt",
    )
    p.add_argument(
        "--output", "-o",
        default="runtime/persona/knowledge/yoka_plugins.json",
        help="Output-JSON-Pfad",
    )
    p.add_argument(
        "--stats", action="store_true",
        help="Statistik auf stdout ausgeben",
    )
    args = p.parse_args()

    inp = Path(args.input)
    if not inp.exists():
        print(f"FEHLER: {inp} nicht gefunden.", file=sys.stderr)
        return 1

    print(f"Parse {inp}...")
    inv = parse_report(inp)

    print(f"\nGefunden:")
    print(f"  Cubase {inv.cubase_version} (Build {inv.cubase_build})")
    print(f"  Total laut Header: {inv.total_plugins}")
    print(f"  Parsed: {len(inv.plugins)} Plugins")
    print(f"  Blocklisted: {len(inv.blocklist)}")
    print(f"  VST2-Pfade: {len(inv.vst2_paths)}")

    # JSON-Output
    out = Path(args.output)
    out.parent.mkdir(parents=True, exist_ok=True)
    stats = make_statistics(inv)
    payload = {
        **inv.to_dict(),
        "statistics": stats,
    }
    out.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"\n[OK] JSON geschrieben: {out}")

    if args.stats:
        print("\n--- Top 15 Vendors ---")
        for v, c in list(stats["by_vendor"].items())[:15]:
            print(f"  {c:3d}  {v}")
        print("\n--- Top 15 Primary Categories ---")
        for c, n in list(stats["by_primary_category"].items())[:15]:
            print(f"  {n:3d}  {c}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
