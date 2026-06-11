"""
High-Level Plugin-Control fuer KI-Studio Tier-1.

Wrapper um runtime/midi_bridge/send_cc.py mit:
- Plugin-spezifischen Set-Funktionen (set_pro_q3_band, set_pro_c2)
- Range-Mapping-Logik (linear/log/discrete/bool) gem. midi_channel_layout.json
- Preset-Loader (mix_presets.json -> mehrere CC-Sends in Folge)

Pure Logic — kein DAW-Eingriff ueber MIDI-Send hinaus. Idempotent: jeder
Set-Aufruf liefert eine Result-Struktur mit pro-Param-Success-Status.

Aufruf:
    from runtime.persona.plugin_control import (
        set_pro_q3_band, set_pro_c2, apply_preset, list_presets,
    )

    # EQ-Band setzen mit konkreten Werten
    result = set_pro_q3_band(
        bus='bass', band_num=1, freq_hz=30, gain_db=0,
        q=1.0, shape='Low Cut', enabled=True,
    )

    # Compressor in einem Rutsch
    result = set_pro_c2(
        bus='drums', threshold_db=-18, ratio=4.0, attack_ms=10, release_ms=100,
    )

    # Preset aus Bibliothek anwenden
    result = apply_preset('triphop_bass_default', bus='bass')
"""

from __future__ import annotations

import json
import math
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from runtime.midi_bridge.send_cc import SendResult, send_cc


_KNOWLEDGE_DIR = Path(__file__).resolve().parent / "knowledge"
_LAYOUT_FILE = _KNOWLEDGE_DIR / "midi_channel_layout.json"
_PRESETS_FILE = _KNOWLEDGE_DIR / "mix_presets.json"


# ---------- Cache ----------

_cache: dict[str, Any] = {}


def _load_layout() -> dict[str, Any]:
    if "layout" not in _cache:
        if not _LAYOUT_FILE.exists():
            raise FileNotFoundError(f"Layout-Datei fehlt: {_LAYOUT_FILE}")
        _cache["layout"] = json.loads(_LAYOUT_FILE.read_text(encoding="utf-8"))
    return _cache["layout"]


def _load_presets() -> dict[str, Any]:
    if "presets" not in _cache:
        if not _PRESETS_FILE.exists():
            return {"presets": {}}
        _cache["presets"] = json.loads(_PRESETS_FILE.read_text(encoding="utf-8"))
    return _cache["presets"]


def reload() -> None:
    """Cache leeren - bei externer JSON-Edit."""
    _cache.clear()


# ---------- Bus-Kanal-Konvention ----------

_BUS_TO_CHANNEL: dict[str, int] = {
    "bass": 1,
    "drums": 2,
    "synth": 3,
    "vocals": 4,
    "other": 5,
    "guitar": 6,
    "percussions": 7,
    "backing_vocals": 8,
    "master": 16,
}


def bus_to_channel(bus: str) -> int:
    """Liefert MIDI-Kanal (1-16) fuer einen Bus-Namen.

    Returns Cubase-Kanal (1-16), nicht mido-channel (0-15)!
    Konvention aus midi_channel_layout.json.
    """
    if bus not in _BUS_TO_CHANNEL:
        raise ValueError(f"Unbekannter Bus {bus!r}. Bekannt: {sorted(_BUS_TO_CHANNEL.keys())}")
    return _BUS_TO_CHANNEL[bus]


def cubase_channel_to_mido(channel: int) -> int:
    """Cubase-Kanal (1-16) -> mido-Channel (0-15)."""
    if not 1 <= channel <= 16:
        raise ValueError(f"Cubase-Kanal ausserhalb 1-16: {channel}")
    return channel - 1


# ---------- Range-Mapping ----------

def value_to_cc(
    value: Any,
    range_min: float | None = None,
    range_max: float | None = None,
    mapping_type: str = "linear",
    values_list: list | None = None,
) -> int:
    """
    Konvertiert einen Param-Wert (in Plugin-Einheit) zu CC-Wert (0-127).

    Args:
        value: Plugin-Wert (z.B. -18.0 dB, 30 Hz, 1.0 Q, "Low Cut", True)
        range_min: Minimum der Range (fuer linear/log)
        range_max: Maximum der Range (fuer linear/log)
        mapping_type: 'linear', 'log', 'threshold_64' (bool), oder 'discrete_N'
        values_list: bei discrete — Liste der moeglichen String-Werte

    Returns CC-Wert 0-127 (clamped).
    """
    if mapping_type == "linear":
        if range_min is None or range_max is None:
            raise ValueError("linear mapping braucht range_min + range_max")
        if range_max == range_min:
            raise ValueError("range_min == range_max")
        pct = (float(value) - range_min) / (range_max - range_min)

    elif mapping_type == "log":
        if range_min is None or range_max is None:
            raise ValueError("log mapping braucht range_min + range_max")
        if range_min <= 0 or range_max <= 0:
            raise ValueError(f"Log-Mapping benoetigt positive Range, bekam [{range_min}, {range_max}]")
        v = float(value)
        if v <= 0:
            raise ValueError(f"Log-Mapping mit Wert <= 0: {v}")
        pct = (math.log10(v) - math.log10(range_min)) / (math.log10(range_max) - math.log10(range_min))

    elif mapping_type == "threshold_64":
        # Bool-Mapping: True/127, False/0
        if isinstance(value, bool):
            return 127 if value else 0
        # numerisch: 0 = aus, alles andere = an
        return 127 if value else 0

    elif mapping_type.startswith("discrete_"):
        # Diskrete N-Stufen mit String-Liste.
        # Akzeptiert: String exakt aus values_list, ODER int/float der einen
        # Domain-Wert aus values_list trifft (z.B. 24 fuer "24" dB/oct),
        # ODER int als Index (0..N-1) als Fallback.
        n = int(mapping_type.split("_")[1])
        if values_list is None:
            raise ValueError(f"discrete_{n} braucht values_list")
        position: int | None = None
        if isinstance(value, str):
            if value not in values_list:
                raise ValueError(f"Wert {value!r} nicht in values_list {values_list}")
            position = values_list.index(value)
        elif isinstance(value, (int, float)):
            # Priorisiert: Domain-Wert-Match (Preset speichert "24" als 24 fuer Slope 24 dB/oct).
            # Konvertiere zu String fuer Vergleich mit values_list.
            str_val_int = str(int(value)) if float(value).is_integer() else str(value)
            str_val_float = str(float(value))
            if str_val_int in values_list:
                position = values_list.index(str_val_int)
            elif str_val_float in values_list:
                position = values_list.index(str_val_float)
            else:
                # Fallback: als Index interpretieren
                pos_candidate = int(value)
                if 0 <= pos_candidate < n:
                    position = pos_candidate
                else:
                    raise ValueError(
                        f"Wert {value} weder Domain-Wert in {values_list} "
                        f"noch gueltiger Index 0-{n-1}"
                    )
        else:
            raise ValueError(f"Unerwarteter Typ fuer discrete: {type(value).__name__}")
        # Mitte des jeweiligen Bins treffen
        bin_width = 127.0 / n
        pct = (position + 0.5) * bin_width / 127.0

    else:
        raise ValueError(f"Unbekannter mapping_type: {mapping_type}")

    return max(0, min(127, round(pct * 127)))


# ---------- Layout-Lookup ----------

def _lookup_cc(bus: str, plugin_id: str, param_name: str) -> tuple[int, dict[str, Any]]:
    """
    Findet CC-Nummer + Mapping-Spec fuer (Bus, Plugin, Param-Name).

    Returns (cc_number, mapping_spec) wobei mapping_spec
    {param, range_min, range_max, mapping_type, ...}.

    Sucht NICHT pro Bus separat — Plugin-Mappings sind via Save-as-Default global.
    Nimmt Bus=1 (Bass) als Referenz-Eintrag.
    """
    layout = _load_layout()
    # Referenz aus Kanal 1 (Bass) — alle Pro-Q3-Instanzen haben gleiche Mappings
    bass_plugins = layout["channels"]["1"]["plugins"]
    if plugin_id not in bass_plugins:
        raise ValueError(f"Plugin {plugin_id!r} nicht in Layout. Verfuegbar: {list(bass_plugins.keys())}")
    cc_mappings = bass_plugins[plugin_id].get("cc_mappings", {})
    for cc_str, spec in cc_mappings.items():
        if isinstance(spec, dict) and spec.get("param") == param_name:
            return int(cc_str), spec
    raise ValueError(f"Param {param_name!r} nicht im Plugin {plugin_id}")


# ---------- Result-Strukturen ----------

@dataclass
class ParamResult:
    """Ergebnis eines einzelnen Param-Sends."""
    param: str
    target_value: Any
    cc_sent: int | None
    cc_value: int | None
    ok: bool
    error: str | None = None


@dataclass
class PluginControlResult:
    """Aggregiertes Ergebnis ueber mehrere Param-Sends.

    dry_run=True signalisiert, dass die CCs nur berechnet wurden (Vorschlag),
    aber NICHT an MIDI gesendet wurden — Suggest-then-Confirm-Pattern (STC)
    aus ADR 2026-05-21 + Nicker-Skill-Direktive D4.
    """
    plugin: str
    bus: str
    channel: int
    params: list[ParamResult] = field(default_factory=list)
    all_ok: bool = True
    dry_run: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "plugin": self.plugin,
            "bus": self.bus,
            "channel": self.channel,
            "all_ok": self.all_ok,
            "dry_run": self.dry_run,
            "params": [asdict(p) for p in self.params],
        }


# ---------- Set-Funktionen pro Plugin ----------

def set_pro_q3_band(
    bus: str,
    band_num: int,
    freq_hz: float | None = None,
    gain_db: float | None = None,
    q: float | None = None,
    shape: str | None = None,
    slope: float | None = None,
    enabled: bool | None = None,
    port: str = "AI_INPUT",
    dry_run: bool = False,
) -> PluginControlResult:
    """
    Setzt mehrere Parameter eines Pro-Q3-Bandes in einem Aufruf.

    Args:
        bus: 'bass', 'drums', 'synth', 'vocals', etc.
        band_num: 1, 2 oder 3
        freq_hz: Band-Frequenz in Hz (10..30000)
        gain_db: Gain in dB (-30..+30)
        q: Q-Faktor (0.025..40)
        shape: Filter-Type-String z.B. 'Bell', 'Low Cut', 'Low Shelf', etc.
        slope: dB/oct fuer Cut/Shelf (6, 12, 18, 24, 36, 48, 72, 96)
        enabled: Band an/aus
        port: loopMIDI-Port (default AI_INPUT)
        dry_run: True = berechne CCs, sende aber NICHT (STC-Vorschlag-Phase).
                 False (default) = berechne und sende.

    Nur die gesetzten Params werden gesendet. None bedeutet "nicht aendern".
    """
    cubase_channel = bus_to_channel(bus)
    mido_channel = cubase_channel_to_mido(cubase_channel)
    result = PluginControlResult(
        plugin="fabfilter_pro_q3", bus=bus, channel=cubase_channel, dry_run=dry_run,
    )

    # Sequenz: jeder Param ein separater CC-Send
    params_to_send = [
        ("Enabled", enabled, f"Band {band_num} Enabled"),
        ("Shape", shape, f"Band {band_num} Shape (Filter-Type)"),
        ("Slope", slope, f"Band {band_num} Slope"),
        ("Frequency", freq_hz, f"Band {band_num} Frequency"),
        ("Gain", gain_db, f"Band {band_num} Gain"),
        ("Q", q, f"Band {band_num} Q"),
    ]

    for short_name, target_value, full_param_name in params_to_send:
        if target_value is None:
            continue  # Param nicht gesetzt — skip

        try:
            cc_num, spec = _lookup_cc(bus, "fabfilter_pro_q3", full_param_name)
            mapping_type = spec.get("mapping_type", "linear")
            cc_value = value_to_cc(
                target_value,
                range_min=spec.get("range_min"),
                range_max=spec.get("range_max"),
                mapping_type=mapping_type,
                values_list=spec.get("values"),
            )
            if dry_run:
                # STC-Vorschlag: nichts senden, nur die geplante Aktion zurueckgeben
                result.params.append(ParamResult(
                    param=full_param_name,
                    target_value=target_value,
                    cc_sent=cc_num,
                    cc_value=cc_value,
                    ok=True,
                    error=None,
                ))
            else:
                send_result = send_cc(cc=cc_num, value=cc_value, port=port, channel=mido_channel)
                result.params.append(ParamResult(
                    param=full_param_name,
                    target_value=target_value,
                    cc_sent=cc_num,
                    cc_value=cc_value,
                    ok=send_result.ok,
                    error=send_result.error,
                ))
                if not send_result.ok:
                    result.all_ok = False
        except (ValueError, KeyError) as e:
            result.params.append(ParamResult(
                param=full_param_name,
                target_value=target_value,
                cc_sent=None,
                cc_value=None,
                ok=False,
                error=f"{type(e).__name__}: {e}",
            ))
            result.all_ok = False

    return result


def set_pro_c2(
    bus: str,
    threshold_db: float | None = None,
    ratio: float | None = None,
    attack_ms: float | None = None,
    release_ms: float | None = None,
    knee_db: float | None = None,
    range_db: float | None = None,
    lookahead_ms: float | None = None,
    hold_ms: float | None = None,
    wet_gain_db: float | None = None,
    dry_gain_db: float | None = None,
    port: str = "AI_INPUT",
    dry_run: bool = False,
) -> PluginControlResult:
    """
    Setzt mehrere Parameter eines Pro-C 2 in einem Aufruf.

    Args:
        bus: 'bass', 'drums', etc.
        threshold_db: Threshold (-60..0)
        ratio: Compression-Ratio (1..99)
        attack_ms: Attack (0.05..500)
        release_ms: Release (5..3000)
        knee_db: Knee (0..72)
        range_db: Range (0..60)
        lookahead_ms: Lookahead (0..20)
        hold_ms: Hold (0..500)
        wet_gain_db: Wet Output (-36..+36)
        dry_gain_db: Dry Output fuer Parallel-Comp (-36..+36)
        port: loopMIDI-Port
        dry_run: True = berechne CCs, sende aber NICHT (STC-Vorschlag-Phase).
                 False (default) = berechne und sende.

    Nur gesetzte Params werden gesendet.
    """
    cubase_channel = bus_to_channel(bus)
    mido_channel = cubase_channel_to_mido(cubase_channel)
    result = PluginControlResult(
        plugin="fabfilter_pro_c2", bus=bus, channel=cubase_channel, dry_run=dry_run,
    )

    params_to_send = [
        ("Threshold", threshold_db),
        ("Ratio", ratio),
        ("Attack", attack_ms),
        ("Release", release_ms),
        ("Knee", knee_db),
        ("Range", range_db),
        ("Lookahead", lookahead_ms),
        ("Hold", hold_ms),
        ("Wet Gain", wet_gain_db),
        ("Dry Gain", dry_gain_db),
    ]

    for param_name, target_value in params_to_send:
        if target_value is None:
            continue

        try:
            cc_num, spec = _lookup_cc(bus, "fabfilter_pro_c2", param_name)
            mapping_type = spec.get("mapping_type", "linear")
            cc_value = value_to_cc(
                target_value,
                range_min=spec.get("range_min"),
                range_max=spec.get("range_max"),
                mapping_type=mapping_type,
            )
            if dry_run:
                # STC-Vorschlag: nichts senden, nur die geplante Aktion zurueckgeben
                result.params.append(ParamResult(
                    param=param_name,
                    target_value=target_value,
                    cc_sent=cc_num,
                    cc_value=cc_value,
                    ok=True,
                    error=None,
                ))
            else:
                send_result = send_cc(cc=cc_num, value=cc_value, port=port, channel=mido_channel)
                result.params.append(ParamResult(
                    param=param_name,
                    target_value=target_value,
                    cc_sent=cc_num,
                    cc_value=cc_value,
                    ok=send_result.ok,
                    error=send_result.error,
                ))
                if not send_result.ok:
                    result.all_ok = False
        except (ValueError, KeyError) as e:
            result.params.append(ParamResult(
                param=param_name,
                target_value=target_value,
                cc_sent=None,
                cc_value=None,
                ok=False,
                error=f"{type(e).__name__}: {e}",
            ))
            result.all_ok = False

    return result


# ---------- Preset-Anwendung ----------

def list_presets(category: str | None = None) -> list[dict[str, Any]]:
    """
    Listet verfuegbare Mix-Presets.

    Args:
        category: optional Filter ('bass', 'drums', 'master', etc.)
    """
    data = _load_presets()
    out = []
    for preset_id, preset in data.get("presets", {}).items():
        if category and preset.get("category") != category:
            continue
        out.append({
            "preset_id": preset_id,
            "display_name": preset.get("display_name", preset_id),
            "category": preset.get("category"),
            "description": preset.get("description"),
            "plugins_used": list(preset.get("plugins", {}).keys()),
        })
    return out


def apply_preset(
    preset_id: str,
    bus: str | None = None,
    port: str = "AI_INPUT",
    dry_run: bool = False,
) -> dict[str, Any]:
    """
    Wendet ein Preset aus mix_presets.json auf einen Bus an.

    Args:
        preset_id: Preset-Name (z.B. 'triphop_bass_default')
        bus: Bus-Name; wenn None, wird der im Preset definierte Bus genommen
        port: loopMIDI-Port
        dry_run: True = berechne ALLE CCs des Presets, sende aber NICHT
                 (Suggest-then-Confirm-Phase). False (default) = anwenden.

    Returns aggregiertes Result dict (inkl. "dry_run" Flag).
    """
    data = _load_presets()
    preset = data.get("presets", {}).get(preset_id)
    if preset is None:
        return {
            "ok": False,
            "dry_run": dry_run,
            "error": f"Unbekanntes Preset: {preset_id!r}",
            "available_presets": sorted(data.get("presets", {}).keys()),
        }

    target_bus = bus or preset.get("default_bus")
    if target_bus is None:
        return {
            "ok": False,
            "dry_run": dry_run,
            "error": f"Preset {preset_id!r} hat kein default_bus — explizit angeben",
        }

    results: list[PluginControlResult] = []

    # Pro-Q3-Bands anwenden
    pro_q3 = preset.get("plugins", {}).get("fabfilter_pro_q3")
    if pro_q3:
        for band_spec in pro_q3.get("bands", []):
            r = set_pro_q3_band(
                bus=target_bus,
                band_num=band_spec["num"],
                freq_hz=band_spec.get("freq_hz"),
                gain_db=band_spec.get("gain_db"),
                q=band_spec.get("q"),
                shape=band_spec.get("shape"),
                slope=band_spec.get("slope"),
                enabled=band_spec.get("enabled"),
                port=port,
                dry_run=dry_run,
            )
            results.append(r)

    # Pro-C 2 anwenden
    pro_c2 = preset.get("plugins", {}).get("fabfilter_pro_c2")
    if pro_c2:
        r = set_pro_c2(
            bus=target_bus,
            threshold_db=pro_c2.get("threshold_db"),
            ratio=pro_c2.get("ratio"),
            attack_ms=pro_c2.get("attack_ms"),
            release_ms=pro_c2.get("release_ms"),
            knee_db=pro_c2.get("knee_db"),
            range_db=pro_c2.get("range_db"),
            lookahead_ms=pro_c2.get("lookahead_ms"),
            hold_ms=pro_c2.get("hold_ms"),
            wet_gain_db=pro_c2.get("wet_gain_db"),
            dry_gain_db=pro_c2.get("dry_gain_db"),
            port=port,
            dry_run=dry_run,
        )
        results.append(r)

    all_ok = all(r.all_ok for r in results)
    return {
        "ok": all_ok,
        "dry_run": dry_run,
        "preset_id": preset_id,
        "bus": target_bus,
        "plugin_results": [r.to_dict() for r in results],
    }
