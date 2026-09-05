# AGENTS.md — guidance for AI coding agents

## Project

Single-file Python CLI: `scr_python/webcam_grab.py`. It captures one still frame from a Linux V4L2 webcam by delegating to `ffmpeg` (no Python imaging libs). It auto-detects the first usable `/dev/video*` device, discards warm-up frames so auto-exposure settles, and writes JPEG/PNG based on the output extension.

`mcp/openpaw_mcp_server.py` is a general-purpose MCP server (official Python SDK, `mcp>=2`); the webcam is its first tool group. It wraps the capture logic and exposes it over stdio:

- `list_webcams()` — devices with supported pixel formats and sizes.
- `capture_still()` — captures a frame, returns inline image content plus a summary line; saves to `tmp/` unless an output path is given.
- `get_weather()` — demo tool returning deterministic simulated weather for a city (no live feed).

Anticipated failures (validation, missing ffmpeg, no camera, permission) raise the SDK's `ToolError` so the model receives an actionable message instead of "Error executing tool". There is no package, no test suite. Do not introduce one unless asked.

## Environment requirements

- Python 3.10+ (uses `from __future__ import annotations`, `X | Y` unions, `pathlib`).
- `ffmpeg` on PATH (`sudo apt install ffmpeg`). This is the only external dependency.
- A webcam requires real hardware; in headless/CI environments capture cannot be tested — do not "fix" the code because `-l` or a capture fails with no `/dev/video*` present.

There is a Python dependency now (server only): `./setup.sh` creates `.venv/` and installs `requirements.txt` (`mcp>=2.0`) into it; `--force` recreates the venv from scratch. `webcam_grab.py` itself stays stdlib-only.

## Commands

```bash
python3 -m py_compile scr_python/webcam_grab.py mcp/openpaw_mcp_server.py   # syntax check (minimum validation)
python3 scr_python/webcam_grab.py -l                 # list device formats (needs a camera)
python3 scr_python/webcam_grab.py                    # capture to tmp/webcam_<timestamp>.jpg
python3 scr_python/webcam_grab.py -h                 # CLI help
./setup.sh && .venv/bin/python mcp/openpaw_mcp_server.py   # MCP stdio server (spawned by MCP clients; no service needed)
```

Run with `--help` and smoke-test argument parsing rather than doing real captures when possible. To validate the MCP server without an IDE, drive it with the SDK's `mcp.client.session`/`stdio_client` client (spawn the server, initialize, `list_tools`, `call_tool`).

## Conventions

- Capture logic (`webcam_grab.py`) is standard library only; shelling out to `ffmpeg` is the intended architecture. `mcp/openpaw_mcp_server.py` adds the `mcp` SDK dependency and must stay a thin wrapper that reuses the CLI's helpers rather than reimplementing ffmpeg calls.
- The CLI's exit codes are part of its contract: `0` success, `1` capture error, `2` usage/environment error (via `argparse`/`sys.exit` with a message). Reusable helpers raise `WebcamError`; `main()` converts that to exit code 1. The MCP server converts it to `ToolError` instead.
- ffmpeg's stderr is parsed with regexes (`FORMAT_LINE_RE`, `SIZE_RE`); description strings may contain colons, so sizes are matched at end-of-line — keep that anchoring when editing.
- Errors should be actionable: keep and extend the hint messages (permission denied → `usermod -aG video`, busy device, metadata-only nodes, etc.).
- Linux/V4L2 only; don't add macOS/Windows backends unless asked.
- User-facing sample writes default to the repo's `tmp/` (regardless of cwd for the CLI) — that path must stay gitignored.