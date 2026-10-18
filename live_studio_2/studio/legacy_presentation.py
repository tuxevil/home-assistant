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
    main_x, main_y, main_w, main_h = 24, 130, 1472, 828

    def __init__(self, width, height, settings=None):
        if (width, height) != (1920, 1080):
            raise ValueError("Broadcast design requires 1920x1080")
        self.settings = dict(settings or {})
        self._chrome_key = None
        self._chrome = None
        self._thumb_key = None
        self._thumbs = None
        self._thumb_at = 0
        self.scaler = PlanarScaler(self.main_w, self.main_h)
        self._scaled_frame = None
        self._scaled = None
        self._cache = None
        self._cache_at = 0
        self._footer_key = None
        self._footer = None

    def _cards(self, count):
        # Fixed 16:9 in both variants; the three-camera variant gets larger views.
        if count == 3:
            return [(1532, 142 + j * 278, 352, 198) for j in range(count)]
        if count <= 2:
            return [(1532, 228 + j * 302, 352, 198) for j in range(count)]
        return [(1548, 130 + j * 208, 320, 180) for j in range(count)]

    def render(self, entries, active, context=None):
        start = time.perf_counter()
        context = context or {}
        membership = tuple((key, name) for key, name, _ in entries)
        others = [e for e in entries if e[0] != active][:4]
        cards = self._cards(len(others))
        selected = next(
            (e for e in entries if e[0] == active), (active, "Cámara principal", None)
        )
        now = datetime.now(
            ZoneInfo(context.get("timezone", self.settings.get("timezone", "UTC")))
        )
        weather = telemetry(context.get("sensor_text", ""))
        # Health/name transitions refresh immediately; normal thumbnails keep 3s.
        thumb_key = (active, tuple((i, n, f is not None) for i, n, f in others))
        if (
            thumb_key != self._thumb_key
            or time.monotonic() - self._thumb_at
            >= self.settings.get("sidebar_refresh_seconds", 3)
        ):
            thumbs = []
            for (_, _, frame), (x, y, w, h) in zip(others, cards):
                views = (
                    None
                    if frame is None
                    else tuple(
                        np.asarray(
                            Image.fromarray(p).resize(
                                (w // (1 if i == 0 else 2), h // (1 if i == 0 else 2)),
                                Image.Resampling.BILINEAR,
                            )
                        ).copy()
                        for i, p in enumerate(_planes(frame))
                    )
                )
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
            draw.rectangle((0, 0, 1919, 82), fill="#0d1a21")
            draw.line((24, 83, 1896, 83), fill=LINE, width=1)
            draw.line(
                [(28, 57), (48, 31), (61, 44), (80, 22), (106, 58)], fill=INK, width=2
            )
            draw.line(
                [(48, 57), (68, 33), (80, 46), (90, 35), (112, 57)], fill=MUTED, width=2
            )
            brand, face = fitted(
                draw, self.settings.get("broadcast_brand", "LIVE STUDIO"), 29, 202, True
            )
            draw.text((136, 25), brand, font=face, fill=INK)
            draw.line((355, 25, 355, 60), fill=LINE, width=1)
            location, face = fitted(
                draw, self.settings.get("broadcast_location", ""), 19, 650
            )
            draw.text((382, 31), location, font=face, fill=MUTED)
            label = self.settings.get("broadcast_label", "NATURALEZA EN DIRECTO")
            draw.text((1090, 34), label, font=font(14), fill=MUTED)
            draw.ellipse((1664, 34, 1676, 46), fill="#f25259")
            draw.text((1690, 29), "EN VIVO 24/7", font=font(19, True), fill=INK)
            name, face = fitted(draw, selected[1].upper(), 22, 590, True)
            draw.ellipse(
                (25, 106, 33, 114), fill=ACCENT if selected[2] is not None else MUTED
            )
            draw.text((46, 94), name, font=face, fill=INK)
            draw.text((1271, 99), "CÁMARA PRINCIPAL", font=font(13), fill=MUTED)
            draw.text((1548, 99), "OTRAS PERSPECTIVAS", font=font(13, True), fill=MUTED)
            draw.rectangle((22, 128, 1497, 959), outline=LINE, width=2)
            # Main matte becomes entirely covered by the scaled 16:9 frame.
            draw.rectangle((24, 130, 1495, 957), fill=PANEL)
            if selected[2] is None:
                draw.text((630, 495), "SIN SEÑAL", font=font(27, True), fill=MUTED)
                draw.text((608, 538), "Reconectando cámara", font=font(17), fill=MUTED)
            for (identity, name, frame), (x, y, w, h) in zip(others, cards):
                draw.rectangle(
                    (x - 1, y - 1, x + w, y + h + 22), fill=PANEL, outline=LINE, width=1
                )
                draw.line(
                    (x, y + h + 1, x + 3, y + h + 20),
                    fill=ACCENT if frame is not None else LINE,
                    width=3,
                )
                text, face = fitted(draw, name, 16, w - 29, True)
                draw.text(
                    (x + 13, y + h + 4),
                    text,
                    font=face,
                    fill=INK if frame is not None else MUTED,
                )
                if frame is None:
                    draw.text(
                        (x + (w - 94) // 2, y + h // 2 - 10),
                        "SIN SEÑAL",
                        font=font(15, True),
                        fill=MUTED,
                    )
            if len(others) <= 2:
                draw.text((1548, 824), label, font=font(17, True), fill=INK)
                draw.text(
                    (1548, 858),
                    "OTRAS MIRADAS · MISMO LUGAR",
                    font=font(12),
                    fill=MUTED,
                )
                draw.line((1548, 892, 1868, 892), fill=LINE, width=1)
            self._chrome = _ui_planes(image)
            self._chrome_key = key
        footer_key = (now.strftime("%Y-%m-%d %H:%M:%S"), tuple(weather.items()))
        if footer_key != self._footer_key:
            footer = Image.new("RGB", (1920, 98), BG)
            draw = ImageDraw.Draw(footer)
            draw.line((24, 0, 1896, 0), fill=LINE, width=1)
            draw.line((24, 0, 150, 0), fill=ACCENT, width=2)
            draw.text((28, 11), now.strftime("%H:%M:%S"), font=font(35, True), fill=INK)
            draw.text((30, 55), now.strftime("%d / %m / %Y"), font=font(14), fill=MUTED)
            for j, (kind, label) in enumerate(
                (
                    ("temperature", "TEMPERATURA"),
                    ("humidity", "HUMEDAD"),
                    ("wind", "VIENTO"),
                    ("irradiance", "IRRADIANCIA"),
                )
            ):
                x = 336 + j * 384
                draw.line((x - 26, 21, x - 26, 76), fill=LINE, width=1)
                icon(draw, kind, x, 26)
                value = weather.get(kind, "—")
                draw.text(
                    (x + 56, 16),
                    value,
                    font=font(27, True),
                    fill=INK if kind in weather else MUTED,
                )
                draw.text((x + 56, 56), label, font=font(12), fill=MUTED)
            self._footer = _ui_planes(footer)
            self._footer_key = footer_key
        planes = tuple(p.copy() for p in self._chrome)
        for i, (p, hud) in enumerate(zip(planes, self._footer)):
            f = 1 if i == 0 else 2
            p[982 // f :] = hud
        for views, (x, y, w, h) in zip(self._thumbs, cards):
            if views:
                for i, (p, view) in enumerate(zip(planes, views)):
                    f = 1 if i == 0 else 2
                    p[y // f : (y + h) // f, x // f : (x + w) // f] = view
        # Optional existing CTA/ticker uses a reserved main caption, not loose HUD.
        caption = context.get("cta") or context.get("ticker")
        if caption:
            strip = Image.new("RGB", (550, 32), BG)
            d = ImageDraw.Draw(strip)
            text, face = fitted(d, caption, 14, 530)
            d.text((4, 6), text, font=face, fill=MUTED)
            for i, (p, view) in enumerate(zip(planes, _ui_planes(strip))):
                f = 1 if i == 0 else 2
                p[92 // f : 124 // f, 650 // f : 1200 // f] = view
        for p in planes:
            p.flags.writeable = False
        return Rail(
            active,
            membership,
            tuple(e[0] for e in others),
            tuple(e[2] is not None for e in others),
            planes,
            time.monotonic(),
            (time.perf_counter() - start) * 1000,
            selected[2] is not None,
        )

    def transition_frame(self, original):
        # Hold the previous complete scene briefly while the worker builds the
        # new membership. Never flash full-screen or mix new main/old thumbnails.
        return (
            self._cache[2]
            if self._cache and time.monotonic() - self._cache_at < 1.5
            else original
        )

    def apply(self, frame, rail):
        if rail is None:
            return frame
        if self._cache and self._cache[0] is frame and self._cache[1] is rail:
            return self._cache[2]
        if rail.main_available and self._scaled_frame is not frame:
            self._scaled = self.scaler.scale(frame)
            self._scaled_frame = frame
        output = bytearray(3110400)
        for i, (target, chrome, main) in enumerate(
            zip(_planes(output), rail.planes, self._scaled or (None, None, None))
        ):
            target[:] = chrome
            f = 1 if i == 0 else 2
            if rail.main_available:
                target[
                    self.main_y // f : (self.main_y + self.main_h) // f,
                    self.main_x // f : (self.main_x + self.main_w) // f,
                ] = main
        self._cache = (frame, rail, output)
        self._cache_at = time.monotonic()
        return output
