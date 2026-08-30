# GitHub Copilot — repo guidance

`webcam_grab.py` (stdlib-only Python CLI) captures a still frame from a Linux V4L2 webcam by shelling out to `ffmpeg`. `webcam_mcp_server.py` is an MCP server (official SDK, `mcp>=2`) that reuses the CLI's helpers and exposes `list_webcams()` and `capture_still()` (inline image content) over stdio.

Key points:

- Python 3.10+; keep the stdlib-only, ffmpeg-delegation architecture of the CLI; the MCP server is a thin wrapper that reuses its helpers.
- CLI exit codes are the contract: 0 = success, 1 = capture error, 2 = usage/environment error. Reusable helpers raise `WebcamError`; the server turns it into the SDK's `ToolError` so the model gets an actionable message, not a generic crash.
- ffmpeg stderr is regex-parsed (`FORMAT_LINE_RE`, `SIZE_RE`); size lists are anchored at end-of-line because format descriptions contain colons — preserve that.
- Error messages must stay actionable (video group/permissions, busy device, metadata-only nodes).
- A webcam (real hardware) is required for actual captures; in headless environments only `python3 -m py_compile webcam_grab.py webcam_mcp_server.py` and `python3 webcam_grab.py -h` can be validated. Captures default into `tmp/` (gitignored).

Full details in `AGENTS.md`.