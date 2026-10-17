"""Overlay validation and real runtime edits without reconnecting the encoder."""

import unittest

from studio.config import validate
from studio.layout import DEFAULT_LAYOUT


class LayoutValidationTests(unittest.TestCase):
    def test_partial_layout_keeps_other_elements_and_legacy_visibility(self):
        original = validate({"show_clock": False, "show_camera_name": False})
        self.assertFalse(original["overlay_layout"]["date"]["visible"])
        changed = validate({"overlay_layout": {"ticker": {"font_size": 45}}}, original)
        self.assertEqual(changed["overlay_layout"]["ticker"]["font_size"], 45)
        self.assertEqual(
            changed["overlay_layout"]["band"], original["overlay_layout"]["band"]
        )
        self.assertEqual(original["overlay_layout"]["ticker"]["font_size"], 28)
        self.assertEqual(DEFAULT_LAYOUT["ticker"]["font_size"], 28)
        changed = validate({"overlay_layout": {"clock": {"visible": True}}}, changed)
        self.assertTrue(changed["show_clock"])
        self.assertFalse(changed["overlay_layout"]["date"]["visible"])

    def test_layout_rejects_filter_injection_and_invalid_types(self):
        for patch in [
            {"unknown": {}},
            {"ticker": {"font_size": True}},
            {"ticker": {"color": "red:enable=1"}},
            {"ticker": {"font_size": 1000}},
            {"ticker": {"speed": -1}},
            {"ticker": {"anchor": "w/0"}},
            {"band": {"position": "left"}},
            {"band": {"opacity": 101}},
            {"clock": {"format": "%{localtime}"}},
            {"source": {"textfile": "/etc/passwd"}},
        ]:
            with self.subTest(patch=patch), self.assertRaises(ValueError):
                validate({"overlay_layout": patch})
