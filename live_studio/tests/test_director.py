import tempfile
import time
import unittest
import uuid
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

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

    def submit(self, a, b, now=None, **updates):
        now = time.time() if now is None else now
        body = dict(
            comparison_id=uuid.uuid4().hex,
            observed_at=now,
            sources_revision="sources",
            selection_revision=self.d.revision,
            scores={
                c: dict(score=v, usable=True, reason="visible detail")
                for c, v in [("wide", a), ("zoom", b)]
            },
        )
        body.update(updates)
        self.d.comparison(
            body, {"wide": True, "zoom": True}, True, "sources", now=now
        )
        return body

    def test_two_confirmations(self):
        self.submit(60, 74)
        self.assertEqual(self.d.active, "wide")
        self.submit(60, 74)
        self.assertEqual(self.d.active, "zoom")

    def test_retired_global_daylight_bonus_is_ignored(self):
        legacy = validate(
            {
                "sources": self.settings["sources"],
                "preferred_camera": "wide",
                "day_bonus": 15,
            }
        )
        self.assertNotIn("preferred_camera", legacy)
        self.assertNotIn("day_bonus", legacy)
        self.d.result = {"wide": {"score": 66}, "zoom": {"score": 60}}
        self.assertEqual(self.d.scores(), {"wide": 66, "zoom": 60})
        self.assertNotIn("applied_day_bonus", self.d.status_dict())

    def test_morning_and_evening_preferences_use_live_timezone_and_half_open_windows(self):
        self.d.settings.update(
            timezone="America/Guayaquil",
            morning_camera="zoom",
            morning_start="05:00",
            morning_end="08:00",
            morning_bonus=15,
            evening_camera="wide",
            evening_start="16:30",
            evening_end="19:00",
            evening_bonus=12,
        )
        at = lambda hour, minute=0: datetime(
            2026, 6, 1, hour, minute, tzinfo=ZoneInfo("America/Guayaquil")
        ).timestamp()
        self.assertEqual(self.d.time_bonuses(at(4, 59)), {})
        self.assertEqual(self.d.time_bonuses(at(5)), {"zoom": 15})
        self.assertEqual(self.d.time_bonuses(at(7, 59)), {"zoom": 15})
        self.assertEqual(self.d.time_bonuses(at(8)), {})
        self.assertEqual(self.d.time_bonuses(at(16, 29)), {})
        self.assertEqual(self.d.time_bonuses(at(16, 30)), {"wide": 12})
        self.assertEqual(self.d.time_bonuses(at(18, 59)), {"wide": 12})
        self.assertEqual(self.d.time_bonuses(at(19)), {})

    def test_morning_preference_can_change_automatic_selection(self):
        now = datetime(
            2026, 6, 1, 5, 30, tzinfo=ZoneInfo("America/Guayaquil")
        ).timestamp()
        self.d.settings.update(
            timezone="America/Guayaquil",
            morning_camera="zoom",
            morning_start="05:00",
            morning_end="08:00",
            morning_bonus=15,
            minimum_margin=5,
            confirmations=1,
            minimum_dwell=0,
        )
        self.d.last_switch = now - 1
        self.submit(60, 55, now=now)
        self.assertEqual(self.d.active, "zoom")
        self.assertEqual(self.d.status, "selected")

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

    def test_timed_preference_target_validation_and_removal(self):
        base = validate(
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
                ],
                "morning_camera": "zoom",
            }
        )
        with self.assertRaises(ValueError):
            validate({"morning_camera": "missing"}, base)
        with self.assertRaises(ValueError):
            validate({"morning_start": "25:00"}, base)
        with self.assertRaises(ValueError):
            validate({"evening_start": "16:30", "evening_end": "16:30"}, base)
        remaining = validate({"sources": [base["sources"][0]]}, base)
        self.assertEqual(remaining["morning_camera"], "")
