"""Validated announcements; rasterize on the worker, scroll planar rows on feeder."""

from dataclasses import dataclass
import math
import re

import numpy as np
from PIL import Image, ImageDraw

from .sidebar import _font, _ui_planes

DEFAULT_NEWS = {"enabled": False, "speed_px_s": 25, "messages": []}


def validate_news(value):
    if not isinstance(value, dict) or set(value) - set(DEFAULT_NEWS):
        raise ValueError("Invalid vertical news configuration")
    result = {**DEFAULT_NEWS, **value}
    if type(result["enabled"]) is not bool:
        raise ValueError("Invalid news enabled flag")
    speed = result["speed_px_s"]
    if (
        type(speed) not in (int, float)
        or not math.isfinite(speed)
        or not 1 <= speed <= 100
    ):
        raise ValueError("News speed must be 1–100 px/s")
    messages = result["messages"]
    if not isinstance(messages, list) or len(messages) > 32:
        raise ValueError("Configure at most 32 announcements")
    clean, ids = [], set()
    for message in messages:
        if not isinstance(message, dict) or set(message) - {
            "id",
            "icon",
            "title",
            "subtitle",
            "enabled",
            "priority",
        }:
            raise ValueError("Invalid announcement")
        item = {"icon": "", "subtitle": "", "enabled": True, "priority": 0, **message}
        if (
            not isinstance(item.get("id"), str)
            or not re.fullmatch(r"[a-zA-Z0-9_-]{1,64}", item["id"])
            or item["id"] in ids
        ):
            raise ValueError("Announcement IDs must be unique")
        for key, limit in (("title", 200), ("subtitle", 800), ("icon", 24)):
            if not isinstance(item.get(key), str) or len(item[key]) > limit:
                raise ValueError("Invalid announcement text")
            item[key] = " ".join(item[key].split())
        if (
            not item["title"]
            or type(item["enabled"]) is not bool
            or type(item["priority"]) is not int
        ):
            raise ValueError("Invalid announcement fields")
        ids.add(item["id"])
        clean.append(item)
    result["messages"] = clean
    return result


def wrapped(draw, text, face, width):
    lines, line = [], ""
    for character in text:
        if line and draw.textlength(line + character, font=face) > width:
            lines.append(line.rstrip())
            line = ""
        line += character
    if line.strip():
        lines.append(line.strip())
    return lines


@dataclass(frozen=True)
class NewsStrip:
    planes: tuple
    height: int
    viewport: tuple
    speed: float


class VerticalNewsTicker:
    """No full-frame RGB conversion and no mutable shared render buffers."""

    def __init__(self):
        self.key = self.strip = None

    def prepare(self, config, viewport):
        messages = sorted(
            (m for m in config["messages"] if m["enabled"]), key=lambda m: m["priority"]
        )
        if not config["enabled"] or not messages:
            return None
        x, y, width, height = viewport
        key = (
            tuple(
                (m["id"], m["icon"], m["title"], m["subtitle"], m["priority"])
                for m in messages
            ),
            width,
            height,
        )
        if key != self.key:
            probe = ImageDraw.Draw(Image.new("RGB", (width, 2)))
            title_font, sub_font = _font(18), _font(14)
            prepared = []
            content_height = 0
            for m in messages:
                titles = wrapped(probe, m["title"], title_font, width - 52)
                subtitles = wrapped(probe, m["subtitle"], sub_font, width - 52)
                card_height = 28 + 25 * len(titles) + 21 * len(subtitles)
                card_height += card_height % 2
                prepared.append((m, titles, subtitles, card_height))
                content_height += card_height + 12
            # Repeat short playlists to fill tall viewports without a long empty pause.
            repeats = max(1, math.ceil(height / content_height))
            prepared *= repeats
            total = content_height * repeats + 24
            total += total % 2
            image = Image.new("RGB", (width, total), "#101f26")
            draw = ImageDraw.Draw(image)
            top = 0
            for m, titles, subtitles, card_height in prepared:
                draw.rounded_rectangle(
                    (0, top, width - 1, top + card_height - 1), radius=6, fill="#152a34"
                )
                draw.line(
                    (0, top + 12, 0, top + card_height - 12), fill="#39d4c3", width=3
                )
                # Portable vector glyph; never rely on emoji fonts.
                draw.ellipse((12, top + 17, 24, top + 29), outline="#39d4c3", width=2)
                if m["icon"] == "youtube":
                    draw.polygon(
                        ((15, top + 19), (15, top + 27), (22, top + 23)), fill="#39d4c3"
                    )
                yy = top + 12
                for text in titles:
                    draw.text((36, yy), text, font=title_font, fill="#edf5f3")
                    yy += 25
                for text in subtitles:
                    draw.text((36, yy), text, font=sub_font, fill="#93aeb4")
                    yy += 21
                top += card_height + 12
            planes = _ui_planes(image)
            for p in planes:
                p.flags.writeable = False
            self.key, self.strip = key, (planes, total)
        return NewsStrip(self.strip[0], self.strip[1], viewport, config["speed_px_s"])

    @staticmethod
    def blit(targets, strip, offset):
        x, y, width, height = strip.viewport
        position = int(offset) % strip.height
        for i, (target, source) in enumerate(zip(targets, strip.planes)):
            factor = 1 if i == 0 else 2
            start = position // factor
            rows = height // factor
            first = min(rows, source.shape[0] - start)
            dst = target[
                y // factor : (y + height) // factor,
                x // factor : (x + width) // factor,
            ]
            dst[:first] = source[start : start + first]
            if first < rows:
                dst[first:] = source[: rows - first]
