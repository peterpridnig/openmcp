#!/usr/bin/env python3
"""Grab a still picture from a webcam.

A dependency-free CLI that captures a single frame from a V4L2 video device
by delegating to ffmpeg. It auto-detects the first usable /dev/video* device,
waits for the camera's auto-exposure to settle (warm-up frames), and saves
the result as JPEG or PNG depending on the output file extension.

Prerequisites:
    ffmpeg installed (e.g. 'sudo apt install ffmpeg')

Usage:
    python webcam_grab.py                          # tmp/webcam_YYYYmmdd_HHMMSS.jpg
    python webcam_grab.py -o shot.png             # explicit output path/format
    python webcam_grab.py -o /tmp/captures        # directory -> timestamped JPEG
    python webcam_grab.py -s 1920x1080 -w 20      # resolution + warm-up frames
    python webcam_grab.py -l                      # list device capabilities
    python webcam_grab.py -d /dev/video1 -o s.jpg # explicit device

Exit codes:
    0 success, 1 capture error, 2 usage/environment error
"""

from __future__ import annotations

import argparse
import re
import shutil
import subprocess
import sys
from datetime import datetime
from pathlib import Path

# Lines look like:
# [video4linux2,v4l2 @ 0x...] Compressed:       mjpeg : Motion-JPEG : 1920x1080 640x480
# [video4linux2,v4l2 @ 0x...] Raw       :     yuyv422 :           YUYV 4:2:2 : 640x480
# Note: descriptions may themselves contain colons ("YUYV 4:2:2"), so the
# sizes list is anchored at the end of the line rather than split naively.
FORMAT_LINE_RE = re.compile(
    r"^\[[^\]]+\]\s+(Compressed|Raw)\s*:\s+(\S+)\s*:\s+(.+?)\s*:\s*([0-9xX ]+)$"
)
SIZE_RE = re.compile(r"^(\d+)[xX](\d+)$")


class WebcamError(RuntimeError):
    """Environment or capture problem that maps to CLI exit code 1."""


def find_ffmpeg() -> str:
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        raise WebcamError(
            "Error: ffmpeg not found. Install it (e.g. 'sudo apt install ffmpeg')."
        )
    return ffmpeg


def probe_formats(
    ffmpeg: str, device: Path
) -> tuple[list[dict[str, str]], str]:
    """Return the capture formats a device supports, plus raw probe stderr."""
    cmd = [
        ffmpeg, "-hide_banner", "-f", "v4l2", "-list_formats", "all",
        "-i", str(device),
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True)
    formats: list[dict[str, str]] = []
    for line in (proc.stderr or "").splitlines():
        match = FORMAT_LINE_RE.match(line.strip())
        if not match:
            continue
        kind, codec, desc, sizes = match.groups()
        formats.append(
            {
                "kind": kind,
                "codec": codec,
                "description": desc.strip(),
                "sizes": sizes.split(),
            }
        )
    return formats, proc.stderr or ""


def find_default_device(ffmpeg: str) -> Path:
    """Return the first /dev/video* node that reports capture formats.

    UVC webcams often expose extra metadata-only nodes (/dev/video1) which
    cannot produce frames; those are skipped. Distinguishes permission
    problems from genuinely unusable devices so the error message is useful.
    """
    devices = sorted(Path("/dev").glob("video[0-9]*"))
    if not devices:
        raise WebcamError(
            "Error: no /dev/video* devices found. Is the webcam connected?"
        )

    access_denied = False
    for device in devices:
        formats, stderr = probe_formats(ffmpeg, device)
        if formats:
            return device
        if "permission denied" in stderr.lower():
            access_denied = True

    if access_denied:
        raise WebcamError(
            "Error: permission denied on the video device.\n"
            "The 'video' group membership only applies to NEW login sessions.\n"
            "  1. sudo usermod -aG video $USER   (already done? then just re-login)\n"
            "  2. Log out and back in (or reboot), then run this script again.\n"
            "Temporary workaround:\n"
            "  sg video -c 'python3 scr/webcam_grab.py'"
        )
    raise WebcamError(
        f"Error: none of {', '.join(str(d) for d in devices)} "
        "reported capture formats (metadata-only nodes?)."
    )


def choose_input_format(
    formats: list[dict[str, str]], requested: str
) -> str | None:
    """Pick the pixel format ffmpeg should request from the device."""
    if requested != "auto":
        return requested
    for codec in ("mjpeg", "yuyv422"):
        if any(f["codec"] == codec for f in formats):
            return codec
    return None  # let the driver pick its default


def explain_failure(stderr: str) -> str:
    """Turn common ffmpeg failures into actionable hints."""
    low = stderr.lower()
    hints: list[str] = []
    if "permission denied" in low:
        hints.append(
            "no permission on the device: run 'sudo usermod -aG video $USER' "
            "and log in again"
        )
    if "busy" in low:
        hints.append("device is in use by another process")
    if "no such file or directory" in low:
        hints.append("device path does not exist")
    if "not contain video" in low or "ioctl" in low:
        hints.append("device does not support video capture (metadata-only node?)")
    return "\n".join(f"  - {h}" for h in hints)


def grab_frame(
    ffmpeg: str,
    device: Path,
    output: Path,
    size: str | None = None,
    input_format: str | None = None,
    warmup: int = 10,
    quality: int = 2,
) -> subprocess.CompletedProcess[str]:
    """Run ffmpeg to capture one frame, discarding `warmup` frames first."""
    cmd = [ffmpeg, "-hide_banner", "-loglevel", "error", "-y", "-f", "v4l2"]
    if input_format:
        cmd += ["-input_format", input_format]
    if size:
        cmd += ["-video_size", size]
    cmd += ["-i", str(device)]
    if warmup > 0:
        # Keep only frame number >= warmup, so auto-exposure has time to settle.
        cmd += ["-vf", f"select=gte(n\\,{warmup})"]
    if output.suffix.lower() in (".jpg", ".jpeg"):
        cmd += ["-q:v", str(quality)]
    cmd += ["-frames:v", "1", "-update", "1", str(output)]
    return subprocess.run(cmd, capture_output=True, text=True)


def resolve_output(raw_output: str | None) -> Path:
    """Default to a timestamped JPEG under ./tmp; allow -o to pick file or dir."""
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    if raw_output is None:
        return Path("tmp") / f"webcam_{stamp}.jpg"
    out = Path(raw_output).expanduser()
    if str(out).endswith(("/", "/.")) or out.is_dir():
        return out / f"webcam_{stamp}.jpg"
    return out


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Grab a single still picture from a webcam via ffmpeg."
    )
    parser.add_argument(
        "-o",
        "--output",
        help="Output file path (JPEG or PNG by extension) or directory "
        "for a timestamped JPEG. Default: tmp/webcam_<timestamp>.jpg.",
    )
    parser.add_argument(
        "-d",
        "--device",
        type=Path,
        default=None,
        help="Video device to use (default: first usable /dev/video*).",
    )
    parser.add_argument(
        "-s",
        "--size",
        default=None,
        help="Frame size as WIDTHxHEIGHT, e.g. 1920x1080 (default: device default).",
    )
    parser.add_argument(
        "-f",
        "--input-format",
        choices=["auto", "mjpeg", "yuyv422"],
        default="auto",
        help="Pixel format requested from the device (default: auto).",
    )
    parser.add_argument(
        "-w",
        "--warmup",
        type=int,
        default=10,
        help="Frames to discard first so auto-exposure settles (default: 10).",
    )
    parser.add_argument(
        "-q",
        "--quality",
        type=int,
        default=2,
        choices=range(1, 11),
        metavar="{1..10}",
        help="JPEG quality, 1=best..10=worst (default: 2).",
    )
    parser.add_argument(
        "-l",
        "--list",
        action="store_true",
        help="List the device's supported formats and sizes, then exit.",
    )
    args = parser.parse_args()

    if args.warmup < 0:
        parser.error("--warmup must be >= 0.")
    if args.size and not SIZE_RE.match(args.size):
        parser.error("--size must look like WIDTHxHEIGHT, e.g. 1280x720.")

    try:
        ffmpeg = find_ffmpeg()
        device = args.device or find_default_device(ffmpeg)
    except WebcamError as exc:
        sys.exit(str(exc))  # prints to stderr, exit code 1

    formats, _probe_stderr = probe_formats(ffmpeg, device)
    if args.list:
        print(f"{device}:")
        if not formats:
            print("  no capture formats reported")
        for fmt in formats:
            sizes = " ".join(fmt["sizes"]) or "(device default)"
            print(f"  {fmt['kind']:<10} {fmt['codec']:<10} {sizes}")
        return 0

    input_format = choose_input_format(formats, args.input_format)
    output = resolve_output(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)

    proc = grab_frame(
        ffmpeg,
        device,
        output,
        size=args.size,
        input_format=input_format,
        warmup=args.warmup,
        quality=args.quality,
    )

    # A requested size may not be supported by the device; retry once
    # with the device's default size before giving up.
    if proc.returncode != 0 and args.size:
        print(f"Note: capture at {args.size} failed, retrying with device default size.")
        proc = grab_frame(
            ffmpeg,
            device,
            output,
            size=None,
            input_format=input_format,
            warmup=args.warmup,
            quality=args.quality,
        )

    if proc.returncode != 0 or not output.exists():
        print(f"Error: capture failed on {device}.", file=sys.stderr)
        if proc.stderr:
            print(proc.stderr.strip(), file=sys.stderr)
        hints = explain_failure(proc.stderr or "")
        if hints:
            print("Possible causes:", file=sys.stderr)
            print(hints, file=sys.stderr)
        return 1

    size_note = args.size or "device default"
    print(
        f"Captured {output} from {device} "
        f"(format={input_format or 'default'}, size={size_note}, warmup={args.warmup})"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())