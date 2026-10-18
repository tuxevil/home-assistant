import tempfile
import time
import unittest
import uuid
from pathlib import Path

from studio.config import validate
from studio.director import Director


class PolicyTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.settings = validate(
            {
                "sources": [
                    {
                        "id": "wide",
                        "name": "Wide",
                        "rtsp_url": "rtsp://camera.invalid/wide",
                    },
                    {
                        "id": "zoom",
                        "name": "Zoom",
                        "rtsp_url": "rtsp://camera.invalid/zoom",
                    },
                ]
            }
        )
        self.d = Director(Path(self.tmp.name), self.settings["sources"], self.settings)
        self.d.last_switch = time.time() - 1300

    def submit(self, a, b, **updates):
        body = dict(
            comparison_id=uuid.uuid4().hex,
            observed_at=time.time(),
            sources_revision="sources",
            selection_revision=self.d.revision,
            scores={
                c: dict(score=v, usable=True, reason="visible detail")
                for c, v in [("wide", a), ("zoom", b)]
            },
        )
        body.update(updates)
        self.d.comparison(body, {"wide": True, "zoom": True}, True, "sources")
        return body

    def test_two_confirmations(self):
        self.submit(60, 74)
        self.assertEqual(self.d.active, "wide")
        self.submit(60, 74)
        self.assertEqual(self.d.active, "zoom")

    def test_day_bonus_and_night_neutral(self):
        self.d.select("manual", "zoom")
        self.d.select("automatic")
        self.d.last_switch = time.time() - 1300
        self.d.daylight = True
        self.d.daylight_at = time.monotonic()
        self.submit(66, 60)
        self.submit(66, 60)
        self.assertEqual(self.d.active, "wide")
        self.d.select("manual", "zoom")
        self.d.select("automatic")
        self.d.last_switch = time.time() - 1300
        self.d.daylight = False
        self.submit(66, 60)
        self.submit(66, 60)
        self.assertEqual(self.d.active, "zoom")

    def test_stale_daylight_has_no_bonus(self):
        self.d.daylight = True
        self.d.daylight_at = time.monotonic() - 121
        self.assertEqual(self.d.bonus, 0)

    def test_dwell_and_manual_override(self):
        self.d.last_switch = time.time()
        self.submit(10, 99)
        self.submit(10, 99)
        self.assertEqual(self.d.active, "wide")
        self.d.select("manual", "zoom")
        self.submit(99, 10)
        self.submit(99, 10)
        self.assertEqual(self.d.active, "zoom")

    def test_manual_roundtrip_invalidates_inflight_ai(self):
        old = self.d.revision
        self.d.select("manual", "wide")
        self.d.select("automatic")
        with self.assertRaises(ValueError):
            self.submit(10, 99, selection_revision=old)

    def test_duplicate_expired_and_changed_sources_rejected(self):
        body = self.submit(60, 74)
        for patch in [
            body,
            dict(body, comparison_id=uuid.uuid4().hex, observed_at=time.time() - 181),
            dict(body, comparison_id=uuid.uuid4().hex, sources_revision="old"),
        ]:
            with self.assertRaises(ValueError):
                self.d.comparison(patch, {"wide": True, "zoom": True}, True, "sources")

    def test_health_failover_only_in_auto_after_two_checks(self):
        self.d.health_tick({"wide": False, "zoom": True})
        self.assertEqual(self.d.active, "wide")
        self.d.health_tick({"wide": False, "zoom": True})
        self.assertEqual(self.d.active, "zoom")
        self.d.select("manual", "wide")
        self.d.health_tick({"wide": False, "zoom": True})
        self.d.health_tick({"wide": False, "zoom": True})
        self.assertEqual(self.d.active, "wide")

    def test_persistence_and_bad_result(self):
        self.d.select("manual", "zoom")
        restored = Director(
            Path(self.tmp.name), self.settings["sources"], self.settings
        )
        self.assertEqual((restored.mode, restored.active), ("manual", "zoom"))
        with self.assertRaises(ValueError):
            self.submit(101, 70)
        with self.assertRaises(ValueError):
            self.submit(70, True)

    def test_offline_camera_does_not_block_healthy_selection(self):
        self.d.settings["confirmations"] = 1
        body = self.submit(10, 99)
        self.d.select("automatic", "wide")
        self.d.last_switch = time.time() - 1300
        body.update(comparison_id=uuid.uuid4().hex, selection_revision=self.d.revision)
        self.d.comparison(body, {"wide": False, "zoom": True}, True, "sources")
        self.assertEqual(self.d.active, "zoom")
        self.assertEqual(self.d.status, "selected")

    def test_failed_camera_never_wins_with_a_high_old_score(self):
        body = self.submit(80, 99)
        body.update(comparison_id=uuid.uuid4().hex, selection_revision=self.d.revision)
        self.d.comparison(body, {"wide": True, "zoom": False}, True, "sources")
        self.assertEqual(self.d.active, "wide")
        self.assertEqual(self.d.status, "keep")

    def test_no_healthy_cameras_preserves_current_selection(self):
        body = self.submit(80, 99)
        body.update(comparison_id=uuid.uuid4().hex, selection_revision=self.d.revision)
        self.d.comparison(body, {"wide": False, "zoom": False}, True, "sources")
        self.assertEqual(self.d.active, "wide")
        self.assertEqual(self.d.status, "no_video")

    def test_source_validation_and_legacy_migration(self):
        self.assertEqual(
            validate({"rtsp_url": "rtsp://camera.invalid/old"})["sources"][0][
                "rtsp_url"
            ],
            "rtsp://camera.invalid/old",
        )
        for patch in [
            {
                "sources": [
                    {
                        "id": "invalid/id",
                        "name": "a",
                        "rtsp_url": "rtsp://camera.invalid/a",
                    }
                ]
            },
            {"minimum_margin": 0},
            {
                "sources": [
                    {
                        "id": "a",
                        "name": "Automatic",
                        "rtsp_url": "rtsp://camera.invalid/a",
                    }
                ]
            },
        ]:
            with self.assertRaises(ValueError):
                validate(patch)
