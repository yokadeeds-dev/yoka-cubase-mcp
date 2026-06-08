"""
Smoke-Test: MCP-Server startet, antwortet auf list_tools, get_daw_state funktioniert.

Voraussetzung: loopMIDI-Ports MACKIE_FROM_CUBASE / MACKIE_TO_CUBASE existieren
(Cubase muss nicht laufen — Listener wartet einfach auf Input, State bleibt im Default).

Aufruf:
    python -m tests.selftests.mcp_server_smoketest
"""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from mcp import ClientSession, StdioServerParameters  # noqa: E402
from mcp.client.stdio import stdio_client  # noqa: E402


async def main() -> int:
    venv_python = ROOT / ".venv" / "Scripts" / "python.exe"
    params = StdioServerParameters(
        command=str(venv_python),
        args=["-m", "runtime.mcp.server"],
        env=None,  # nutzt Defaults im Server
        cwd=str(ROOT),
    )

    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            print("Initialized.\n")

            tools = await session.list_tools()
            print(f"Server-Tools: {len(tools.tools)}")
            for t in tools.tools:
                desc_first_line = (t.description or "").splitlines()[0] if t.description else ""
                print(f"  - {t.name}: {desc_first_line[:80]}")
            print()

            # list_connected_daws — Multi-DAW-Registry zeigen
            print("Call: list_connected_daws")
            result = await session.call_tool("list_connected_daws", arguments={})
            for content in result.content:
                if hasattr(content, "text"):
                    payload = json.loads(content.text)
                    info = payload.get("observed", {})
                    print(f"  ok={payload['ok']}  registered_daws={list(info.keys())}")
                    for daw_name, daw_info in info.items():
                        print(f"    {daw_name:8} listener={daw_info['listener_port']!r:30} sender={daw_info['sender_port']!r:30} initialized={daw_info['initialized']}")
            print()

            # get_daw_state für cubase (default)
            print("Call: get_daw_state (default daw)")
            result = await session.call_tool("get_daw_state", arguments={})
            for content in result.content:
                if hasattr(content, "text"):
                    payload = json.loads(content.text)
                    print(f"  ok={payload['ok']}  target_daw={payload.get('target_daw')!r}  freshness_ms={payload.get('freshness_ms')}")
                    obs = payload.get("observed", {})
                    print(f"  mode={obs.get('mode')!r}  transport.state={obs.get('transport',{}).get('state')!r}")
            print()

            # list_tracks für cubase explizit
            print("Call: list_tracks (daw=cubase explizit)")
            result = await session.call_tool("list_tracks", arguments={"daw": "cubase"})
            for content in result.content:
                if hasattr(content, "text"):
                    payload = json.loads(content.text)
                    tracks = payload.get("observed", [])
                    print(f"  ok={payload['ok']}  target_daw={payload.get('target_daw')!r}  tracks={len(tracks)}")
            print()

            # Versuch ableton anzusprechen — wenn Ports nicht da, kommt graceful Error
            print("Call: get_daw_state (daw=ableton)")
            result = await session.call_tool("get_daw_state", arguments={"daw": "ableton"})
            for content in result.content:
                if hasattr(content, "text"):
                    payload = json.loads(content.text)
                    print(f"  ok={payload['ok']}  target_daw={payload.get('target_daw')!r}")
                    if not payload.get("ok"):
                        print(f"  error={payload.get('error', '')[:120]}")
                    else:
                        obs = payload.get("observed", {})
                        print(f"  mode={obs.get('mode')!r}")
            print()

            # nochmal list_connected_daws — sollte zeigen, welche DAWs jetzt initialisiert wurden
            print("Call: list_connected_daws (nach Tool-Calls)")
            result = await session.call_tool("list_connected_daws", arguments={})
            for content in result.content:
                if hasattr(content, "text"):
                    payload = json.loads(content.text)
                    info = payload.get("observed", {})
                    init = [n for n, x in info.items() if x.get("initialized")]
                    print(f"  initialisierte DAWs: {init}")
            print()

    print("[OK] MCP-Server-Smoketest durchgelaufen.")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
