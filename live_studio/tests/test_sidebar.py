"""Contract, lifecycle, fail-open and backpressure tests; synthetic frames."""

import asyncio
import time
import unittest
from unittest.mock import patch

from studio.config import validate
from studio.sidebar import CameraSidebar
from studio.video import VideoHub

W, H = 1920, 1080
SIZE = W * H * 3 // 2


def frame(y=90, u=100, v=160):
    return bytes([y]) * (W * H) + bytes([u]) * (W * H // 4) + bytes([v]) * (W * H // 4)


def entries():
    return [("c" + str(i), "Camera " + str(i), frame(40 + i * 25)) for i in range(5)]


class Director:
    active = "c0"

    def health_tick(self, _):
        pass


def hub():
    settings = validate(
        {
            "camera_sidebar": True,
            "fps": 30,
            "sources": [
                {
                    "id": "c" + str(i),
                    "name": "Camera " + str(i),
                    "rtsp_url": "rtsp://example.invalid/" + str(i),
                }
                for i in range(5)
            ],
        }
    )
    return VideoHub(settings, Director())


class SidebarTests(unittest.TestCase):
    def test_size_planes_immutability_and_chroma_alignment(self):
        c = CameraSidebar(W, H)
        rail = c.render(entries(), "c0")
        original = frame(18)
        result = c.apply(original, rail)
        self.assertEqual(len(result), 3110400)
        self.assertEqual(original, frame(18))
        self.assertEqual(rail.ids, ("c1", "c2", "c3", "c4"))
        x, y = c.panel_x + c.tile_x, c.panel_y + c.first_y
        self.assertEqual(result[y * W + x], 65)
        self.assertEqual(result[W * H + (y // 2) * (W // 2) + x // 2], 100)
        self.assertEqual(result[W * H * 5 // 4 + (y // 2) * (W // 2) + x // 2], 160)
        self.assertIs(result, c.apply(original, rail))
        self.assertEqual(result[0], 18)
        self.assertEqual((c.tile_w * 9, c.photo_h * 16), (2880, 2880))
        self.assertTrue(
            all(
                v % 2 == 0
                for v in (
                    c.panel_x,
                    c.panel_y,
                    c.tile_x,
                    c.first_y,
                    c.step,
                    c.tile_w,
                    c.photo_h,
                )
            )
        )

    def test_missing_signal_one_source_and_main_exclusion(self):
        c = CameraSidebar(W, H)
        rail = c.render(
            [
                ("c0", "Main", frame()),
                ("c1", "Missing", None),
                ("c2", "Other", frame()),
            ],
            "c0",
        )
        self.assertEqual(rail.healthy, (False, True))
        self.assertEqual(rail.ids, ("c1", "c2"))
        self.assertIsNone(c.render([("c0", "Only", frame())], "c0"))
        self.assertEqual(c.render(entries(), "c3").ids, ("c0", "c1", "c2", "c4"))
        with self.assertRaises(ValueError):
            c.apply(b"bad", rail)

    def test_validation(self):
        self.assertFalse(validate({})["camera_sidebar"])
        self.assertEqual(validate({})["sidebar_refresh_seconds"], 3)
        for value in (1, "true", None):
            with self.assertRaises(ValueError):
                validate({"camera_sidebar": value})
        for value in (0, 31):
            with self.assertRaises(ValueError):
                validate({"sidebar_refresh_seconds": value})


class LifecycleTests(unittest.IsolatedAsyncioTestCase):
    async def test_hot_toggle_and_cleanup(self):
        h = hub()
        await h.configure_sidebar(h.settings)
        task = h.sidebar_task
        await asyncio.sleep(0.12)
        self.assertIsNotNone(h.sidebar_rail)
        await h.configure_sidebar(h.settings)
        self.assertIs(task, h.sidebar_task)
        await h.configure_sidebar(dict(h.settings, camera_sidebar=False))
        self.assertIsNone(h.sidebar_task)
        self.assertIsNone(h.sidebar_worker)
        self.assertIsNone(h.sidebar)
        await h.configure_sidebar(dict(h.settings, camera_sidebar=True))
        await asyncio.sleep(0.1)
        await h.stop()
        self.assertIsNone(h.sidebar_task)
        self.assertIsNone(h.sidebar_worker)

    async def test_late_worker_and_switch_never_duplicate_main(self):
        h = hub()
        original = frame()
        h.sidebar_rail = h.sidebar.render(entries(), "c0")
        h.director.active = "c1"
        self.assertIs(h.compose(original), original)
        h.sidebar_membership = (("c0", "Renamed"),)
        h.director.active = "c0"
        self.assertIs(h.compose(original), original)
        await h.stop()

    async def test_cancel_worker_joins_and_does_not_publish(self):
        h = hub()
        old = h.sidebar.render

        def slow(*args):
            time.sleep(0.12)
            return old(*args)

        await h.configure_sidebar(h.settings)
        h.sidebar.render = slow
        await asyncio.sleep(0.02)
        await h.configure_sidebar(dict(h.settings, camera_sidebar=False))
        self.assertIsNone(h.sidebar_rail)
        self.assertIsNone(h.sidebar_worker)
        await asyncio.sleep(0.15)
        self.assertIsNone(h.sidebar_rail)
        await h.stop()

    async def test_render_failure_falls_open(self):
        h = hub()
        await h.configure_sidebar(h.settings)
        h.sidebar.render = lambda *_: 1 / 0
        await asyncio.sleep(0.1)
        self.assertIsNone(h.sidebar)
        self.assertIsNotNone(h.sidebar_error)
        original = frame()
        self.assertIs(h.compose(original), original)
        await h.stop()

    async def test_feed_failure_keeps_size_pacing_and_drain(self):
        h = hub()
        h.sidebar_rail = h.sidebar.render(entries(), "c0")
        h.sidebar.apply = lambda *_: 1 / 0
        original = frame()
        h.current_frame = lambda: original

        class Pipe:
            calls = 0
            closed = False

            def write(self, data):
                assert len(data) == SIZE
                self.calls += 1
                if self.calls == 8:
                    proc.returncode = 0

            async def drain(self):
                await asyncio.sleep(0.001)

            def close(self):
                self.closed = True

        class Process:
            returncode = None
            stdin = Pipe()

        proc = Process()
        start = time.monotonic()
        await h.feed(proc)
        self.assertGreater(time.monotonic() - start, 0.2)
        self.assertEqual(h.written, 8)
        self.assertTrue(proc.stdin.closed)
        self.assertIsNone(h.sidebar)
        await h.stop()

    async def test_missing_dependencies_fail_open(self):
        import builtins

        original = builtins.__import__

        def fail(name, *args, **kwargs):
            if name == "sidebar":
                raise ImportError("synthetic")
            return original(name, *args, **kwargs)

        with patch("builtins.__import__", side_effect=fail):
            h = hub()
        self.assertIsNone(h.sidebar)
        self.assertIsNotNone(h.sidebar_error)
        await h.stop()
