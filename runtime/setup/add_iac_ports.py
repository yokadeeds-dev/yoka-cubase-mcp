"""
Mac-Setup-Utility: IAC-Ports via CoreMIDI-API anlegen.

Legt alle benötigten virtuellen MIDI-Ports im IAC-Treiber an,
falls sie noch nicht existieren. Idempotent — bestehende Ports
werden nicht doppelt angelegt.

Usage:
    python -m runtime.setup.add_iac_ports
    python -m runtime.setup.add_iac_ports --dry-run

Erfordert: pyobjc-framework-CoreMIDI (pip install pyobjc-framework-CoreMIDI)
Nur macOS — auf Windows wird dieser Schritt übersprungen.
"""

from __future__ import annotations

import platform
import sys

REQUIRED_PORTS = [
    "MACKIE_FROM_CUBASE",
    "MACKIE_TO_CUBASE",
    "MACKIE_FROM_ABLETON",
    "MACKIE_TO_ABLETON",
]


def main(dry_run: bool = False) -> int:
    if platform.system() != "Darwin":
        print("Nur auf macOS verfügbar — übersprungen.")
        return 0

    try:
        import CoreMIDI
    except ImportError:
        print("pyobjc-framework-CoreMIDI nicht installiert.")
        print("  pip install pyobjc-framework-CoreMIDI")
        return 1

    import mido

    # IAC-Device finden (immer Device 0 oder nach Name)
    iac_device = None
    for i in range(CoreMIDI.MIDIGetNumberOfDevices()):
        dev = CoreMIDI.MIDIGetDevice(i)
        _, name = CoreMIDI.MIDIObjectGetStringProperty(dev, CoreMIDI.kMIDIPropertyName, None)
        if name and "IAC" in str(name):
            iac_device = dev
            print(f"IAC-Device gefunden: {name!r}")
            break

    if iac_device is None:
        print("FEHLER: Kein IAC-Device gefunden.")
        print("  → Audio MIDI Setup öffnen → IAC Driver → 'Device is online' aktivieren")
        return 1

    # Bestehende Ports ermitteln
    existing = {p.split(" ")[-1] for p in mido.get_input_names() if p is not None}
    existing |= {p.split(" ")[-1] for p in mido.get_output_names() if p is not None}

    added = []
    skipped = []

    for port_name in REQUIRED_PORTS:
        if port_name in existing:
            skipped.append(port_name)
            print(f"  ✓ {port_name!r} (bereits vorhanden)")
        else:
            if not dry_run:
                err, _ = CoreMIDI.MIDIDeviceAddEntity(iac_device, port_name, False, 1, 1, None)
                if err != 0:
                    print(f"  ✗ {port_name!r} — Fehler: {err}")
                    continue
            added.append(port_name)
            tag = "(dry-run)" if dry_run else "→ angelegt"
            print(f"  + {port_name!r} {tag}")

    print(f"\nFertig: {len(added)} angelegt, {len(skipped)} bereits vorhanden.")
    return 0


if __name__ == "__main__":
    dry_run = "--dry-run" in sys.argv
    raise SystemExit(main(dry_run=dry_run))
