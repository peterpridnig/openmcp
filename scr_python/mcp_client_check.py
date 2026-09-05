"""Smoke-test client for the openpaw MCP server.

Connects to mcp/openpaw_mcp_server.py over stdio, lists the server's tools
and lets the user choose which one to test. Run with no arguments for the
interactive menu, or name a tool to run it once and exit:

    .venv/bin/python scr_python/mcp_client_check.py              # menu
    .venv/bin/python scr_python/mcp_client_check.py get_weather  # one shot

Exit codes: 0 = ok, 1 = a tool call failed, 2 = usage error.
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from mcp.types import CallToolResult

REPO = Path(__file__).resolve().parent.parent

EXIT_OK = 0
EXIT_CALL_FAILED = 1
EXIT_USAGE = 2


def _print_content(res: CallToolResult) -> None:
    """Print the result's text blocks and summarize image blocks."""
    for c in res.content:
        text = getattr(c, "text", None)
        if text:
            print(text)
        elif getattr(c, "type", None) == "image":
            mime = getattr(c, "mime_type", None) or getattr(c, "mimeType", None)
            print(f"image content: mime={mime}, b64 len={len(c.data)}")


def _prompt_args(tool: str) -> dict:
    """Collect optional arguments for known tools; Enter accepts the default."""
    args: dict = {}
    if tool == "get_weather":
        city = input("city [Ljubljana]: ").strip()
        unit = input("unit celsius/fahrenheit [celsius]: ").strip().lower()
        if city:
            args["city"] = city
        if unit in ("celsius", "fahrenheit"):
            args["unit"] = unit
    return args


async def run_tool(session: ClientSession, tool: str, prompt: bool) -> bool:
    """Call one tool and print its result; True on success."""
    args = _prompt_args(tool) if prompt else {}
    try:
        res = await session.call_tool(tool, args)
    except Exception as exc:
        print(f"--- {tool} ---\ntransport error: {exc}")
        return False
    print(f"--- {tool} ---")
    _print_content(res)
    if getattr(res, "isError", False):
        print("(tool reported an error)")
        return False
    return True


def _choose_tool(tools: list[str]) -> str | None:
    """Show the menu and return the chosen tool, or None to quit."""
    print()
    print("Which tool do you want to test?")
    for i, name in enumerate(tools, 1):
        print(f"  {i}) {name}")
    print("  q) quit")
    try:
        raw = input(f"choice [1-{len(tools)}, q]: ").strip().lower()
    except EOFError:
        return None
    if raw in ("", "q", "quit", "exit"):
        return None
    if raw.isdigit() and 1 <= int(raw) <= len(tools):
        return tools[int(raw) - 1]
    if raw in tools:
        return raw
    print(f"unknown choice {raw!r}")
    return _choose_tool(tools)


async def main(argv: list[str]) -> int:
    params = StdioServerParameters(
        command=str(REPO / ".venv" / "bin" / "python"),
        args=[str(REPO / "mcp" / "openpaw_mcp_server.py")],
    )
    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            init = await session.initialize()
            info = init.serverInfo if hasattr(init, "serverInfo") else init.server_info
            print("initialized:", info.name, info.version)
            tools = await session.list_tools()
            names = [t.name for t in tools.tools]
            for n in names:
                print("tool:", n)

            if argv:
                if len(argv) != 1 or argv[0] not in names:
                    print(f"usage: mcp_client_check.py [{'|'.join(names)}]")
                    return EXIT_USAGE
                ok = await run_tool(session, argv[0], prompt=False)
                return EXIT_OK if ok else EXIT_CALL_FAILED

            while True:
                tool = _choose_tool(names)
                if tool is None:
                    return EXIT_OK
                await run_tool(session, tool, prompt=True)


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main(sys.argv[1:])))