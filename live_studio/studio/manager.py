"""Independent live lifecycles behind one authenticated companion API."""

import asyncio
import hashlib
import json
import shutil
import time
import uuid
from pathlib import Path

from . import __version__
from .config import atomic_json, clean_text, validate
from .engine import Engine


class LiveManager:
    MAX_LIVES = 16

    def __init__(self, data, media, options):
        self.data, self.media, self.options = Path(data), Path(media), options
        self.data.mkdir(parents=True, exist_ok=True)
        self.media.mkdir(parents=True, exist_ok=True)
        identity = self.data / "server_identity"
        if not identity.exists():
            identity.write_text(str(uuid.uuid4()))
        self.identity = identity.read_text().strip()
        self.lock = asyncio.Lock()
        self.started = False
        manifest = self.data / "lives.json"
        if manifest.exists():
            saved = json.loads(manifest.read_text())
            self.records = saved["lives"]
        else:
            # Keep all legacy files, identity and active-output intent in place.
            self.records = {"default": {"name": "Live Studio"}}
            self.persist()
        try:
            self.destinations = json.loads(
                (self.data / "destinations.json").read_text()
            )
        except FileNotFoundError:
            self.destinations = {}
        self.engines = {}
        self.failed = set()
        for identity in self.records:
            self._validate_id(identity)
            try:
                self.engines[identity] = self._engine(identity)
            except (OSError, ValueError, TypeError, KeyError):
                # One damaged live must not prevent the other lives starting.
                self.failed.add(identity)

    @staticmethod
    def _validate_id(identity):
        import re

        if not isinstance(identity, str) or not re.fullmatch(
            r"[a-z][a-z0-9_-]{0,63}", identity
        ):
            raise ValueError("Invalid live identifier")

    def path(self, identity):
        return self.data if identity == "default" else self.data / "lives" / identity

    def media_path(self, identity):
        return self.media if identity == "default" else self.media / identity

    def persist(self):
        atomic_json(self.data / "lives.json", {"version": 1, "lives": self.records})

    def _engine(self, identity):
        destination = self.destinations.get(
            identity,
            self.options.get("destination_url", "") if identity == "default" else "",
        )
        return Engine(
            self.path(identity),
            self.media_path(identity),
            {"destination_url": destination},
        )

    def get(self, identity):
        self._validate_id(identity)
        if identity not in self.records:
            raise KeyError("Unknown live")
        if identity in self.failed:
            raise ValueError("Live configuration needs repair")
        return self.engines[identity]

    def status(self, identity):
        result = self.get(identity).status()
        return dict(
            result,
            live_id=identity,
            live_name=self.records[identity]["name"],
            server_id=self.identity,
        )

    def server_status(self):
        return {
            "id": self.identity,
            "version": __version__,
            "max_lives": self.MAX_LIVES,
            "live_count": len(self.records),
            "capabilities": [
                "multiple_lives",
                "independent_destinations",
                "camera_catalog",
            ],
        }

    def list_lives(self):
        return {
            "lives": [
                {
                    "live_id": key,
                    "name": record["name"],
                    "id": self.engines[key].identity if key in self.engines else None,
                    "state": (
                        self.engines[key].state if key in self.engines else "error"
                    ),
                    "source_count": (
                        len(self.engines[key].settings["sources"])
                        if key in self.engines
                        else 0
                    ),
                }
                for key, record in self.records.items()
            ]
        }

    def catalog(self):
        # Removing a camera from a live must not erase it from the library.
        path = self.data / "camera_catalog.json"
        try:
            sources = json.loads(path.read_text())
            if not isinstance(sources, dict):
                sources = {}
        except (OSError, ValueError):
            sources = {}
        previous = dict(sources)
        for engine in self.engines.values():
            for source in engine.settings["sources"]:
                key = (
                    "source_"
                    + hashlib.sha256(source["rtsp_url"].encode()).hexdigest()[:16]
                )
                sources[key] = dict(source, catalog_id=key)
        if sources != previous:
            atomic_json(path, sources)
        return {"sources": list(sources.values())}

    def _name(self, name, exclude=None):
        name = clean_text(name, 100)
        if not name or any(
            r["name"].casefold() == name.casefold()
            for k, r in self.records.items()
            if k != exclude
        ):
            raise ValueError("Live names must be nonempty and unique")
        return name

    async def create(self, body):
        if not isinstance(body, dict) or set(body) != {"name", "config"}:
            raise ValueError("Provide a name and configuration")
        async with self.lock:
            if len(self.records) >= self.MAX_LIVES:
                raise ValueError("Maximum number of lives reached")
            name = self._name(body["name"])
            patch = body["config"]
            if not isinstance(patch, dict) or "destination_url" in patch:
                raise ValueError("Invalid initial configuration")
            settings = validate(dict(patch, title=patch.get("title", name)))
            if not settings["sources"]:
                raise ValueError("Select at least one camera")
            identity = "live_" + uuid.uuid4().hex[:16]
            path = self.path(identity)
            path.mkdir(parents=True)
            atomic_json(
                path / "settings.json",
                {k: v for k, v in settings.items() if k != "destination_url"},
            )
            engine = self._engine(identity)
            self.records[identity] = {"name": name}
            self.engines[identity] = engine
            self.persist()
            if self.started:
                await self._start_engine(engine)
            return self.status(identity)

    async def rename(self, identity, body):
        if not isinstance(body, dict) or set(body) != {"name"}:
            raise ValueError("Provide only the live name")
        async with self.lock:
            self.get(identity)
            self.records[identity]["name"] = self._name(body["name"], identity)
            self.persist()
        return self.status(identity)

    async def destination(self, identity, body):
        if not isinstance(body, dict) or set(body) != {"url"}:
            raise ValueError("Provide a destination URL")
        engine = self.get(identity)
        async with engine.lock:
            if engine.wanted:
                raise ValueError("Stop this live before changing its destination")
            url = validate({"destination_url": body["url"]})["destination_url"]
            # One key cannot be driven concurrently by two lives, even with URL aliases.
            from urllib.parse import urlsplit

            def ingest_key(value):
                parsed = urlsplit(value)
                return (
                    ("youtube", parsed.path.rstrip("/").rsplit("/", 1)[-1])
                    if (parsed.hostname or "").endswith(".youtube.com")
                    else (parsed.netloc, parsed.path, parsed.query)
                )

            if url:
                key = ingest_key(url)
                if any(
                    other != identity
                    and e.settings.get("destination_url")
                    and ingest_key(e.settings["destination_url"]) == key
                    for other, e in self.engines.items()
                ):
                    raise ValueError("Destination already assigned to another live")
            self.destinations[identity] = url
            atomic_json(self.data / "destinations.json", self.destinations)
            engine.options["destination_url"] = url
            engine.settings["destination_url"] = url
        return {"destination_configured": bool(url)}

    async def delete(self, identity):
        async with self.lock:
            if identity not in self.records:
                raise KeyError("Unknown live")
            engine = self.engines.get(identity)
            if engine and engine.wanted:
                raise ValueError("Stop this live before deleting it")
            if engine:
                await engine.stop()
                if engine.text_task:
                    engine.text_task.cancel()
                    await asyncio.gather(engine.text_task, return_exceptions=True)
            # Archive small configuration files for recovery; never move the server root.
            archive = self.data / "deleted" / (identity + "-" + str(time.time_ns()))
            archive.mkdir(parents=True)
            for name in [
                "settings.json",
                "identity",
                "selection.json",
                "audio_position.json",
                "intent.json",
            ]:
                file = self.path(identity) / name
                if file.exists():
                    shutil.copy2(file, archive / name)
            if identity in self.destinations:
                atomic_json(
                    archive / "destination.json", {"url": self.destinations[identity]}
                )
                del self.destinations[identity]
                atomic_json(self.data / "destinations.json", self.destinations)
            self.records.pop(identity)
            self.engines.pop(identity, None)
            self.failed.discard(identity)
            self.persist()
            if identity != "default":
                shutil.rmtree(self.path(identity), ignore_errors=True)
                shutil.rmtree(self.media_path(identity), ignore_errors=True)
            else:
                for name in [
                    "settings.json",
                    "identity",
                    "selection.json",
                    "audio_position.json",
                    "intent.json",
                    "playlist.ffconcat",
                    "resume_head.flac",
                    "resume_tail.flac",
                ]:
                    (self.data / name).unlink(missing_ok=True)
                for name in ["audio", "overlay"]:
                    shutil.rmtree(self.data / name, ignore_errors=True)
                for name in ["preview.mp4", "preview.part.mp4"]:
                    (self.media / name).unlink(missing_ok=True)
            return {"deleted": True}

    async def _start_engine(self, engine):
        engine.text_task = asyncio.create_task(engine.texts())
        try:
            resume = (
                json.loads((engine.data / "intent.json").read_text()).get("resume_live")
                is True
            )
        except (OSError, ValueError, TypeError):
            resume = False
        if resume:
            try:
                await engine.start("live")
            except ValueError:
                engine.state = "error"
                engine.error = "Saved live could not resume; check its configuration"

    async def startup(self):
        self.started = True
        for engine in self.engines.values():
            await self._start_engine(engine)

    async def cleanup(self):
        self.started = False
        for engine in self.engines.values():
            await engine.stop(clear_intent=False)
            if engine.text_task:
                engine.text_task.cancel()
                await asyncio.gather(engine.text_task, return_exceptions=True)
