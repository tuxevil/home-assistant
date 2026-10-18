"""Complete broadcast canvas. Live pixels remain planar YUV throughout.

The worker builds immutable chrome/secondary views; the feeder scales only a new
main frame, caching repeated source frames independently of the one-second HUD.
No decoder, connection, encoder, clock or output process is created here.
"""

import ctypes
import ctypes.util
import re
import time
from datetime import datetime
from zoneinfo import ZoneInfo

import numpy as np
from PIL import Image, ImageDraw, ImageFont

from .sidebar import Rail, _font, _planes, _ui_planes
from .news import VerticalNewsTicker, DEFAULT_NEWS

BG = "#091217"
PANEL = "#101f26"
LINE = "#29434b"
INK = "#edf5f3"
MUTED = "#93aeb4"
ACCENT = "#39d4c3"


def font(size, bold=False):
    if bold:
        return _font(size)
    try:
        return ImageFont.truetype(
            "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", size
        )
    except OSError:
        return _font(size)


def fitted(draw, text, size, width, bold=False):
    face = font(size, bold)
    while text and draw.textlength(text, font=face) > width:
        text = text[:-2].rstrip() + "…" if len(text) > 2 else ""
    return text, face


def telemetry(text):
    """Read only published HA readings with unambiguous labels/units.

    Missing/stale input stays absent. Never derive weather from camera images or
    substitute a remembered reading. The publisher owns the freshness timeout.
    """
    result = {}
    for part in text.split("·"):
        match = re.search(
            r":\s*(-?\d+(?:[.,]\d+)?)\s*(°C|°F|%|km/h|m/s|W/m²|W/m2)\s*$", part
        )
        if not match:
            continue
        number, unit = match.groups()
        name = part[: match.start()].casefold()
        key = None
        if unit in ("°C", "°F") and any(x in name for x in ("temp", "temperature")):
            key = "temperature"
        elif unit == "%" and any(x in name for x in ("hum", "humidity")):
            key = "humidity"
        elif (
            unit in ("km/h", "m/s")
            and any(x in name for x in ("wind", "viento"))
            and "gust" not in name
        ):
            key = "wind"
        elif unit in ("W/m²", "W/m2"):
            key = "irradiance"
        if key and key not in result:
            value = float(number.replace(",", "."))
            display = f"{value:g}"
            result[key] = (
                display
                + (" " if unit not in ("°C", "°F", "%") else "")
                + unit.replace("m2", "m²")
            )
    return result


def icon(draw, kind, x, y):
    c = ACCENT
    if kind == "temperature":
        draw.rounded_rectangle((x + 8, y, x + 16, y + 29), radius=4, outline=c, width=2)
        draw.ellipse((x + 4, y + 22, x + 20, y + 38), outline=c, width=2)
        draw.line((x + 12, y + 10, x + 12, y + 30), fill=c, width=3)
    elif kind == "humidity":
        draw.line(
            [
                (x + 12, y),
                (x + 2, y + 22),
                (x + 2, y + 30),
                (x + 7, y + 36),
                (x + 17, y + 36),
                (x + 22, y + 30),
                (x + 22, y + 22),
                (x + 12, y),
            ],
            fill=c,
            width=2,
        )
    elif kind == "wind":
        for j, width in enumerate((27, 35, 21)):
            yy = y + 8 + j * 11
            draw.line((x, yy, x + width, yy), fill=c, width=2)
            draw.arc(
                (x + width - 8, yy - 8, x + width + 4, yy + 4), 270, 90, fill=c, width=2
            )
    else:
        draw.ellipse((x + 7, y + 10, x + 25, y + 28), outline=c, width=2)
        for dx, dy, ex, ey in (
            (16, 0, 16, 6),
            (16, 32, 16, 38),
            (-3, 19, 3, 19),
            (29, 19, 35, 19),
            (2, 4, 6, 8),
            (26, 30, 30, 34),
            (2, 34, 6, 30),
            (26, 8, 30, 4),
        ):
            draw.line((x + dx, y + dy, x + ex, y + ey), fill=c, width=2)


class PlanarScaler:
    """FFmpeg's installed SIMD scaler, single-threaded, no new FFmpeg process.

    A portable Pillow fallback keeps optional deployments functional. Buffers are
    private scratch: apply copies them into an owned output before the next call.
    """

    def __init__(self, width, height):
        self.width, self.height = width, height
        self.lib = self.ctx = None
        try:
            lib = ctypes.CDLL(ctypes.util.find_library("swscale") or "libswscale.so")
            ptr = ctypes.POINTER(ctypes.c_uint8)
            lib.sws_getContext.argtypes = [ctypes.c_int] * 7 + [ctypes.c_void_p] * 3
            lib.sws_getContext.restype = ctypes.c_void_p
            lib.sws_scale.argtypes = [
                ctypes.c_void_p,
                ctypes.POINTER(ptr),
                ctypes.POINTER(ctypes.c_int),
                ctypes.c_int,
                ctypes.c_int,
                ctypes.POINTER(ptr),
                ctypes.POINTER(ctypes.c_int),
            ]
            lib.sws_scale.restype = ctypes.c_int
            lib.sws_freeContext.argtypes = [ctypes.c_void_p]
            # AV_PIX_FMT_YUV420P=0; SWS_BILINEAR=2, no RGB conversion.
            ctx = lib.sws_getContext(
                1920, 1080, 0, width, height, 0, 2, None, None, None
            )
            if not ctx:
                raise RuntimeError("Scaler allocation failed")
            self.lib, self.ctx = lib, ctx
            self.buffer = np.empty(width * height * 3 // 2 + 64, dtype=np.uint8)
            self.views = _planes(
                memoryview(self.buffer)[: width * height * 3 // 2], width, height
            )
        except (OSError, AttributeError, RuntimeError):
            self.lib = self.ctx = None

    def scale(self, frame):
        if self.ctx:
            source = _planes(frame)
            ptr = ctypes.POINTER(ctypes.c_uint8)
            src = (ptr * 4)(*(p.ctypes.data_as(ptr) for p in source), ptr())
            dst = (ptr * 4)(*(p.ctypes.data_as(ptr) for p in self.views), ptr())
            source_stride = (ctypes.c_int * 4)(1920, 960, 960, 0)
            target_stride = (ctypes.c_int * 4)(
                self.width, self.width // 2, self.width // 2, 0
            )
            rows = self.lib.sws_scale(
                self.ctx, src, source_stride, 0, 1080, dst, target_stride
            )
            if rows != self.height:
                raise ValueError("Incomplete scaled frame")
            return self.views
        return tuple(
            np.asarray(
                Image.fromarray(p).resize(
                    (
                        self.width // (1 if i == 0 else 2),
                        self.height // (1 if i == 0 else 2),
                    ),
                    Image.Resampling.BILINEAR,
                )
            )
            for i, p in enumerate(_planes(frame))
        )

    def close(self):
        if self.ctx:
            self.lib.sws_freeContext(self.ctx)
            self.ctx = None

    def __del__(self):
        self.close()


class StudioComposer:
    """Full-height rail. Worker owns UI; feeder owns scale/cache and ticker phase."""

    def __init__(self, width, height, settings=None):
        if (width, height) != (1920, 1080):
            raise ValueError("Broadcast design requires 1920x1080")
        self.settings = dict(settings or {})
        self.side_w = self.settings.get("sidebar_width", 384)
        self.side_x = 1920 - self.side_w
        self.main_x, self.main_y = 12, 76
        self.main_w = self.side_x - 24
        # Fit within 1512x850 without distorting 16:9. Even letterbox margins.
        units = min(self.main_w // 32, 850 // 18)
        self.main_w, self.main_h = units * 32, units * 18
        self.main_x += ((self.side_x - 24 - self.main_w) // 4) * 2
        self.main_y += ((850 - self.main_h) // 4) * 2
        self.scaler = PlanarScaler(self.main_w, self.main_h)
        self.news = VerticalNewsTicker()
        self._chrome_key = self._chrome = None
        self._thumb_key = self._thumbs = None
        self._thumb_at = 0
        self._scaled_frame = self._scaled = None
        self._cache = None
        self._cache_at = 0
        self._footer_key = self._footer = None
        self._news_at = None
        self._news_offset = 0.0
        self._news_speed = 0.0
        self._main_label = None

    def _cards(self, count):
        w = self.side_w - 24
        h = ((w * 9 + 15) // 16 + 1) // 2 * 2
        return [(self.side_x + 12, 64 + j * (h + 8), w, h) for j in range(count)]

    def render(self, entries, active, context=None):
        started = time.perf_counter()
        context = context or {}
        settings = context.get("settings", self.settings)
        membership = tuple((key, name) for key, name, _ in entries)
        others = [e for e in entries if e[0] != active][:4]
        cards = self._cards(len(others))
        selected = next(
            (e for e in entries if e[0] == active), (active, "Cámara principal", None)
        )
        thumb_key = (active, tuple((i, n, f is not None) for i, n, f in others))
        if (
            thumb_key != self._thumb_key
            or time.monotonic() - self._thumb_at
            >= settings.get("sidebar_refresh_seconds", 3)
        ):
            thumbs = []
            for (_, name, frame), (_, _, w, h) in zip(others, cards):
                # Labels are part of a small pre-rendered tile, never extra rows.
                probe = ImageDraw.Draw(Image.new("RGB", (2, 2)))
                label_w = min(
                    w - 16,
                    (int(probe.textlength(name, font=font(16, True))) + 44) // 2 * 2,
                )
                label = Image.new("RGB", (label_w, 30), "#0d1a25")
                d = ImageDraw.Draw(label)
                text, face = fitted(d, name, 16, label_w - 32, True)
                d.ellipse((10, 11, 17, 18), fill=ACCENT if frame is not None else MUTED)
                d.text(
                    (26, 4), text, font=face, fill=INK if frame is not None else MUTED
                )
                if frame is None:
                    tile = Image.new("RGB", (w, h), PANEL)
                    draw = ImageDraw.Draw(tile)
                    draw.text(
                        (w // 2 - 53, h // 2 - 14),
                        "SIN SEÑAL",
                        font=font(16, True),
                        fill=MUTED,
                    )
                    views = tuple(p.copy() for p in _ui_planes(tile))
                else:
                    units = min(w // 32, h // 18)
                    fw, fh = units * 32, units * 18
                    dx, dy = ((w - fw) // 4) * 2, ((h - fh) // 4) * 2
                    views = []
                    for i, p in enumerate(_planes(frame)):
                        factor = 1 if i == 0 else 2
                        tile = np.full(
                            (h // factor, w // factor),
                            16 if i == 0 else 128,
                            dtype=np.uint8,
                        )
                        scaled = np.asarray(
                            Image.fromarray(p).resize(
                                (fw // factor, fh // factor), Image.Resampling.BILINEAR
                            )
                        )
                        tile[
                            dy // factor : (dy + fh) // factor,
                            dx // factor : (dx + fw) // factor,
                        ] = scaled
                        views.append(tile)
                    views = tuple(views)
                for i, (view, band) in enumerate(zip(views, _ui_planes(label))):
                    factor = 1 if i == 0 else 2
                    view[
                        4 // factor : 34 // factor,
                        8 // factor : (8 + label_w) // factor,
                    ] = band
                thumbs.append(views)
            self._thumb_key, self._thumbs, self._thumb_at = (
                thumb_key,
                thumbs,
                time.monotonic(),
            )
        key = (thumb_key, selected[1], selected[2] is not None)
        if key != self._chrome_key:
            image = Image.new("RGB", (1920, 1080), BG)
            draw = ImageDraw.Draw(image)
            draw.rectangle((0, 0, self.side_x - 1, 63), fill="#0d1a25")
            draw.rectangle((self.side_x, 0, 1919, 1079), fill=PANEL)
            draw.line((self.side_x, 0, self.side_x, 1079), fill=LINE, width=2)
            draw.line(
                ((18, 45), (37, 20), (49, 34), (62, 17), (84, 45)), fill=ACCENT, width=2
            )
            brand, face = fitted(
                draw, settings.get("broadcast_brand", "LIVE STUDIO"), 25, 210, True
            )
            draw.text((100, 15), brand, font=face, fill=INK)
            draw.line((315, 16, 315, 48), fill=LINE)
            draw.text(
                (334, 22),
                settings.get("broadcast_location", ""),
                font=font(17),
                fill=INK,
            )
            draw.line((700, 16, 700, 48), fill=LINE)
            draw.text(
                (724, 25),
                settings.get("broadcast_label", "NATURALEZA EN DIRECTO"),
                font=font(12),
                fill=MUTED,
            )
            draw.ellipse((self.side_x - 181, 26, self.side_x - 171, 36), fill="#f25259")
            draw.text(
                (self.side_x - 157, 21), "EN VIVO 24/7", font=font(17, True), fill=INK
            )
            draw.ellipse((self.side_x + 18, 23, self.side_x + 26, 31), fill=ACCENT)
            draw.text(
                (self.side_x + 40, 17), "OTRAS CÁMARAS", font=font(17, True), fill=INK
            )
            draw.line((self.side_x + 12, 54, 1908, 54), fill=LINE)
            draw.rectangle((10, 74, self.side_x - 11, 927), outline=LINE, width=2)
            if selected[2] is None:
                draw.text(
                    (self.side_x // 2 - 72, 460),
                    "SIN SEÑAL",
                    font=font(27, True),
                    fill=MUTED,
                )
            for x, y, w, h in cards:
                draw.rectangle(
                    (x - 2, y - 2, x + w + 1, y + h + 1), outline=LINE, width=2
                )
            self._chrome, self._chrome_key = _ui_planes(image), key
            label = Image.new("RGB", (300, 74), "#0d1a25")
            d = ImageDraw.Draw(label)
            d.ellipse(
                (12, 12, 20, 20), fill=ACCENT if selected[2] is not None else MUTED
            )
            d.text((32, 8), "CÁMARA ACTUAL", font=font(12, True), fill=MUTED)
            text, face = fitted(d, selected[1].upper(), 21, 276, True)
            d.text((12, 34), text, font=face, fill=INK)
            self._main_label = _ui_planes(label)
        weather = telemetry(context.get("sensor_text", ""))
        footer_key = (
            tuple(weather.items()),
            settings.get("weather_footer_enabled", True),
        )
        if footer_key != self._footer_key:
            footer = Image.new("RGB", (self.side_x - 24, 128), BG)
            draw = ImageDraw.Draw(footer)
            if settings.get("weather_footer_enabled", True):
                draw.line((0, 0, self.side_x - 25, 0), fill=LINE, width=1)
                for j, (kind, label) in enumerate(
                    (
                        ("temperature", "TEMPERATURA"),
                        ("humidity", "HUMEDAD"),
                        ("wind", "VIENTO"),
                        ("irradiance", "IRRADIANCIA"),
                    )
                ):
                    x = j * ((self.side_x - 24) // 4)
                    if j:
                        draw.line((x, 24, x, 106), fill=LINE)
                    icon(draw, kind, x + 20, 41)
                    value = weather.get(kind, "—")
                    text, face = fitted(
                        draw, value, 29, (self.side_x - 24) // 4 - 90, True
                    )
                    draw.text(
                        (x + 78, 28),
                        text,
                        font=face,
                        fill=INK if kind in weather else MUTED,
                    )
                    draw.text((x + 78, 76), label, font=font(12), fill=MUTED)
            self._footer, self._footer_key = _ui_planes(footer), footer_key
        planes = tuple(p.copy() for p in self._chrome)
        for i, (p, footer) in enumerate(zip(planes, self._footer)):
            factor = 1 if i == 0 else 2
            p[
                940 // factor : 1068 // factor,
                12 // factor : (self.side_x - 12) // factor,
            ] = footer
        for views, (x, y, w, h) in zip(self._thumbs, cards):
            for i, (p, view) in enumerate(zip(planes, views)):
                factor = 1 if i == 0 else 2
                p[y // factor : (y + h) // factor, x // factor : (x + w) // factor] = (
                    view
                )
        bottom = cards[-1][1] + cards[-1][3] if cards else 64
        ticker_y = bottom + 12
        ticker_y += ticker_y % 2
        # Internal heading remains fixed; only the content viewport scrolls.
        news_config = settings.get("vertical_news", DEFAULT_NEWS)
        strip = self.news.prepare(
            news_config,
            (self.side_x + 12, ticker_y + 30, self.side_w - 24, 1068 - ticker_y - 30),
        )
        if strip:
            heading = Image.new("RGB", (self.side_w - 24, 30), PANEL)
            d = ImageDraw.Draw(heading)
            d.line((0, 0, self.side_w - 25, 0), fill=LINE)
            d.text((0, 7), "NOVEDADES", font=font(13, True), fill=ACCENT)
            for i, (p, view) in enumerate(zip(planes, _ui_planes(heading))):
                factor = 1 if i == 0 else 2
                p[
                    ticker_y // factor : (ticker_y + 30) // factor,
                    (self.side_x + 12) // factor : 1908 // factor,
                ] = view
        for p in planes:
            p.flags.writeable = False
        return Rail(
            active,
            membership,
            tuple(e[0] for e in others),
            tuple(e[2] is not None for e in others),
            planes,
            time.monotonic(),
            (time.perf_counter() - started) * 1000,
            selected[2] is not None,
            strip,
            self._main_label if settings.get("show_camera_name", True) else None,
        )

    def transition_frame(self, original):
        return (
            self._cache[2]
            if self._cache and time.monotonic() - self._cache_at < 1.5
            else original
        )

    def apply(self, frame, rail):
        if rail is None:
            return frame
        now = time.monotonic()
        if self._news_at is not None:
            self._news_offset += max(0, now - self._news_at) * self._news_speed
        self._news_at = now
        self._news_speed = rail.news.speed if rail.news else 0
        offset = int(self._news_offset) % rail.news.height if rail.news else None
        if (
            self._cache
            and self._cache[0] is frame
            and self._cache[1] is rail
            and self._cache[3] == offset
        ):
            return self._cache[2]
        if rail.main_available and self._scaled_frame is not frame:
            self._scaled = self.scaler.scale(frame)
            self._scaled_frame = frame
        # Ownership must span StreamWriter.drain(): never mutate a previous output.
        output = bytearray(3110400)
        targets = _planes(output)
        for i, (target, chrome, main) in enumerate(
            zip(targets, rail.planes, self._scaled or (None, None, None))
        ):
            target[:] = chrome
            factor = 1 if i == 0 else 2
            if rail.main_available:
                target[
                    self.main_y // factor : (self.main_y + self.main_h) // factor,
                    self.main_x // factor : (self.main_x + self.main_w) // factor,
                ] = main
            if rail.main_label:
                x, y = self.main_x + 16, self.main_y + 16
                target[
                    y // factor : (y + 74) // factor, x // factor : (x + 300) // factor
                ] = rail.main_label[i]
        if rail.news:
            VerticalNewsTicker.blit(targets, rail.news, offset)
        self._cache = (frame, rail, output, offset)
        self._cache_at = now
        return output
