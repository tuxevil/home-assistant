"""Validated, installation-independent engine configuration."""

import json
from pathlib import Path
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

DEFAULTS = dict(
    rtsp_url="",
    destination_url="",
    music_directory="/share/stream_music",
    width=1920,
    height=1080,
    fps=15,
    bitrate_kbps=3000,
    threads=2,
    title="Live Studio",
    timezone="UTC",
    show_clock=True,
    ticker="",
    cta="Enjoy the view · Like and subscribe",
    cta_period=600,
    cta_duration=12,
)
TEXT_LIMITS = {"title": 100, "ticker": 1200, "cta": 200}
NUMBERS = {
    "width": (640, 3840),
    "height": (360, 2160),
    "fps": (5, 30),
    "bitrate_kbps": (500, 15000),
    "threads": (1, 8),
    "cta_period": (60, 7200),
    "cta_duration": (3, 60),
}


def clean_text(value, limit=300):
    if not isinstance(value, str):
        raise ValueError("Expected text")
    return " ".join(
        "".join(c for c in value if c.isprintable() or c.isspace()).split()
    )[:limit]


def validate(values, base=None):
    if not isinstance(values, dict) or values.keys() - DEFAULTS.keys():
        raise ValueError("Unknown configuration fields")
    result = {**DEFAULTS, **(base or {})}
    for key, value in values.items():
        if key in NUMBERS:
            lo, hi = NUMBERS[key]
            if type(value) is not int or not lo <= value <= hi:
                raise ValueError("Invalid " + key)
        elif key in TEXT_LIMITS:
            value = clean_text(value, TEXT_LIMITS[key])
        elif key == "show_clock":
            if type(value) is not bool:
                raise ValueError("Invalid show_clock")
        elif key == "timezone":
            if not isinstance(value, str):
                raise ValueError("Invalid timezone")
            try:
                ZoneInfo(value)
            except (ZoneInfoNotFoundError, ValueError):
                raise ValueError("Invalid timezone") from None
        elif key in ("rtsp_url", "destination_url"):
            if not isinstance(value, str):
                raise ValueError("Invalid URL")
            if value:
                parsed = urlsplit(value)
                schemes = ("rtsp", "rtsps") if key == "rtsp_url" else ("rtmp", "rtmps")
                if (
                    parsed.scheme not in schemes
                    or not parsed.hostname
                    or any(c.isspace() for c in value)
                ):
                    raise ValueError("Invalid " + key)
        elif key == "music_directory":
            if not isinstance(value, str) or not any(
                Path(value).resolve().is_relative_to(root)
                for root in (Path("/share"), Path("/media"))
            ):
                raise ValueError("Music must be under /share or /media")
        result[key] = value
    if result["width"] % 2 or result["height"] % 2:
        raise ValueError("Video dimensions must be even")
    if result["cta_duration"] >= result["cta_period"]:
        raise ValueError("CTA duration must be less than period")
    return result


def atomic_json(path, data):
    path = Path(path)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False))
    tmp.chmod(0o600)
    tmp.replace(path)
