"""Validated, installation-independent engine configuration."""

import json
import os
import re
from pathlib import Path
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

DEFAULTS = dict(
    rtsp_url="",
    sources=[],
    preferred_camera="",
    minimum_margin=10,
    day_bonus=5,
    minimum_dwell=1200,
    confirmations=2,
    comparison_interval=600,
    show_camera_name=True,
    no_signal_text="No camera signal · Reconnecting",
    destination_url="",
    music_directory="/share/stream_music",
    width=1920,
    height=1080,
    fps=15,
    video_encoder="cpu",
    video_decoder="cpu",
    vaapi_device="",
    source_buffer_ms=250,
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
TEXT_LIMITS = {"title": 100, "ticker": 1200, "cta": 200, "no_signal_text": 150}
NUMBERS = {
    "minimum_margin": (1, 30),
    "day_bonus": (0, 15),
    "minimum_dwell": (0, 7200),
    "confirmations": (1, 5),
    "comparison_interval": (60, 3600),
    "width": (640, 3840),
    "height": (360, 2160),
    "fps": (5, 30),
    "source_buffer_ms": (0, 2000),
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


def validate_sources(values):
    if not isinstance(values, list) or len(values) > 8:
        raise ValueError("Configure at most eight cameras")
    result = []
    ids = set()
    names = set()
    for source in values:
        if not isinstance(source, dict) or source.keys() - {
            "id",
            "name",
            "rtsp_url",
            "camera_entity",
            "description",
        }:
            raise ValueError("Invalid camera")
        identity = source.get("id")
        name = clean_text(source.get("name", ""), 64)
        url = source.get("rtsp_url")
        if (
            not isinstance(identity, str)
            or not re.fullmatch(r"[a-z][a-z0-9_]{0,47}", identity)
            or identity in ids
        ):
            raise ValueError("Invalid camera ID")
        if (
            not name
            or name.casefold() in names
            or name.casefold() in ("automatic", "automático", "manual")
        ):
            raise ValueError("Camera names must be unique")
        if not isinstance(url, str) or not url or any(c.isspace() for c in url):
            raise ValueError("Invalid camera URL")
        parsed = urlsplit(url)
        if parsed.scheme not in ("rtsp", "rtsps") or not parsed.hostname:
            raise ValueError("Invalid camera URL")
        entity = source.get("camera_entity", "")
        if not isinstance(entity, str) or (
            entity and not re.fullmatch(r"camera\.[a-z0-9_]+", entity)
        ):
            raise ValueError("Invalid camera entity")
        result.append(
            dict(
                id=identity,
                name=name,
                rtsp_url=url,
                camera_entity=entity,
                description=clean_text(source.get("description", ""), 800),
            )
        )
        ids.add(identity)
        names.add(name.casefold())
    return result


def validate(values, base=None):
    if not isinstance(values, dict) or values.keys() - DEFAULTS.keys():
        raise ValueError("Unknown configuration fields")
    result = {**DEFAULTS, **(base or {})}
    for key, value in values.items():
        if key == "sources":
            value = validate_sources(value)
        elif key in ("video_encoder", "video_decoder"):
            if value not in ("cpu", "vaapi", "auto"):
                raise ValueError("Invalid video acceleration")
        elif key == "vaapi_device":
            if not isinstance(value, str) or (
                value
                and not re.fullmatch(
                    r"/dev/dri/(renderD[0-9]+|by-path/[A-Za-z0-9:._-]+-render)", value
                )
            ):
                raise ValueError("Invalid render device")
        elif key == "preferred_camera":
            if not isinstance(value, str):
                raise ValueError("Invalid preferred camera")
        elif key in NUMBERS:
            lo, hi = NUMBERS[key]
            if type(value) is not int or not lo <= value <= hi:
                raise ValueError("Invalid " + key)
        elif key in TEXT_LIMITS:
            value = clean_text(value, TEXT_LIMITS[key])
        elif key in ("show_clock", "show_camera_name"):
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
                for root in [
                    Path(x).resolve()
                    for x in os.environ.get(
                        "STUDIO_MUSIC_ROOTS", "/share:/media"
                    ).split(os.pathsep)
                    if x and Path(x).is_absolute()
                ]
            ):
                raise ValueError("Music must be under an allowed music root")
        result[key] = value
    # Migration from the original one-camera configuration is lossless.
    if "rtsp_url" in values and "sources" not in values:
        if result["sources"]:
            result["sources"] = [
                dict(x, rtsp_url=result["rtsp_url"]) if i == 0 else dict(x)
                for i, x in enumerate(result["sources"])
            ]
        elif result["rtsp_url"]:
            result["sources"] = [
                dict(
                    id="camera_1",
                    name="Camera 1",
                    rtsp_url=result["rtsp_url"],
                    camera_entity="",
                    description="",
                )
            ]
    result["sources"] = validate_sources(result["sources"])
    result["rtsp_url"] = result["sources"][0]["rtsp_url"] if result["sources"] else ""
    ids = [x["id"] for x in result["sources"]]
    if result["preferred_camera"] not in ids:
        result["preferred_camera"] = ids[0] if ids else ""
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
