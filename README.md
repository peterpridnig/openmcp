# openmcp — webcam tools

Grab still pictures from a webcam on Linux, as a dependency-free CLI and as an
MCP (Model Context Protocol) server for AI assistants.

Both components share the same capture logic: they auto-detect the first usable
`/dev/video*` device (skipping metadata-only nodes), discard warm-up frames so
auto-exposure settles, and save JPEG or PNG based on the output file extension.

## Contents

| File | Purpose |
| --- | --- |
| `webcam_grab.py` | CLI that captures one frame via ffmpeg/V4L2 (standard library only) |
| `webcam_mcp_server.py` | MCP server (stdio) exposing `list_webcams` and `capture_still` tools |
| `requirements.txt` | Runtime dependency of the MCP server (`mcp>=2`) |

## Requirements

- Linux with a V4L2 webcam (`/dev/video*`)
- Python 3.10+
- `ffmpeg` on PATH (`sudo apt install ffmpeg`)
- For the MCP server only: `pip install -r requirements.txt`

If you get *permission denied* on the device:
`sudo usermod -aG video $USER`, then log out and back in (group membership
only applies to new login sessions).

## CLI usage

```bash
python webcam_grab.py                          # tmp/webcam_YYYYmmdd_HHMMSS.jpg
python webcam_grab.py -o shot.png              # explicit output path/format
python webcam_grab.py -o /tmp/captures         # directory -> timestamped JPEG
python webcam_grab.py -s 1920x1080 -w 20      # resolution + warm-up frames
python webcam_grab.py -l                      # list device capabilities
python webcam_grab.py -d /dev/video1 -o s.jpg # explicit device
```

Options: `-o/--output`, `-d/--device`, `-s/--size WIDTHxHEIGHT`,
`-f/--input-format {auto,mjpeg,yuyv422}`, `-w/--warmup` (frames to discard,
default 10), `-q/--quality` (1=best..10=worst, default 2), `-l/--list`.

Exit codes: `0` success, `1` capture error, `2` usage/environment error.

## MCP server

Run over stdio:

```bash
pip install -r requirements.txt
python webcam_mcp_server.py
```

Register it with your MCP client, e.g.:

```json
{
  "mcpServers": {
    "webcam": {
      "command": "python3",
      "args": ["/path/to/openmcp/webcam_mcp_server.py"]
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
  The frame is also saved to disk: default `tmp/webcam_<timestamp>.jpg`, or an
  output path you provide (PNG for `.png`, JPEG otherwise). Unsupported
  requested sizes are retried once with the device default.

Errors that can be anticipated (invalid arguments, missing ffmpeg, no camera,
permission problems) are surfaced as tool errors with actionable hints.

## How it works

The webcam is only driven through `ffmpeg` (`v4l2` device with
`-list_formats` for probing, `select` filter for warm-up frames). Capture
logic lives in `webcam_grab.py`; the MCP server is a thin wrapper that reuses
its helpers and is the only component needing the `mcp` package.

## AI agent guidance

See [`AGENTS.md`](AGENTS.md) and
[`.github/copilot-instructions.md`](.github/copilot-instructions.md) for
project conventions, validation commands, and design constraints.