"""Actual FFmpeg tests using generated sources; never touch physical cameras."""

import array
import asyncio
import json
import pathlib
import shutil
import socket
import subprocess
import tempfile
import time
import unittest
import uuid
from unittest.mock import patch

from aiohttp.test_utils import TestClient, TestServer

from studio.server import create_app
from studio.video import Source


class ContinuousVideoTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = pathlib.Path(self.temp.name)
        self.music = pathlib.Path("/media") / ("test-music-" + uuid.uuid4().hex)
        self.music.mkdir(parents=True)
        for index, frequency in enumerate([440, 880]):
            await asyncio.to_thread(
                subprocess.run,
                [
                    "ffmpeg",
                    "-nostdin",
                    "-v",
                    "error",
                    "-f",
                    "lavfi",
                    "-i",
                    f"sine=frequency={frequency}:duration=1",
                    "-y",
                    str(self.music / f"{index}.mp3"),
                ],
                check=True,
                capture_output=True,
            )
        self.disabled = set()

        def generated(source):
            if source.id in self.disabled:
                return ["false"]
            color = "red" if source.id == "wide" else "blue"
            return [
                "ffmpeg",
                "-nostdin",
                "-v",
                "error",
                "-re",
                "-f",
                "lavfi",
                "-i",
                f"color=c={color}:s={source.width}x{source.height}:r={source.fps}",
                "-pix_fmt",
                "yuv420p",
                "-threads",
                "1",
                "-f",
                "rawvideo",
                "pipe:1",
            ]

        self.patcher = patch.object(Source, "command", generated)
        self.patcher.start()
        self.app = await create_app(
            self.root / "data",
            self.root / "out",
            {"api_token": "x" * 40, "destination_url": ""},
        )
        self.engine = self.app["engine"]
        self.client = TestClient(TestServer(self.app))
        await self.client.start_server()
        await self.engine.configure(
            {
                "width": 640,
                "height": 360,
                "fps": 10,
                "bitrate_kbps": 800,
                "music_directory": str(self.music),
                "title": "",
                "show_clock": False,
                "ticker": "",
                "cta": "",
                "show_camera_name": False,
                "sources": [
                    {
                        "id": "wide",
                        "name": "Wide",
                        "rtsp_url": "rtsp://generated.invalid/red",
                    },
                    {
                        "id": "zoom",
                        "name": "Zoom",
                        "rtsp_url": "rtsp://generated.invalid/blue",
                    },
                ],
            }
        )

    async def asyncTearDown(self):
        await self.client.close()
        self.patcher.stop()
        shutil.rmtree(self.music)
        self.temp.cleanup()

    async def until(self, predicate, timeout=40):
        end = time.monotonic() + timeout
        while time.monotonic() < end:
            if predicate():
                return
            await asyncio.sleep(0.05)
        self.fail("Timed out waiting for the generated video test")

    async def test_switches_keep_encoder_audio_and_timestamps(self):
        await self.engine.select("manual", "wide")
        await self.engine.start("preview", 10)
        await self.until(lambda: self.engine.last_audio >= 2)
        identity = self.engine.output_id
        pid = self.engine.process.pid
        before = self.engine.last_audio
        image = await self.engine.camera_snapshot("wide")
        self.assertTrue(image.startswith(b"\xff\xd8"))
        await self.engine.select("manual", "zoom")
        await self.until(lambda: self.engine.last_audio >= 5)
        self.assertEqual(
            (self.engine.output_id, self.engine.process.pid), (identity, pid)
        )
        self.assertGreater(self.engine.last_audio, before)
        await self.engine.select("manual", "wide")
        await self.until(lambda: not self.engine.wanted)
        self.assertEqual(self.engine.state, "preview_completed")
        self.assertEqual(self.engine.output_restarts, 1)
        clip = self.root / "out/preview.mp4"
        pixels = await asyncio.to_thread(
            subprocess.check_output,
            [
                "ffmpeg",
                "-nostdin",
                "-v",
                "error",
                "-i",
                str(clip),
                "-an",
                "-vf",
                "crop=2:2:320:180,format=rgb24",
                "-f",
                "rawvideo",
                "pipe:1",
            ],
        )
        runs = []
        for offset in range(0, len(pixels), 12):
            r, g, b = pixels[offset : offset + 3]
            color = (
                "red"
                if r > 150 and b < 100
                else "blue" if b > 150 and r < 100 else "other"
            )
            if not runs or runs[-1] != color:
                runs.append(color)
        self.assertEqual(runs, ["red", "blue", "red"])
        raw = await asyncio.to_thread(
            subprocess.check_output,
            [
                "ffmpeg",
                "-nostdin",
                "-v",
                "error",
                "-i",
                str(clip),
                "-vn",
                "-ar",
                "8000",
                "-ac",
                "1",
                "-f",
                "s16le",
                "pipe:1",
            ],
        )
        samples = array.array("h", raw)
        for start in range(4000, len(samples) - 2000, 2000):
            window = samples[start : start + 2000]
            self.assertGreater(
                sum(v * v for v in window) / len(window),
                90000,
                "Unexpected silence at camera switch/playlist wrap",
            )

    async def test_decoder_failure_does_not_restart_output(self):
        await self.engine.start("preview", 22)
        await self.until(lambda: self.engine.last_audio >= 2)
        identity = self.engine.output_id
        pid = self.engine.process.pid
        self.disabled.add("wide")
        self.engine.hub.sources["wide"].process.kill()
        await self.until(lambda: self.engine.director.active == "zoom", timeout=17)
        self.assertEqual(
            (self.engine.output_id, self.engine.process.pid), (identity, pid)
        )
        self.assertTrue(self.engine.hub.healthy()["zoom"])
        with self.assertRaises(ValueError):
            await self.engine.camera_snapshot("wide")
        self.disabled.remove("wide")
        await self.until(lambda: self.engine.hub.healthy()["wide"], timeout=8)
        self.assertEqual(
            (self.engine.output_id, self.engine.process.pid), (identity, pid)
        )
        await self.engine.stop()
        self.assertEqual(self.engine.state, "stopped")

    async def test_transient_feed_delay_recovers_with_aligned_audio(self):
        await self.engine.select("manual", "wide")
        await self.engine.start("preview", 6)
        await self.until(lambda: self.engine.process is not None)
        writer = self.engine.process.stdin
        original = writer.drain
        delayed = False

        async def delayed_drain():
            nonlocal delayed
            await original()
            if not delayed:
                delayed = True
                await asyncio.sleep(1.5)

        writer.drain = delayed_drain
        started = time.monotonic()
        await self.until(lambda: not self.engine.wanted, timeout=16)
        elapsed = time.monotonic() - started
        self.assertEqual(self.engine.state, "preview_completed")
        # Includes the injected1.5s pause and FFmpeg's input probing/startup;
        # the RTMP test below separately verifies steady-state delivery FPS.
        self.assertLess(elapsed, 12, "Video did not recover after a transient pause")
        probe = json.loads(
            await asyncio.to_thread(
                subprocess.check_output,
                [
                    "ffprobe",
                    "-v",
                    "error",
                    "-show_streams",
                    "-of",
                    "json",
                    str(self.root / "out/preview.mp4"),
                ],
                text=True,
            )
        )
        durations = [float(s["duration"]) for s in probe["streams"]]
        self.assertLess(max(durations) - min(durations), 0.3)

    async def test_slow_rtmp_handshake_does_not_lock_camera_to_one_fps(self):
        # A real RTMP receiver behind a delayed TCP proxy reproduces the
        # startup stall. Output FPS alone misses the regression: fps/drawtext
        # can produce smooth text over repeated camera frames indefinitely.
        with socket.socket() as reserved:
            reserved.bind(("127.0.0.1", 0))
            port = reserved.getsockname()[1]
        receiver = await asyncio.create_subprocess_exec(
            "ffmpeg",
            "-nostdin",
            "-v",
            "error",
            "-listen",
            "1",
            "-i",
            f"rtmp://127.0.0.1:{port}/live/test",
            "-c",
            "copy",
            "-y",
            str(self.root / "received.flv"),
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.DEVNULL,
        )
        connections = set()

        async def proxy(reader, writer):
            task = asyncio.current_task()
            connections.add(task)
            upstream = None
            try:
                await asyncio.sleep(2)
                remote, upstream = await asyncio.open_connection("127.0.0.1", port)

                async def relay(source, destination):
                    while data := await source.read(65536):
                        destination.write(data)
                        await destination.drain()

                await asyncio.gather(relay(reader, upstream), relay(remote, writer))
            finally:
                writer.close()
                if upstream:
                    upstream.close()
                connections.discard(task)

        server = await asyncio.start_server(proxy, "127.0.0.1", 0)
        endpoint = server.sockets[0].getsockname()[1]
        try:
            self.engine.settings["destination_url"] = (
                f"rtmp://127.0.0.1:{endpoint}/live/test"
            )
            await self.engine.start("live")
            await self.until(lambda: self.engine.last_audio >= 4)
            identity = self.engine.output_id
            await self.until(
                lambda: self.engine.hub.feed_fps is not None
                and self.engine.hub.feed_fps >= 9,
                timeout=16,
            )
            self.assertEqual(self.engine.output_id, identity)
            self.assertGreaterEqual(self.engine.hub.selected_frame_fps, 8)
            self.assertLess(self.engine.hub.feed_max_block_seconds, 0.5)
        finally:
            await self.engine.stop()
            server.close()
            tasks = list(connections)
            for task in tasks:
                task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
            await server.wait_closed()
            if receiver.returncode is None:
                receiver.terminate()
            try:
                await asyncio.wait_for(receiver.wait(), 3)
            except TimeoutError:
                receiver.kill()
                await receiver.wait()

    async def test_layout_changes_render_without_restarting_video_or_music(self):
        await self.engine.configure(
            {
                "title": "OVERLAY",
                "overlay_layout": {
                    "band": {"visible": False},
                    "date": {"visible": False},
                    "clock": {"visible": False},
                    "source": {"visible": False},
                    "title": {
                        "anchor": "top_left",
                        "x": 20,
                        "y": 20,
                        "font_size": 60,
                        "shadow": False,
                    },
                },
            }
        )
        await self.engine.start("preview", 12)
        await self.until(lambda: self.engine.last_audio >= 2)
        identity, pid = self.engine.output_id, self.engine.process.pid
        before = self.engine.last_audio
        await self.engine.configure(
            {
                "overlay_layout": {
                    "title": {"x": 300, "y": 100, "font_size": 90, "color": "#00FF00"},
                    "band": {"position": "top", "visible": True, "height": 120},
                }
            }
        )
        await self.until(lambda: not self.engine.layout_pending or self.engine.layout_error)
        self.assertIsNone(self.engine.layout_error)
        response = await self.client.get(
            "/api/overlay/snapshot.jpg", headers={"Authorization": "Bearer " + "x" * 40}
        )
        self.assertEqual(response.status, 200)
        self.assertTrue((await response.read()).startswith(b"\xff\xd8"))
        await self.until(lambda: self.engine.last_audio >= 6)
        self.assertEqual(
            (identity, pid), (self.engine.output_id, self.engine.process.pid)
        )
        self.assertGreater(self.engine.last_audio, before)
        await self.engine.configure({"overlay_layout": {"title": {"visible": False}}})
        await self.until(lambda: not self.engine.wanted)
        self.assertEqual(self.engine.state, "preview_completed")
        self.assertEqual(self.engine.output_restarts, 1)
        clip = self.root / "out/preview.mp4"

        async def pixels(at):
            return await asyncio.to_thread(
                subprocess.check_output,
                [
                    "ffmpeg",
                    "-v",
                    "error",
                    "-ss",
                    str(at),
                    "-i",
                    str(clip),
                    "-frames:v",
                    "1",
                    "-f",
                    "rawvideo",
                    "-pix_fmt",
                    "rgb24",
                    "-",
                ],
            )

        old, moved, hidden = await pixels(1), await pixels(5), await pixels(9)

        def count(image, color, left, top, right, bottom):
            result = 0
            for y in range(top, bottom):
                for x in range(left, right):
                    r, g, b = image[(y * 640 + x) * 3 : (y * 640 + x) * 3 + 3]
                    result += (
                        (r > 180 and g > 180 and b > 180)
                        if color == "white"
                        else (r < 80 and g > 120 and b < 80)
                    )
            return result

        self.assertGreater(count(old, "white", 0, 0, 150, 40), 100)
        self.assertGreater(count(moved, "green", 90, 25, 300, 85), 100)
        self.assertLess(count(hidden, "green", 90, 25, 300, 85), 10)

    async def test_two_simultaneous_encoders_and_independent_stop(self):
        manager = self.app["manager"]
        second = await manager.create(
            {"name": "Second", "config": self.engine.public_config()}
        )
        other = manager.get(second["live_id"])
        await self.engine.start("preview", 12)
        await other.start("preview", 12)
        await self.until(lambda: self.engine.last_audio >= 2 and other.last_audio >= 2)
        self.assertNotEqual(self.engine.process.pid, other.process.pid)
        other_id, other_pid = other.output_id, other.process.pid
        await self.engine.stop()
        before = other.last_audio
        await self.until(lambda: other.last_audio > before + 1)
        self.assertEqual((other.output_id, other.process.pid), (other_id, other_pid))
        self.assertTrue(other.wanted)
        await self.engine.start("preview", 5)
        await self.until(lambda: not self.engine.wanted and not other.wanted)
        self.assertEqual(other.output_restarts, 1)
        self.assertTrue((self.engine.media / "preview.mp4").exists())
        self.assertTrue((other.media / "preview.mp4").exists())
        self.assertNotEqual(self.engine.media, other.media)
