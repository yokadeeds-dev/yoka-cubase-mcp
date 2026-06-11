"""
Plugin-Encoder-Value-Observer — beobachtet Cubase im Plugin-Mode und loggt
ALLE rohen MIDI-Events während Yoka einen Plugin-Knopf im Editor-Fenster
mit der Maus dreht. Ziel: Schema für active_plugin.encoders[N].value_str
empirisch ermitteln.

Hypothese: Cubase pusht bei Encoder-/Param-Changes:
  (a) LCD-SysEx-Update auf row2 mit dem neuen Param-Wert auf der jeweiligen
      Strip-Position, ODER
  (b) Encoder-CC-Echo (CC 16-23) mit Mackie-Inkrement-Encoding, ODER
  (c) Display-Update auf row1 das den Param-Namen vorübergehend durch den
      Wert ersetzt, ODER
  (d) was ganz anderes

Voraussetzung: Cubase in Plugin-Mode, Plugin-Editor offen, Track selektiert.

Aufruf:
    python -m tests.selftests.plugin_encoder_value_observer
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from runtime.mackie.closedloop import ClosedLoopController  # noqa: E402
from runtime.mackie.parser import parse_message  # noqa: E402

CAPTURE_SECONDS = 25


def main() -> int:
    print("Plugin-Encoder-Value-Observer\n")

    with ClosedLoopController(
        listener_port="MACKIE_FROM_CUBASE",
        sender_port="MACKIE_TO_CUBASE",
    ) as cl:
        cl.start_listening()
        time.sleep(0.3)

        print(">>> set_mode('plugin') — sicherstellen dass wir im Plugin-Mode sind")
        cl.set_mode("plugin", timeout_ms=1000)
        time.sleep(0.5)

        # Pre-Snapshot: aktuelle Plugin-Page sichern
        pre_snap = cl.state.snapshot()
        pre_plugin = pre_snap.get("active_plugin")
        if pre_plugin:
            print(f"  Pre: plugin={pre_plugin.get('plugin_name')!r} page={pre_plugin.get('page')}/{pre_plugin.get('page_count')}")
            for e in pre_plugin.get("encoders", []):
                print(f"    ch{e['encoder_index']}: {e['name']!r}")
        else:
            print("  Pre: kein active_plugin — Plugin-Mode nicht aktiv? Yoka muss Plugin-Edit-Page sicherstellen.")
        print()

        # Direkt am Listener-Port lauschen (parallel zum Background-Thread)
        # — wir sammeln Roh-Events MIT timestamp für Auswertung
        import mido
        listener_port = cl._listener_port_name

        # Bereits offener Listener-Thread parsed alles in den State.
        # Wir nutzen ihn UND zusätzlich einen direkten poll-Stream für die
        # Roh-Events (parallel-Read auf demselben Port geht NICHT, also greifen
        # wir auf den Background-Listener zurück und schauen den State-Diff an).

        print(f">>> Capture {CAPTURE_SECONDS}s — DREH JETZT EINEN PLUGIN-KNOPF mit der Maus im Cubase-Plugin-Editor.")
        print("    (Idealerweise einen einzelnen Param mehrmals langsam hin- und herziehen,")
        print("     damit wir mehrere Updates sehen.)")
        print()

        snapshots: list[tuple[float, dict]] = []
        t0 = time.monotonic()
        last_lcd_state: tuple[str, str] | None = None
        events_summary: list[str] = []

        # Polling-Loop alle 100 ms — wir capturn LCD-Reihen-Diffs und Plugin-State-Diffs
        while time.monotonic() - t0 < CAPTURE_SECONDS:
            t = time.monotonic() - t0
            with cl.state._lock:
                row1 = "".join(cl.state._lcd_row1)
                row2 = "".join(cl.state._lcd_row2)
            snap = cl.state.snapshot()
            current_lcd = (row1, row2)
            if last_lcd_state != current_lcd:
                events_summary.append(f"  +{t:5.2f}s LCD-CHANGE")
                events_summary.append(f"    row1: {row1!r}")
                events_summary.append(f"    row2: {row2!r}")
                last_lcd_state = current_lcd
            snapshots.append((t, snap))
            time.sleep(0.05)

        print()
        print(f"=== {len(events_summary) // 3} LCD-Änderungen in {CAPTURE_SECONDS}s ===")
        if events_summary:
            for line in events_summary[:60]:  # limit output
                print(line)
            if len(events_summary) > 60:
                print(f"  ... ({(len(events_summary) - 60) // 3} weitere LCD-Changes ausgelassen)")
        else:
            print("  KEINE LCD-Änderungen erfasst.")
            print("  Mögliche Ursachen:")
            print("   - Cubase nicht im Plugin-Mode (mode != 'plugin')")
            print("   - Du hast keinen Knopf gedreht")
            print("   - Cubase pusht Param-Werte nicht via LCD bei Maus-Edit (anderer Mechanismus)")
        print()

        # Final-State analysieren
        final_snap = cl.state.snapshot()
        final_plugin = final_snap.get("active_plugin")
        if final_plugin:
            print("=== Final active_plugin ===")
            print(f"  plugin={final_plugin.get('plugin_name')!r}, page={final_plugin.get('page')}/{final_plugin.get('page_count')}")
            print(f"  is_overview_page={final_plugin.get('is_overview_page')}")
            print(f"  encoders:")
            for e in final_plugin.get("encoders", []):
                print(f"    ch{e['encoder_index']}: name={e['name']!r}  value_str={e.get('value_str')!r}")
        print()

        # Diff Pre vs Final
        if pre_plugin and final_plugin:
            print("=== Diff Pre vs Final (Plugin-State) ===")
            pre_encoders = {e["encoder_index"]: e for e in pre_plugin.get("encoders", [])}
            final_encoders = {e["encoder_index"]: e for e in final_plugin.get("encoders", [])}
            for idx in range(8):
                pe = pre_encoders.get(idx, {})
                fe = final_encoders.get(idx, {})
                if pe.get("name") != fe.get("name") or pe.get("value_str") != fe.get("value_str"):
                    print(f"  ch{idx}: {pe.get('name')!r}/{pe.get('value_str')!r}  →  {fe.get('name')!r}/{fe.get('value_str')!r}")
            if pre_plugin.get("page") != final_plugin.get("page"):
                print(f"  page: {pre_plugin.get('page')} → {final_plugin.get('page')}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
