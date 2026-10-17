"""Run inside the engine image: python3 -m unittest discover -s tests -v."""

import asyncio
import json
import tempfile
import unittest
from pathlib import Path

from aiohttp.test_utils import TestClient, TestServer

from studio.config import clean_text, validate
from studio.music import Music
from studio.server import create_app


class ConfigTests(unittest.TestCase):
    def test_bounds_and_paths(self):
        for patch in [
            {"threads": 20},
            {"width": 1919},
            {"fps": True},
            {"destination_url": "https://example.invalid/key"},
            {"music_directory": "/etc"},
            {"timezone": "bad/timezone"},
            {"cta_duration": 60, "cta_period": 60},
            {"unknown": True},
        ]:
            with self.subTest(patch=patch), self.assertRaises(ValueError):
                validate(patch)
        self.assertEqual(validate({"width": 1280, "height": 720})["width"], 1280)

    def test_text_is_literal(self):
        self.assertEqual(
            clean_text("100% : %{localtime}\x00\nhello"), "100% : %{localtime} hello"
        )

    def test_bookmark_reorders_and_wraps(self):
        with tempfile.TemporaryDirectory() as d:
            m = Music("/share", d)
            m.items = [
                {"path": "a", "name": "a.mp3", "duration": 10},
                {"path": "b", "name": "b.mp3", "duration": 20},
            ]
            m.save(45)
            self.assertEqual(m.resume(), 15)
            m.items.reverse()
            self.assertEqual(m.resume(), 5)
            m.items = m.items[1:]
            self.assertEqual(m.resume(), 0)


class ApiTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp = tempfile.TemporaryDirectory()
        p = Path(self.temp.name)
        self.app = await create_app(
            p / "data", p / "media", {"api_token": "x" * 40, "destination_url": ""}
        )
        self.engine = self.app["engine"]
        self.client = TestClient(TestServer(self.app))
        await self.client.start_server()
        self.headers = {"Authorization": "Bearer " + "x" * 40}

    async def asyncTearDown(self):
        await self.client.close()
        self.temp.cleanup()

    async def post(self, path, data):
        return await self.client.post("/api/" + path, json=data, headers=self.headers)

    async def test_auth_and_no_install_autostart(self):
        r = await self.client.get("/api/status")
        self.assertEqual(r.status, 401)
        r = await self.client.get("/api/status", headers=self.headers)
        d = await r.json()
        self.assertEqual(d["state"], "stopped")
        self.assertFalse(self.engine.wanted)
        self.assertNotIn("destination_url", d)

    async def test_reject_start_without_configuration(self):
        self.assertEqual((await self.post("start", {"mode": "live"})).status, 400)
        self.assertEqual(
            (
                await self.post("config", {"rtsp_url": "rtsp://camera.invalid/view"})
            ).status,
            200,
        )
        self.assertEqual((await self.post("start", {"mode": "live"})).status, 400)
        self.assertEqual(
            (await self.post("start", {"mode": "preview", "duration": 999999})).status,
            400,
        )

    async def test_overlay_updates_and_video_is_guarded(self):
        self.engine.wanted = True
        self.assertEqual(
            (
                await self.post("config", {"ticker": "100% : %{localtime} literal"})
            ).status,
            200,
        )
        self.assertEqual((await self.post("config", {"width": 1280})).status, 400)
        self.assertEqual(
            (
                await self.post(
                    "config", {"destination_url": "rtmps://example.invalid/private"}
                )
            ).status,
            400,
        )
        await asyncio.sleep(1.1)
        self.assertEqual(
            (self.engine.overlay / "ticker.txt").read_text(),
            "100% : %{localtime} literal",
        )
        self.assertIsNone(self.engine.process)

    async def test_sensor_expiry_and_invalid_payload(self):
        self.assertEqual(
            (await self.post("metadata", {"sensor_text": "Temperature: 22 C"})).status,
            200,
        )
        await asyncio.sleep(1.1)
        self.assertEqual(
            (self.engine.overlay / "sensor.txt").read_text(), "Temperature: 22 C"
        )
        self.engine.sensor_updated -= 121
        await asyncio.sleep(1.1)
        self.assertEqual((self.engine.overlay / "sensor.txt").read_text(), "")
        self.assertEqual((await self.post("metadata", {"extra": "bad"})).status, 400)

    async def test_source_credentials_do_not_leak_into_status(self):
        await self.post(
            "config", {"rtsp_url": "rtsp://user:secret@camera.invalid/video"}
        )
        r = await self.client.get("/api/status", headers=self.headers)
        raw = await r.text()
        self.assertNotIn("secret", raw)
        self.assertNotIn("rtsp://", raw)
        r = await self.client.get("/api/config", headers=self.headers)
        self.assertNotIn("destination_url", await r.json())


class IntentTests(unittest.IsolatedAsyncioTestCase):
    async def test_restart_restores_live_but_stop_cancels_restore(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            data = root / "data"
            data.mkdir()
            (data / "settings.json").write_text(
                json.dumps({"rtsp_url": "rtsp://camera.invalid/live"})
            )
            (data / "intent.json").write_text(json.dumps({"resume_live": True}))
            options = {
                "api_token": "x" * 40,
                "destination_url": "rtmp://receiver.invalid/live/test",
            }
            for should_stop in [False, True]:
                app = await create_app(data, root / "media", options)
                engine = app["engine"]

                async def fake_worker():
                    while engine.wanted:
                        await asyncio.sleep(0.01)

                engine.run = fake_worker
                client = TestClient(TestServer(app))
                await client.start_server()
                self.assertTrue(engine.wanted)
                self.assertEqual(engine.mode, "live")
                if should_stop:
                    response = await client.post(
                        "/api/stop",
                        json={},
                        headers={"Authorization": "Bearer " + "x" * 40},
                    )
                    self.assertEqual(response.status, 200)
                await client.close()
                self.assertEqual(
                    json.loads((data / "intent.json").read_text())["resume_live"],
                    not should_stop,
                )


if __name__ == "__main__":
    unittest.main()
