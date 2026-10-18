"""Low-rate YUV camera rail, using immutable frames from existing decoders.

render runs in a single worker and returns a snapshot. Only the event loop
publishes it. No secondary camera I/O takes place on the paced feeder.
"""

import time
from dataclasses import dataclass

import numpy as np
from PIL import Image, ImageDraw, ImageFont


@dataclass(frozen=True)
class Rail:
    active: str
    membership: tuple
    ids: tuple
    healthy: tuple
    planes: tuple
    rendered_at: float
    render_ms: float
    main_available: bool = True
    news: object = None
    main_label: object = None


def _font(size):
    try:
        return ImageFont.truetype(
            "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", size
        )
    except OSError:
        return ImageFont.load_default()


def _ui_planes(image):
    # Static UI only; live pixels stay in their original YUV color space.
    rgb = np.asarray(image, dtype=np.float32)
    r, g, b = rgb[..., 0], rgb[..., 1], rgb[..., 2]
    y = np.clip(
        np.rint(16 + 0.182586 * r + 0.614231 * g + 0.062007 * b), 16, 235
    ).astype("uint8")

    def chroma(x):
        h, w = x.shape
        return np.clip(
            np.rint(x.reshape(h // 2, 2, w // 2, 2).mean(axis=(1, 3))), 16, 240
        ).astype("uint8")

    return (
        y,
        chroma(128 - 0.100644 * r - 0.338572 * g + 0.439216 * b),
        chroma(128 + 0.439216 * r - 0.398942 * g - 0.040274 * b),
    )


def _planes(frame, width=1920, height=1080):
    if len(frame) != width * height * 3 // 2:
        raise ValueError("Unexpected YUV420P frame size")
    raw = np.frombuffer(frame, dtype=np.uint8)
    n = width * height
    return (
        raw[:n].reshape(height, width),
        raw[n : n + n // 4].reshape(height // 2, width // 2),
        raw[n + n // 4 :].reshape(height // 2, width // 2),
    )


class CameraSidebar:
    panel_x, panel_y, panel_w = 1550, 88, 370
    tile_x, first_y, step = 24, 44, 210
    tile_w, photo_h, label_h = 320, 180, 24

    def __init__(self, width, height):
        if (width, height) != (1920, 1080):
            raise ValueError("Camera sidebar requires 1920x1080")
        self._background_key = None
        self._background = None
        self._cache = None

    def render(self, entries, active):
        """Return a complete rail; never mutate the currently published rail."""
        started = time.perf_counter()
        membership = tuple((key, name) for key, name, _ in entries)
        others = [(key, name, frame) for key, name, frame in entries if key != active][
            :4
        ]
        if not others:
            return None
        key = tuple(
            (identity, name, frame is not None) for identity, name, frame in others
        )
        if key != self._background_key:
            height = self.first_y + len(others) * self.step
            image = Image.new("RGB", (self.panel_w, height), "#101923")
            draw = ImageDraw.Draw(image)
            draw.rectangle(
                (0, 0, self.panel_w - 1, height - 1), outline="#416775", width=2
            )
            draw.ellipse((16, 16, 24, 24), fill="#18c6ba")
            draw.text((34, 10), "OTRAS CÁMARAS", font=_font(17), fill="#e8f3f2")
            for j, (_, name, frame) in enumerate(others):
                x, y = self.tile_x, self.first_y + j * self.step
                draw.rectangle(
                    (
                        x - 2,
                        y - 2,
                        x + self.tile_w + 1,
                        y + self.photo_h + self.label_h,
                    ),
                    outline="#476976",
                    width=2,
                )
                draw.rectangle(
                    (
                        x,
                        y + self.photo_h,
                        x + self.tile_w - 1,
                        y + self.photo_h + self.label_h - 1,
                    ),
                    fill="#172b36",
                )
                draw.text(
                    (x + 8, y + self.photo_h + 2),
                    name[:30],
                    font=_font(15),
                    fill="#f2fbfb",
                )
                if frame is None:
                    draw.rectangle(
                        (x, y, x + self.tile_w - 1, y + self.photo_h - 1),
                        fill="#29404b",
                    )
                    draw.text(
                        (x + 95, y + 78), "SIN SEÑAL", font=_font(18), fill="#d6e2e6"
                    )
            self._background = _ui_planes(image)
            self._background_key = key
        planes = tuple(p.copy() for p in self._background)
        for j, (_, _, frame) in enumerate(others):
            if frame is None:
                continue
            for i, p in enumerate(_planes(frame)):
                factor = 1 if i == 0 else 2
                x = self.tile_x // factor
                y = (self.first_y + j * self.step) // factor
                # Existing Source already letterboxes to 16:9; no further crop.
                scaled = Image.fromarray(p).resize(
                    (self.tile_w // factor, self.photo_h // factor),
                    Image.Resampling.BILINEAR,
                )
                planes[i][
                    y : y + self.photo_h // factor, x : x + self.tile_w // factor
                ] = np.asarray(scaled)
        for p in planes:
            p.flags.writeable = False
        return Rail(
            active,
            membership,
            tuple(x[0] for x in others),
            tuple(x[2] is not None for x in others),
            planes,
            time.monotonic(),
            (time.perf_counter() - started) * 1000,
        )

    def apply(self, frame, rail):
        if rail is None:
            return frame
        # Most cameras deliver 15 FPS into a 30 FPS output: reuse the identical
        # composition until either the main frame or immutable rail changes.
        if self._cache and self._cache[0] is frame and self._cache[1] is rail:
            return self._cache[2]
        output = bytearray(frame)
        for i, (target, panel) in enumerate(zip(_planes(output), rail.planes)):
            factor = 1 if i == 0 else 2
            x = self.panel_x // factor
            y = self.panel_y // factor
            h, w = panel.shape
            target[y : y + h, x : x + w] = panel
        self._cache = (frame, rail, output)
        return output
