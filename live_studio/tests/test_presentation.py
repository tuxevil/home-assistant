"""Synthetic planar contract/regions, missing readings, native/fallback scaler."""

from contextlib import nullcontext
import unittest
from unittest.mock import patch

from studio.config import validate
from studio.presentation import StudioComposer, PlanarScaler, telemetry
from studio.sidebar import _planes
from test_sidebar import frame, entries


class PresentationTests(unittest.TestCase):
    def test_regions_and_owned_planar_output(self):
        c = StudioComposer(1920, 1080)
        rail = c.render(entries(), "c0", {})
        original = frame(90, 100, 160)
        out = c.apply(original, rail)
        self.assertEqual(len(out), 3110400)
        for i, p in enumerate(_planes(out)):
            f = 1 if i == 0 else 2
            self.assertEqual(
                int(p[c.main_y // f + 200, c.main_x // f + 400]), (90, 100, 160)[i]
            )
        self.assertNotEqual(out[0], 90)
        self.assertEqual(c.main_w * 9, c.main_h * 16)
        for x, y, w, h in c._cards(4):
            self.assertGreater(x, c.main_x + c.main_w)
            self.assertLess(abs(w / h - 16 / 9), 0.02)
            self.assertTrue(all(v % 2 == 0 for v in (x, y, w, h)))
        before = bytes(out)
        c.apply(frame(180), rail)
        self.assertEqual(bytes(out), before)
        self.assertEqual(original, frame(90, 100, 160))
        self.assertEqual(rail.ids, ("c1", "c2", "c3", "c4"))

    def test_missing_main_and_three_camera_variant(self):
        c = StudioComposer(1920, 1080)
        rail = c.render(
            [("c0", "Offline", None), ("c1", "IR", frame()), ("c2", "Wide", frame())],
            "c0",
        )
        self.assertFalse(rail.main_available)
        self.assertEqual(rail.ids, ("c1", "c2"))
        self.assertEqual(len(c.apply(frame(), rail)), 3110400)
        self.assertEqual(c._cards(2)[0][2:], (360, 204))

    def test_real_telemetry_only(self):
        text = "AMB temp: 14.0 °C · AMB humidity: 99.0 % · windspeed: 4.3 km/h · solarradiation: 0.0 W/m² · battery: 80 %"
        self.assertEqual(
            telemetry(text),
            {
                "temperature": "14°C",
                "humidity": "99%",
                "wind": "4.3 km/h",
                "irradiance": "0 W/m²",
            },
        )
        self.assertEqual(telemetry(""), {})
        self.assertEqual(telemetry("temp: unavailable °C · wind: NaN km/h"), {})

    def test_native_and_portable_scaler(self):
        for fallback in (False, True):
            with (
                patch("studio.presentation.ctypes.CDLL", side_effect=OSError)
                if fallback
                else nullcontext()
            ):
                scaler = PlanarScaler(1472, 828)
                planes = scaler.scale(frame(80, 100, 160))
                self.assertEqual(
                    [p.shape for p in planes], [(828, 1472), (414, 736), (414, 736)]
                )
                self.assertEqual([int(p[100, 100]) for p in planes], [80, 100, 160])
                scaler.close()
                scaler.close()

    def test_transition_preserves_complete_scene(self):
        c = StudioComposer(1920, 1080)
        rail = c.render(entries(), "c0")
        out = c.apply(frame(), rail)
        self.assertIs(c.transition_frame(frame(130)), out)
        c._cache_at = 0
        raw = frame(130)
        self.assertIs(c.transition_frame(raw), raw)

    def test_optional_generic_settings(self):
        self.assertFalse(validate({})["studio_presentation"])
        self.assertEqual(validate({})["broadcast_brand"], "LIVE STUDIO")
        with self.assertRaises(ValueError):
            validate({"studio_presentation": 1})
