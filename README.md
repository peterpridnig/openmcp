# openmcp — local tools

`openpaw` is a general-purpose MCP (Model Context Protocol) server for AI
assistants — the webcam tool is just the beginning. Still pictures from a
webcam on Linux are available both through the MCP server and as a
dependency-free CLI.

Both components share the same capture logic: they auto-detect the first usable
`/dev/video*` device (skipping metadata-only nodes), discard warm-up frames so
auto-exposure settles, and save JPEG or PNG based on the output file extension.

## Contents

| File | Purpose |
| --- | --- |
| `scr_python/webcam_grab.py` | CLI that captures one frame via ffmpeg/V4L2 (standard library only) |
| `mcp/openpaw_mcp_server.py` | General-purpose MCP server (stdio); first tool group: `list_webcams` and `capture_still` |
| `scr_python/mcp_client_check.py` | Dev helper that drives the MCP server end-to-end (initialize, list tools, call tools) |
| `requirements.txt` | Runtime dependency of the MCP server (`mcp>=2`) |
| `setup.sh` | Creates/recreates `.venv/` and installs `requirements.txt` into it |
| `rund.sh` | Install/start/stop/status the MCP server as systemd user service `openpaw-mcp.service` (no sudo) |

## Requirements

- Linux with a V4L2 webcam (`/dev/video*`)
- Python 3.10+
- `ffmpeg` on PATH (`sudo apt install ffmpeg`)
- For the MCP server only: run `./setup.sh` (creates `.venv/` from `requirements.txt`)

If you get *permission denied* on the device:
`sudo usermod -aG video $USER`, then log out and back in (group membership
only applies to new login sessions).

## CLI usage

```bash
python scr_python/webcam_grab.py                          # repo tmp/webcam_YYYYmmdd_HHMMSS.jpg
python scr_python/webcam_grab.py -o shot.png              # explicit output path/format
python scr_python/webcam_grab.py -o /tmp/captures         # directory -> timestamped JPEG
python scr_python/webcam_grab.py -s 1920x1080 -w 20      # resolution + warm-up frames
python scr_python/webcam_grab.py -l                      # list device capabilities
python scr_python/webcam_grab.py -d /dev/video1 -o s.jpg # explicit device
```

Default captures land in the repo's `tmp/` no matter which directory you run
the CLI from (`./tmp` when invoked outside a git checkout).

Options: `-o/--output`, `-d/--device`, `-s/--size WIDTHxHEIGHT`,
`-f/--input-format {auto,mjpeg,yuyv422}`, `-w/--warmup` (frames to discard,
default 10), `-q/--quality` (1=best..10=worst, default 2), `-l/--list`.

Exit codes: `0` success, `1` capture error, `2` usage/environment error.

## MCP server

`openpaw` is a general-purpose MCP server that speaks JSON-RPC over **stdio**,
built on the official Python SDK (`mcp>=2`). It runs as a plain process — no
ports, no daemon — so any MCP client can spawn and shut it down like a
subcommand. The webcam tools are the first tool group; more are planned.

### Setup

```bash
./setup.sh                       # creates/reuses .venv/ and installs requirements.txt
source .venv/bin/activate
python mcp/openpaw_mcp_server.py
```

### Client registration

The `mcp` SDK lives in the repo's `.venv/`, so point the client at that
interpreter (not system `python3`), e.g.:

```json
{
  "mcpServers": {
    "openpaw": {
      "command": "/path/to/openmcp/.venv/bin/python",
      "args": ["/path/to/openmcp/mcp/openpaw_mcp_server.py"]
    }
  }
}
```

### Tools

- **`list_webcams()`** — lists `/dev/video*` devices with the pixel formats and
  frame sizes each supports. Use it to pick `device`, `size` and `input_format`
  before capturing.
- **`capture_still(device=None, size=None, input_format="auto", warmup=10,
  quality=2, output=None)`** — captures one frame and returns it as inline
  image content plus a summary line (including the actual frame dimensions).

  | Parameter | Default | Meaning |
  | --- | --- | --- |
  | `device` | auto-detected | Explicit `/dev/video*` path |
  | `size` | device default | `"WIDTHxHEIGHT"`; unsupported sizes are retried once with the device default |
  | `input_format` | `auto` | `auto`, `mjpeg` or `yuyv422` |
  | `warmup` | `10` | Frames discarded first so auto-exposure settles |
  | `quality` | `2` | ffmpeg JPEG quality scale, `1`=best .. `10`=worst |
  | `output` | `tmp/webcam_<timestamp>.jpg` | File or directory (relative paths anchor at the repo root); PNG for `.png`, JPEG otherwise |

### Error handling

Anticipated failures (invalid arguments, missing ffmpeg, no camera, busy
device, permission problems) don't crash the server or return a generic
"Error executing tool": they are converted to MCP tool errors with actionable
hints — e.g. *permission denied* suggests
`sudo usermod -aG video $USER`, a metadata-only node is called out as such.

### Test without an IDE

A ready-made check script ships with the repo:

```bash
.venv/bin/python scr_python/mcp_client_check.py
```

`mcp_client_check.py` spawns the server over stdio, initializes a session,
lists the tools, then calls `list_webcams()` and `capture_still()`, printing
each result — so a green run exercises the full round-trip (including the
saved capture under `tmp/`). Run `./setup.sh` first; paths are derived from
the script location, so it works from any checkout.

Under the hood it is just the SDK's stdio client — spawn, initialize,
`list_tools`, `call_tool`:

```python
import asyncio
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

async def main():
    params = StdioServerParameters(
        command="/path/to/openmcp/.venv/bin/python",
        args=["/path/to/openmcp/mcp/openpaw_mcp_server.py"],
    )
    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            tools = await session.list_tools()
            print([t.name for t in tools.tools])
            result = await session.call_tool("list_webcams", {})
            print(result.content[0].text)

asyncio.run(main())
```

### Extending

New tool groups follow the established pattern: keep the underlying logic in
`scr_python/` (standard library only), register the tools on the `mcp`
instance in `mcp/openpaw_mcp_server.py`, and raise the SDK's `ToolError` with
an actionable message for anything that can be anticipated to fail.

### Run as a user service

`./rund.sh` manages `openpaw-mcp.service` as a systemd **user** service
(`~/.config/systemd/user/`, controlled with `systemctl --user`) — no sudo
required. With linger enabled it starts at boot without an active login
session. Note the server speaks stdio: as a service it stays alive and
supervised but idle — real MCP clients still spawn their own instance.

```bash
./rund.sh install   # writes the unit, daemon-reload, enable (+ linger)
./rund.sh start     # start + show status
./rund.sh stop      # stop
./rund.sh status    # show status
./rund.sh unit      # print the generated unit file to stdout
```

## How it works

The webcam is only driven through `ffmpeg` (`v4l2` device with
`-list_formats` for probing, `select` filter for warm-up frames). Capture
logic lives in `webcam_grab.py`; the MCP server is a thin wrapper that reuses
its helpers and is the only component needing the `mcp` package.

## AI agent guidance

See [`AGENTS.md`](AGENTS.md) and
[`.github/copilot-instructions.md`](.github/copilot-instructions.md) for
project conventions, validation commands, and design constraints.