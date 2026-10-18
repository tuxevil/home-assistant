"""Ticker clipping, dynamics, planar ownership and per-live isolation."""

import unittest
from unittest.mock import patch
import numpy as np
from studio.news import validate_news, VerticalNewsTicker
from studio.presentation import StudioComposer
from studio.sidebar import _planes
from test_sidebar import frame, entries

NEWS = {
    "enabled": True,
    "speed_px_s": 25,
    "messages": [
        {
            "id": "a",
            "title": "Noticias desde Pallatanga",
            "subtitle": "Texto amplio para comprobar el ajuste de línea sin invadir otras tarjetas",
        },
        {"id": "b", "title": "Naturaleza y tecnología", "subtitle": "En directo"},
    ],
}


class NewsTests(unittest.TestCase):
    def test_rejects_ambiguous_and_unbounded_configuration(self):
        for patch_ in (
            {"enabled": 1},
            {"speed_px_s": float("nan")},
            {"speed_px_s": 0},
            {"messages": [{"id": "a", "title": ""}]},
            {"messages": [{"id": "a", "title": "A"}, {"id": "a", "title": "B"}]},
        ):
            with self.assertRaises(ValueError):
                validate_news(patch_)

    def test_empty_and_disabled_have_no_strip(self):
        n = VerticalNewsTicker()
        self.assertIsNone(n.prepare(validate_news({}), (1548, 946, 360, 122)))
        self.assertIsNone(
            n.prepare(
                validate_news({"enabled": True, "messages": []}), (1548, 946, 360, 122)
            )
        )

    def test_scrolling_clipped_to_sidebar_and_preserves_old_buffers(self):
        n = VerticalNewsTicker()
        strip = n.prepare(validate_news(NEWS), (1548, 946, 360, 122))
        original = frame()
        a = bytearray(original)
        b = bytearray(original)
        n.blit(_planes(a), strip, 0)
        n.blit(_planes(b), strip, 51)
        self.assertNotEqual(a, b)
        for p, q in zip(_planes(a), _planes(original)):
            f = 1 if p.shape[0] == 1080 else 2
            self.assertTrue(np.array_equal(p[: 946 // f], q[: 946 // f]))
            self.assertTrue(np.array_equal(p[:, : 1548 // f], q[:, : 1548 // f]))
        before = strip.planes[0].copy()
        n.prepare(
            validate_news(
                {"enabled": True, "messages": [{"id": "new", "title": "Otro anuncio"}]}
            ),
            (1548, 946, 360, 122),
        )
        self.assertTrue(np.array_equal(before, strip.planes[0]))

    def test_speed_change_keeps_phase_and_raster_cache(self):
        c = StudioComposer(1920, 1080, {"vertical_news": validate_news(NEWS)})
        r = c.render(entries(), "c0")
        raw = frame()
        with patch("studio.presentation.time.monotonic", return_value=10):
            c.apply(raw, r)
        with patch("studio.presentation.time.monotonic", return_value=12):
            c.apply(raw, r)
        self.assertEqual(c._news_offset, 50)
        r2 = c.render(
            entries(),
            "c0",
            {"settings": {"vertical_news": validate_news({**NEWS, "speed_px_s": 50})}},
        )
        self.assertIs(r.news.planes, r2.news.planes)
        with patch("studio.presentation.time.monotonic", return_value=12):
            c.apply(raw, r2)
        with patch("studio.presentation.time.monotonic", return_value=13):
            c.apply(raw, r2)
        self.assertEqual(c._news_offset, 100)

    def test_two_and_four_secondary_layouts(self):
        c = StudioComposer(1920, 1080, {"vertical_news": validate_news(NEWS)})
        for count in (3, 5):
            r = c.render(entries()[:count], "c0")
            self.assertEqual(len(r.ids), count - 1)
            x, y, w, h = r.news.viewport
            self.assertEqual(x, 1548)
            self.assertEqual(y + h, 1068)
            self.assertTrue(all(v % 2 == 0 for v in (x, y, w, h)))
            self.assertGreater(y, c._cards(count - 1)[-1][1] + 204)
        c2 = StudioComposer(1920, 1080)
        self.assertIsNone(c2.render(entries(), "c0").news)
