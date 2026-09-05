#!/usr/bin/env python3
"""OpenPaw MCP server: general-purpose local tools.

First tool group — webcam: reuses the capture logic of webcam_grab.py and
speaks the Model Context Protocol over stdio (official Python SDK,
`pip install 'mcp>=2'`). Tools:

    list_webcams()   - list /dev/video* devices with formats and sizes
    capture_still()  - capture one frame, returned as inline image content
    get_weather()    - demo tool: deterministic simulated weather for a city

Run manually for debugging:
    python openpaw_mcp_server.py         # JSON-RPC over stdio
Configure it as an MCP server entry (command: python, args: path/to/
mcp/openpaw_mcp_server.py).
"""

from __future__ import annotations

import sys
import zlib
from datetime import datetime
from pathlib import Path
from typing import Literal

from mcp.server.mcpserver import Image, MCPServer
from mcp.server.mcpserver.exceptions import ToolError

# Import the capture CLI from ../scr_python (fallback: same directory,
# whether run as a script or module).
_here = Path(__file__).resolve().parent
_scr_python = next(
    (
        p
        for p in (_here, _here.parent / "scr_python")
        if (p / "webcam_grab.py").exists()
    ),
    _here.parent / "scr_python",
)
if not (_scr_python / "webcam_grab.py").exists():
    raise ImportError(
        f"webcam_grab.py not found in {_here} or {_here.parent / 'scr_python'}"
    )
sys.path.insert(0, str(_scr_python))

from webcam_grab import (  # noqa: E402
    SIZE_RE,
    WebcamError,
    choose_input_format,
    explain_failure,
    find_default_device,
    find_ffmpeg,
    grab_frame,
    probe_formats,
)

def _find_project_root() -> Path:
    """Walk up from this file to the repo root (the directory containing .git)."""
    here = Path(__file__).resolve().parent
    for candidate in (here, *here.parents):
        if (candidate / ".git").exists():
            return candidate
    return here


PROJECT_ROOT = _find_project_root()
DEFAULT_CAPTURE_DIR = PROJECT_ROOT / "tmp"

mcp = MCPServer(
    name="openpaw",
    title="OpenPaw",
    description=(
        "General-purpose local MCP server (openpaw). First tool group: "
        "still-frame capture from local Linux webcams (V4L2 via ffmpeg); "
        "plus a simple demo weather tool."
    ),
    instructions=(
        "Use list_webcams() first to see devices, pixel formats and sizes, "
        "then capture_still() to grab a frame. capture_still returns the "
        "image as image content plus a summary line; captures are also "
        "saved as files under the repository's tmp/ directory unless an "
        "absolute output path is given. get_weather(city) returns "
        "deterministic simulated demo weather - clearly not a live feed."
    ),
)


def _resolve_output(raw_output: str | None) -> Path:
    """Default captures go to the repo's tmp/ dir; relative paths anchor there."""
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    if raw_output is None:
        return DEFAULT_CAPTURE_DIR / f"webcam_{stamp}.jpg"
    out = Path(raw_output).expanduser()
    if not out.is_absolute():
        out = PROJECT_ROOT / out
    if out.is_dir() or str(out).endswith(("/", "/.")):
        return out / f"webcam_{stamp}.jpg"
    return out


def _capture(
    device: str | None,
    size: str | None,
    input_format: Literal["auto", "mjpeg", "yuyv422"],
    warmup: int,
    quality: int,
    output: str | None,
) -> tuple[Path, Path, str | None, str | None]:
    """Shared capture flow; returns device, output, format, effective size."""
    if warmup < 0:
        raise ToolError("warmup must be >= 0")
    if quality < 1 or quality > 10:
        raise ToolError("quality must be between 1 and 10")
    if size and not SIZE_RE.match(size):
        raise ToolError("size must look like WIDTHxHEIGHT, e.g. 1280x720")
    if device == "":
        raise ToolError("device must be a path like /dev/video0 or omitted")

    ffmpeg = find_ffmpeg()
    try:
        dev = Path(device) if device else find_default_device(ffmpeg)
        formats, _ = probe_formats(ffmpeg, dev)
    except WebcamError as exc:
        raise ToolError(str(exc)) from exc
    resolved_format = choose_input_format(formats, input_format)

    out = _resolve_output(output)
    out.parent.mkdir(parents=True, exist_ok=True)

    proc = grab_frame(
        ffmpeg,
        dev,
        out,
        size=size,
        input_format=resolved_format,
        warmup=warmup,
        quality=quality,
    )
    # A requested size may not be supported by the device; retry once with
    # the device's default size, matching the CLI behavior.
    if proc.returncode != 0 and size:
        proc = grab_frame(
            ffmpeg,
            dev,
            out,
            size=None,
            input_format=resolved_format,
            warmup=warmup,
            quality=quality,
        )
        if proc.returncode == 0:
            size = None  # retry with the device default succeeded

    if proc.returncode != 0 or not out.exists():
        stderr = (proc.stderr or "").strip()
        hints = explain_failure(proc.stderr or "")
        message = f"Capture failed on {dev}."
        if stderr:
            message += f"\nffmpeg said: {stderr}"
        if hints:
            message += f"\nPossible causes:\n{hints}"
        raise ToolError(message)

    return dev, out, resolved_format, size


@mcp.tool(
    description=(
        "List the /dev/video* capture devices and the pixel formats plus "
        "frame sizes each supports. Run this before capturing to pick a "
        "device, size or pixel format for capture_still()."
    ),
)
def list_webcams() -> str:
    """Return a human-readable report of devices and supported formats."""
    try:
        ffmpeg = find_ffmpeg()
    except WebcamError as exc:
        raise ToolError(str(exc)) from exc
    devices = sorted(Path("/dev").glob("video[0-9]*"))
    if not devices:
        raise ToolError("no /dev/video* devices found - is the webcam connected?")

    lines: list[str] = []
    for dev in devices:
        formats, stderr = probe_formats(ffmpeg, dev)
        lines.append(f"{dev}:")
        if not formats:
            if "permission denied" in stderr.lower():
                lines.append(
                    "  permission denied (add the user to the 'video' group "
                    "and log in again)"
                )
            else:
                lines.append("  no capture formats reported (metadata-only node?)")
            continue
        for fmt in formats:
            sizes = " ".join(fmt["sizes"]) or "(device default)"
            lines.append(f"  {fmt['kind']:<10} {fmt['codec']:<10} {sizes}")
    return "\n".join(lines)


def _image_dimensions(path: Path) -> tuple[int, int] | None:
    """Read the pixel dimensions of a JPEG or PNG file (None if unknown)."""
    try:
        with path.open("rb") as fh:
            head = fh.read(24)
            if head.startswith(b"\x89PNG\r\n\x1a\n"):
                return int.from_bytes(head[16:20], "big"), int.from_bytes(head[20:24], "big")
            if not head.startswith(b"\xff\xd8"):
                return None
            # JPEG: walk the marker chain to the first SOFn frame header.
            fh.seek(2)
            while True:
                marker = fh.read(1)
                if len(marker) != 1 or marker != b"\xff":
                    return None
                while marker == b"\xff":
                    marker = fh.read(1)
                if marker in b"\xd8\x01" or b"\xd0" <= marker <= b"\xd7":
                    continue  # standalone marker, no length field
                seg_len_bytes = fh.read(2)
                if len(seg_len_bytes) != 2:
                    return None
                seg_len = int.from_bytes(seg_len_bytes, "big")
                if b"\xc0" <= marker <= b"\xcf" and marker not in (b"\xc4", b"\xc8", b"\xcc"):
                    fh.read(1)  # precision
                    height = int.from_bytes(fh.read(2), "big")
                    width = int.from_bytes(fh.read(2), "big")
                    return width, height
                if seg_len < 2 or fh.seek(seg_len - 2, 1) < 0:
                    return None
    except OSError:
        return None


@mcp.tool(
    description=(
        "Capture one still frame from a webcam and return it as image "
        "content. The frame is also saved to disk: default tmp/webcam_<"
        "timestamp>.jpg under the repository, or pass an output file path "
        "(PNG for .png, JPEG otherwise). Leave device=None to auto-detect "
        "the first usable camera."
    ),
)
def capture_still(
    device: str | None = None,
    size: str | None = None,
    input_format: Literal["auto", "mjpeg", "yuyv422"] = "auto",
    warmup: int = 10,
    quality: int = 2,
    output: str | None = None,
) -> list[Image | str]:
    """Capture a frame; return [image content, summary text]."""
    try:
        dev, out, resolved_format, effective_size = _capture(
            device, size, input_format, warmup, quality, output
        )
    except WebcamError as exc:
        raise ToolError(str(exc)) from exc
    actual = _image_dimensions(out)
    if actual:
        size_note = f"size={actual[0]}x{actual[1]}"
        requested = f"{actual[0]}x{actual[1]}"
        if effective_size and effective_size != requested:
            size_note += f" (requested {effective_size})"
    else:
        size_note = f"size={effective_size or 'device default'}"
    summary = (
        f"Captured {out} from {dev} "
        f"(format={resolved_format or 'device default'}, "
        f"{size_note}, warmup={warmup})"
    )
    return [Image(path=str(out)), summary]


# --- get_weather: a deliberately simple demo tool ---------------------------
# Simulated weather with no network access and no API keys: values are
# derived from a stable hash of the city name, so repeated calls for the
# same city agree while different cities differ. The output is clearly
# labelled as fake so models never present it as a live feed.

_WEATHER_CONDITIONS = (
    "sunny",
    "partly cloudy",
    "overcast",
    "drizzle",
    "light rain",
    "heavy rain",
    "thunderstorm",
    "fog",
    "light snow",
    "heavy snow",
    "windy",
    "clear night sky",
)


@mcp.tool(
    description=(
        "Return the current weather for a city as a summary line. Demo "
        "tool: the data is deterministic simulated weather derived from "
        "the city name (no live feed), handy for testing tool calls."
    ),
)
def get_weather(
    city: str = "Ljubljana",
    unit: Literal["celsius", "fahrenheit"] = "celsius",
) -> str:
    """Return a deterministic simulated weather report for `city`."""
    name = city.strip() if isinstance(city, str) else ""
    if not name:
        raise ToolError("city must be a non-empty name, e.g. 'Ljubljana'")

    seed = zlib.crc32(name.lower().encode("utf-8"))
    condition = _WEATHER_CONDITIONS[seed % len(_WEATHER_CONDITIONS)]
    temp_c = -5.0 + ((seed >> 5) % 380) / 10.0  # -5.0 .. 32.9 °C
    humidity = 30 + (seed >> 8) % 66            # 30 .. 95 %
    wind_kmh = (seed >> 12) % 61                # 0 .. 60 km/h
    feels_c = temp_c - wind_kmh * 0.05 - (1.0 if temp_c > 20.0 else 0.0)

    def fmt(temp_c: float) -> str:
        return (
            f"{temp_c * 9 / 5 + 32:.1f} °F"
            if unit == "fahrenheit"
            else f"{temp_c:.1f} °C"
        )

    return (
        f"{name} (simulated): {condition}, {fmt(temp_c)} "
        f"(feels like {fmt(feels_c)}), humidity {humidity}%, "
        f"wind {wind_kmh} km/h. Demo data - not a live weather feed."
    )


def main() -> int:
    mcp.run(transport="stdio")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())