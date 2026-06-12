"""runtime.setup.doctor — Installations-Diagnose fuer yoka-cubase-mcp.

Aufruf (aus dem Repo-Root):

    python -m runtime.setup.doctor

Prueft in einem Durchlauf:
  * Python-Version (>= 3.11)
  * Python-Dependencies (Core + Windows-AHK + Nicker-Audio)
  * MIDI-Ports (loopMIDI / IAC) — MACKIE_*_CUBASE + AI_INPUT
  * Cubase-Port-Setup (Mackie-Control-Device, via cubase_port_setup.validate)
  * optionale Daten (Plugin-Inventar, volle/Demo-CC-Map, YMP-Wissensbasis)
  * MCP-Server-Import (laedt runtime.mcp.server ohne Fehler)

Exit-Code 0 = alle kritischen Checks bestanden (Warnungen sind ok — z. B. fehlende
MIDI-Ports oder optionale Daten betreffen nur die Live-Steuerung bzw. Zusatz-Features).
Exit-Code 1 = mindestens ein kritischer Fehler (Server evtl. nicht lauffaehig).
"""
from __future__ import annotations

import importlib.util
import io
import sys
from pathlib import Path

# UTF-8-Ausgabe erzwingen (Windows-Konsole ist sonst oft cp1252).
if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

OK, WARN, FAIL = "[OK]  ", "[WARN]", "[FAIL]"
_results: list[tuple[str, str, str]] = []


def _check(level: str, label: str, hint: str = "") -> None:
    _results.append((level, label, hint))


def check_python() -> None:
    v = sys.version_info
    if v >= (3, 11):
        _check(OK, f"Python {v.major}.{v.minor}.{v.micro}")
    else:
        _check(FAIL, f"Python {v.major}.{v.minor} zu alt", "benoetigt >= 3.11")


_CORE_DEPS = [("mido", "mido"), ("rtmidi", "python-rtmidi"), ("mcp", "mcp"), ("pythonosc", "python-osc")]
_AUDIO_DEPS = [("numpy", "numpy"), ("scipy", "scipy"), ("soundfile", "soundfile"), ("pyloudnorm", "pyloudnorm")]


def check_deps() -> None:
    for mod, pkg in _CORE_DEPS:
        if importlib.util.find_spec(mod):
            _check(OK, f"dep {pkg}")
        else:
            _check(FAIL, f"dep {pkg} fehlt", f"pip install {pkg}")
    if sys.platform == "win32":
        if importlib.util.find_spec("win32api"):
            _check(OK, "dep pywin32 (Windows AHK-Bridge)")
        else:
            _check(FAIL, "dep pywin32 fehlt", "pip install pywin32  (Windows-AHK-Bridge)")
    for mod, pkg in _AUDIO_DEPS:
        if importlib.util.find_spec(mod):
            _check(OK, f"dep {pkg} (Nicker-Audio)")
        else:
            _check(WARN, f"dep {pkg} fehlt", f"pip install {pkg}  — Nicker-Audio-Analyse sonst inaktiv")


_EXPECTED_PORTS = ["MACKIE_FROM_CUBASE", "MACKIE_TO_CUBASE", "AI_INPUT"]


def check_midi() -> None:
    try:
        import mido  # noqa: WPS433

        ports = set(mido.get_output_names()) | set(mido.get_input_names())
        for want in _EXPECTED_PORTS:
            # loopMIDI haengt oft eine Index-Zahl an ("MACKIE_FROM_CUBASE 3")
            if any(want in p for p in ports):
                _check(OK, f"MIDI-Port {want}")
            else:
                _check(WARN, f"MIDI-Port {want} nicht gefunden", "loopMIDI (Win) / IAC (mac) Port anlegen")
    except Exception as exc:  # noqa: BLE001
        _check(WARN, "MIDI-Ports nicht pruefbar", str(exc))


def check_cubase_setup() -> None:
    try:
        from runtime.setup.cubase_port_setup import validate_port_setup  # noqa: WPS433

        res = validate_port_setup()
        if res.get("ok"):
            _check(OK, "Cubase Port-Setup (Mackie-Control-Device gefunden)")
        else:
            miss = res.get("missing_ports") or []
            hint = f"fehlende Ports: {miss}" if miss else res.get("error", "Setup-Datei nicht gefunden")
            _check(WARN, "Cubase Port-Setup unvollstaendig", hint)
    except Exception as exc:  # noqa: BLE001
        _check(WARN, "Cubase Port-Setup nicht pruefbar", str(exc))


def check_optional_data() -> None:
    root = Path(__file__).resolve().parent.parent.parent
    kb = root / "runtime" / "persona" / "knowledge"
    mb = root / "runtime" / "midi_bridge"

    if (kb / "yoka_plugins.json").exists():
        _check(OK, "Plugin-Inventar (yoka_plugins.json) vorhanden")
    else:
        _check(WARN, "Plugin-Inventar fehlt (normal im public Build)",
               "python -m runtime.persona.cubase_plugin_sync --apply  (eigenes Cubase scannen)")

    if (mb / "cubase_value_cc_map.json").exists():
        _check(OK, "Volle Plugin-CC-Map vorhanden")
    elif (mb / "cubase_value_cc_map_demo.json").exists():
        _check(WARN, "Nur Demo-CC-Map (1 Stock-Plugin je Kategorie)",
               "eigener Plugin-Scan fuer volle Abdeckung (parse_param_scan.py)")
    else:
        _check(WARN, "Keine CC-Map gefunden", "generate_value_bindings.py laufen lassen")

    try:
        from runtime.persona.ymp_loader import get_studium_path  # noqa: WPS433

        path = get_studium_path()
        if path and path.exists():
            _check(OK, "YMP-Wissensbasis vorhanden")
        else:
            _check(WARN, "YMP-Wissensbasis fehlt — studium-Tools inaktiv",
                   "YMP_PATH setzen oder YMP-Repo als Sibling-Verzeichnis ablegen")
    except Exception:  # noqa: BLE001
        _check(WARN, "YMP-Wissensbasis nicht pruefbar")


def check_server_import() -> None:
    try:
        import runtime.mcp.server as srv  # noqa: WPS433

        _check(OK, f"MCP-Server importiert ({len(srv.TOOLS)} Tools aktiv)")
    except Exception as exc:  # noqa: BLE001
        _check(FAIL, "MCP-Server-Import scheitert", str(exc))


def main() -> int:
    print("yoka-cubase-mcp — Installations-Doctor")
    print("=" * 50)
    check_python()
    check_deps()
    check_midi()
    check_cubase_setup()
    check_optional_data()
    check_server_import()

    print()
    for level, label, hint in _results:
        line = f"{level} {label}"
        if hint:
            line += f"   ->  {hint}"
        print(line)

    fails = sum(1 for r in _results if r[0] == FAIL)
    warns = sum(1 for r in _results if r[0] == WARN)
    print("\n" + "=" * 50)
    print(f"{fails} Fehler, {warns} Warnung(en).")
    if fails:
        print("[FAIL] Kritische Probleme — der Server ist evtl. nicht lauffaehig (siehe oben).")
        return 1
    print("[OK]   Bereit. Warnungen sind optional: Live-Steuerung braucht MIDI-Ports +")
    print("       laufendes Cubase; optionale Daten (Inventar/YMP) sind Zusatz-Features.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
