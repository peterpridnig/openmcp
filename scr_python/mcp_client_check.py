import asyncio
from pathlib import Path

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

REPO = Path(__file__).resolve().parent.parent


async def main() -> None:
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
            for t in tools.tools:
                print("tool:", t.name)

            res = await session.call_tool("list_webcams", {})
            print("--- list_webcams ---")
            for c in res.content:
                if getattr(c, "text", None):
                    print(c.text)

            res = await session.call_tool("capture_still", {})
            print("--- capture_still ---")
            for c in res.content:
                text = getattr(c, "text", None)
                if text:
                    print(text)
                elif getattr(c, "type", None) == "image":
                    mime = getattr(c, "mime_type", None) or getattr(c, "mimeType", None)
                    print(f"image content: mime={mime}, b64 len={len(c.data)}")


asyncio.run(main())