"""Exercise the actual feeder against virtual time; no network or codec needed."""

import types
import unittest

from studio.video import VideoHub


class Clock:
    def __init__(self):
        self.now = 0.0

    def monotonic(self):
        return self.now

    perf_counter = monotonic

    async def sleep(self, duration):
        self.now += duration


class PacingTests(unittest.IsolatedAsyncioTestCase):
    async def feed(self, pauses=None, timeout=False):
        clock = Clock()
        director = types.SimpleNamespace(active="fixture", health_tick=lambda _: None)
        hub = VideoHub(
            {"width": 1920, "height": 1080, "fps": 30,
             "sources": [], "camera_sidebar": False},
            director,
        )
        process = types.SimpleNamespace(returncode=None, terminated=False)
        seen_timeouts = []
        counts = {"frames": 0, "closed": False}

        def compose(frame):
            clock.now += 0.002
            return frame

        def write(frame):
            self.assertEqual(len(frame), 3110400)
            counts["frames"] += 1

        async def drain():
            clock.now += (pauses or {}).get(counts["frames"], 0)
            if counts["frames"] == 300:
                process.returncode = 0

        async def wait_for(awaitable, seconds):
            seen_timeouts.append(seconds)
            if timeout:
                awaitable.close()
                raise TimeoutError
            return await awaitable

        def close():
            counts["closed"] = True

        def terminate():
            process.terminated = True
            process.returncode = 1

        process.stdin = types.SimpleNamespace(write=write, drain=drain, close=close)
        process.terminate = terminate
        hub.compose = compose
        # Isolate time/asyncio references without patching the real event loop's
        # clock or global sleep. Execute the unchanged production feed bytecode.
        dependencies = dict(VideoHub.feed.__globals__)
        dependencies.update(
            time=clock,
            asyncio=types.SimpleNamespace(wait_for=wait_for, sleep=clock.sleep),
        )
        feed = types.FunctionType(VideoHub.feed.__code__, dependencies)
        await feed(hub, process)
        self.assertTrue(counts["closed"])
        self.assertTrue(seen_timeouts)
        self.assertEqual(set(seen_timeouts), {8})
        return clock.now, hub, process, counts

    async def test_repeated_brief_stalls_preserve_media_time(self):
        elapsed, hub, _, counts = await self.feed(
            {frame: 0.060 for frame in range(15, 300, 15)}
        )
        self.assertEqual(counts["frames"], 300)
        self.assertAlmostEqual(elapsed, 10.0, places=5)
        self.assertEqual(hub.feeder_metrics["skipped_pacing_slots"], 0)

    async def test_long_stall_discards_excessive_debt(self):
        elapsed, hub, _, counts = await self.feed({10: 1.5})
        self.assertEqual(counts["frames"], 300)
        self.assertGreater(elapsed, 11.2)
        self.assertLess(elapsed, 11.7)
        self.assertGreater(hub.feeder_metrics["skipped_pacing_slots"], 0)

    async def test_drain_timeout_terminates_and_closes_writer(self):
        _, _, process, counts = await self.feed(timeout=True)
        self.assertTrue(process.terminated)
        self.assertEqual(counts["frames"], 1)
