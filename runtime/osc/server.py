"""OSC-Server: laeuft als separater Prozess, empfaengt OSC-Messages und
leitet sie via Translator weiter.

Aufruf:
    python -m runtime.osc.server --port 9000 --backend mackie --daw cubase
    python -m runtime.osc.server --port 9000 --backend dry_log  # Schema-Sanity-Test

Test von Yokas Seite:
    # Python:
    from pythonosc.udp_client import SimpleUDPClient
    c = SimpleUDPClient("127.0.0.1", 9000)
    c.send_message("/transport/play", [])
    c.send_message("/track/3/volume_db", [-12.5])
    c.send_message("/plugin/preset/triphop_bass_default/dry_run", [])

    # oscsend (Linux/Mac, oder via Choco-Install auf Win):
    oscsend localhost 9000 /transport/play
    oscsend localhost 9000 /track/3/volume_db f -12.5

Schema-Liste sehen: --list-schema
"""
from __future__ import annotations

import argparse
import logging
import signal
import sys
from typing import Any

from pythonosc import dispatcher as osc_dispatcher
from pythonosc.osc_server import BlockingOSCUDPServer

from runtime.osc.schema import default_schema
from runtime.osc.translator import OSCTranslator

logger = logging.getLogger(__name__)


def make_handler(translator: OSCTranslator):
    """Erzeugt einen pythonosc-Handler der auf alle Adressen matcht."""
    def handle(address: str, *args: Any) -> None:
        result = translator.handle(address, *args)
        status = "OK" if result.ok else "FAIL"
        msg = f"[{status}] {address} -> {result.action_type}"
        if result.extracted:
            msg += f"  extracted={result.extracted}"
        if args:
            msg += f"  args={list(args)}"
        if result.error:
            msg += f"  error={result.error!r}"
        if result.backend_response:
            msg += f"  response={result.backend_response}"
        print(msg, flush=True)
    return handle


def print_schema() -> None:
    """Listet alle bekannten OSC-Adressen."""
    schema = default_schema()
    print(f"OSC-Schema: {schema.name} v{schema.version}\n")
    for pattern, action in schema.actions.items():
        print(f"  {pattern}")
        print(f"    -> {action.action_type}")
        print(f"    {action.description}")
        if action.arg_schema:
            print(f"    args: {action.arg_schema}")
        if action.notes:
            print(f"    notes: {action.notes}")
        print()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="KI-Studio OSC-Bridge")
    parser.add_argument("--port", type=int, default=9000, help="OSC-UDP-Port (default 9000)")
    parser.add_argument("--host", default="127.0.0.1", help="Bind-Host (default 127.0.0.1, local-only)")
    parser.add_argument(
        "--backend",
        choices=["mackie", "mcp", "dry_log"],
        default="dry_log",
        help="Backend: mackie=via loopMIDI, mcp=direkter Tool-Call, dry_log=nur loggen",
    )
    parser.add_argument("--daw", default="cubase", help="DAW-Name fuer mackie/mcp-Backend")
    parser.add_argument(
        "--midi-port",
        default="AI_INPUT",
        help="loopMIDI-Port-Name fuer mackie-Backend (default AI_INPUT)",
    )
    parser.add_argument("--list-schema", action="store_true", help="Listet alle OSC-Adressen und exitet")
    parser.add_argument("--verbose", action="store_true")
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    if args.list_schema:
        print_schema()
        return 0

    translator = OSCTranslator(
        backend=args.backend,
        default_daw=args.daw,
        port=args.midi_port,
    )

    disp = osc_dispatcher.Dispatcher()
    disp.set_default_handler(make_handler(translator))

    server = BlockingOSCUDPServer((args.host, args.port), disp)
    print(f"OSC-Server laeuft auf {args.host}:{args.port} (backend={args.backend}, daw={args.daw})", flush=True)
    print("Strg+C zum Beenden.", flush=True)

    # Sauberes Shutdown auf SIGINT
    def shutdown(_sig: int, _frame: Any) -> None:
        print("\n[SHUTDOWN] beende OSC-Server ...", flush=True)
        server.shutdown()

    signal.signal(signal.SIGINT, shutdown)

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
        print("[OK] OSC-Server beendet", flush=True)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
