"""Isolation, lifecycle and credential guards for multiple lives."""

import asyncio
import json
import pathlib
import tempfile
import unittest

from aiohttp.test_utils import TestClient, TestServer

from studio.server import create_app

SOURCE = dict(
    id="wide",
    name="Wide",
    rtsp_url="rtsp://fixture.invalid/video",
    camera_entity="",
    description="Test source",
)


class ManagerTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = pathlib.Path(self.temp.name)
        self.app = await create_app(
            self.root / "data",
            self.root / "media",
            {"api_token": "x" * 40, "destination_url": ""},
        )
        self.client = TestClient(TestServer(self.app))
        await self.client.start_server()
        self.manager = self.app["manager"]
        self.headers = {"Authorization": "Bearer " + "x" * 40}

    async def asyncTearDown(self):
        await self.client.close()
        self.temp.cleanup()

    async def request(self, method, path, body=None, expected=200):
        response = await self.client.request(
            method, "/api/" + path, headers=self.headers, json=body
        )
        self.assertEqual(response.status, expected)
        return (
            await response.json() if response.content_type == "application/json" else {}
        )

    async def test_catalog_remembers_unassigned_cameras_across_restart(self):
        engine = self.manager.get("default")
        await engine.configure({"sources": [SOURCE]})
        first = self.manager.catalog()["sources"]
        await engine.configure({"sources": []})
        self.assertEqual(self.manager.catalog()["sources"], first)
        from studio.manager import LiveManager

        restarted = LiveManager(self.root / "data", self.root / "media", {})
        self.assertEqual(restarted.catalog()["sources"], first)

    async def create(self, name):
        return await self.request(
            "POST", "lives", {"name": name, "config": {"sources": [SOURCE]}}, 201
        )

    async def test_camera_sensor_text_and_lifecycle_are_independent(self):
        a, b = await self.create("First"), await self.create("Second")
        self.assertNotEqual(a["id"], b["id"])
        self.assertNotEqual(
            self.manager.get(a["live_id"]).media, self.manager.get(b["live_id"]).media
        )
        await self.request(
            "POST",
            "lives/" + a["live_id"] + "/metadata",
            {"sensor_text": "Temperature: 20 °C · Humidity: 75 %", "daylight": True},
        )
        await self.request(
            "POST",
            "lives/" + b["live_id"] + "/metadata",
            {"sensor_text": "", "daylight": False},
        )
        self.assertEqual(
            self.manager.get(a["live_id"]).sensor_text,
            "Temperature: 20 °C · Humidity: 75 %",
        )
        self.assertEqual(self.manager.get(b["live_id"]).sensor_text, "")
        self.assertFalse(hasattr(self.manager.get(a["live_id"]).director, "daylight"))
        self.assertEqual(
            (await self.request("GET", "catalog"))["sources"][0]["name"], "Wide"
        )
        for identity in [a["live_id"], b["live_id"]]:
            engine = self.manager.get(identity)
            await self.manager.destination(
                identity, {"url": "rtmp://fixture.invalid/live/" + identity}
            )

            async def run(current=engine):
                while current.wanted:
                    await asyncio.sleep(0.01)

            engine.run = run
            await self.request("POST", "lives/" + identity + "/start", {"mode": "live"})
        self.assertTrue(
            self.manager.get(a["live_id"]).wanted
            and self.manager.get(b["live_id"]).wanted
        )
        await self.request("DELETE", "lives/" + a["live_id"], expected=400)
        await self.request("POST", "lives/" + a["live_id"] + "/stop", {})
        self.assertTrue(self.manager.get(b["live_id"]).wanted)
        await self.request("DELETE", "lives/" + a["live_id"])
        self.assertTrue(self.manager.get(b["live_id"]).wanted)

    async def test_destinations_private_unique_and_persistent(self):
        a, b = await self.create("First"), await self.create("Second")
        path = "lives/" + a["live_id"] + "/destination"
        key = "fixture-private-ingest-key"
        await self.request(
            "POST", path, {"url": "rtmp://a.rtmp.youtube.com/live2/" + key}
        )
        await self.request(
            "POST",
            "lives/" + b["live_id"] + "/destination",
            {"url": "rtmps://a.rtmps.youtube.com:443/live2/" + key},
            400,
        )
        for route in [
            "server",
            "lives",
            "lives/" + a["live_id"] + "/status",
            "lives/" + a["live_id"] + "/config",
        ]:
            self.assertNotIn(key, json.dumps(await self.request("GET", route)))
        self.assertEqual(
            json.loads((self.root / "data/destinations.json").read_text())[
                a["live_id"]
            ],
            "rtmp://a.rtmp.youtube.com/live2/" + key,
        )
        await self.request("POST", path, {"url": ""})
        self.assertFalse(
            (await self.request("GET", "lives/" + a["live_id"] + "/status"))[
                "destination_configured"
            ]
        )

    async def test_creation_validation_missing_and_duplicate_names(self):
        await self.create("First")
        await self.request(
            "POST", "lives", {"name": "first", "config": {"sources": [SOURCE]}}, 400
        )
        await self.request(
            "POST", "lives", {"name": "Empty", "config": {"sources": []}}, 400
        )
        await self.request(
            "POST",
            "lives",
            {
                "name": "Invalid",
                "config": {
                    "sources": [SOURCE],
                    "destination_url": "rtmp://fixture.invalid/live/key",
                },
            },
            400,
        )
        await self.request("GET", "lives/unknown/status", expected=404)
        self.assertEqual((await self.request("GET", "server"))["live_count"], 2)

    async def test_deleted_default_does_not_reappear_after_restart(self):
        await self.request("DELETE", "lives/default")
        from studio.manager import LiveManager

        manager = LiveManager(
            self.root / "data",
            self.root / "media",
            {"destination_url": "rtmp://fixture.invalid/live/old"},
        )
        self.assertEqual(manager.list_lives()["lives"], [])
        self.assertEqual(manager.server_status()["live_count"], 0)

    async def test_broken_profile_does_not_stop_other_profiles(self):
        a = await self.create("First")
        (self.manager.get(a["live_id"]).data / "settings.json").write_text("broken")
        from studio.manager import LiveManager

        manager = LiveManager(self.root / "data", self.root / "media", {})
        self.assertIn(a["live_id"], manager.failed)
        self.assertEqual(manager.get("default").state, "stopped")
        self.assertEqual(
            next(
                x for x in manager.list_lives()["lives"] if x["live_id"] == a["live_id"]
            )["state"],
            "error",
        )

    async def test_saved_intents_resume_per_live(self):
        a, b = await self.create("First"), await self.create("Second")
        for item in [a, b]:
            await self.request(
                "POST",
                "lives/" + item["live_id"] + "/destination",
                {"url": "rtmp://fixture.invalid/live/" + item["live_id"]},
            )
        await self.client.close()
        for item, resume in [(a, True), (b, False)]:
            path = self.root / "data/lives" / item["live_id"] / "intent.json"
            path.write_text(json.dumps({"resume_live": resume}))
        app = await create_app(
            self.root / "data",
            self.root / "media",
            {"api_token": "x" * 40, "destination_url": ""},
        )
        manager = app["manager"]
        for engine in manager.engines.values():

            async def run(current=engine):
                while current.wanted:
                    await asyncio.sleep(0.01)

            engine.run = run
        self.client = TestClient(TestServer(app))
        await self.client.start_server()
        self.assertTrue(manager.get(a["live_id"]).wanted)
        self.assertFalse(manager.get(b["live_id"]).wanted)
        await manager.get(a["live_id"]).stop()
        self.assertFalse(
            json.loads((manager.path(a["live_id"]) / "intent.json").read_text())[
                "resume_live"
            ]
        )
