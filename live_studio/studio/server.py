"""Authenticated local control API; never starts a live on installation."""

import asyncio
import hmac
import json
import os
from pathlib import Path

from aiohttp import web

from .config import clean_text
from .engine import Engine


async def create_app(data=None, media=None, options=None):
    data = Path(data or os.environ.get("STUDIO_DATA", "/data"))
    media = Path(media or os.environ.get("STUDIO_MEDIA", "/media/live_studio"))
    options = (
        options
        if options is not None
        else json.loads((data / "options.json").read_text())
    )
    token = options.get("api_token", "")
    if (
        not isinstance(token, str)
        or not token.isascii()
        or len(token) < 32
        or any(c.isspace() for c in token)
    ):
        raise ValueError("Configure api_token with at least 32 characters")

    @web.middleware
    async def auth(request, handler):
        if not hmac.compare_digest(
            request.headers.get("Authorization", ""), "Bearer " + token
        ):
            raise web.HTTPUnauthorized()
        try:
            return await handler(request)
        except (ValueError, TypeError, KeyError):
            return web.json_response(
                {
                    "error": "Invalid request or operation not available in the current state"
                },
                status=400,
            )

    app = web.Application(middlewares=[auth], client_max_size=16384)
    engine = Engine(data, media, options)
    app["engine"] = engine

    async def status(request):
        return web.json_response(engine.status())

    async def config(request):
        if request.method == "POST":
            patch = await request.json()
            if not isinstance(patch, dict):
                raise ValueError()
            async with engine.lock:
                await engine.configure(patch)
        return web.json_response(engine.public_config())

    async def metadata(request):
        body = await request.json()
        if not isinstance(body, dict) or set(body) != {"sensor_text"}:
            raise ValueError()
        engine.sensor_text = clean_text(body["sensor_text"])
        engine.sensor_updated = asyncio.get_running_loop().time()
        return web.json_response({"ok": True})

    async def start(request):
        body = await request.json()
        if not isinstance(body, dict) or set(body) - {"mode", "duration"}:
            raise ValueError()
        await engine.start(body.get("mode", "preview"), body.get("duration", 20))
        return web.json_response(engine.status())

    async def stop(request):
        await engine.stop()
        return web.json_response(engine.status())

    async def preview(request):
        path = media / "preview.mp4"
        if not path.exists():
            raise web.HTTPNotFound()
        return web.FileResponse(path)

    async def startup(app):
        engine.text_task = asyncio.create_task(engine.texts())
        try:
            resume = (
                json.loads((data / "intent.json").read_text()).get("resume_live")
                is True
            )
        except (OSError, ValueError):
            resume = False
        if resume:
            await engine.start("live")

    async def cleanup(app):
        await engine.stop(clear_intent=False)
        engine.text_task.cancel()
        await asyncio.gather(engine.text_task, return_exceptions=True)

    app.on_startup.append(startup)
    app.on_cleanup.append(cleanup)
    app.router.add_get("/api/status", status)
    app.router.add_get("/api/config", config)
    app.router.add_post("/api/config", config)
    app.router.add_post("/api/metadata", metadata)
    app.router.add_post("/api/start", start)
    app.router.add_post("/api/stop", stop)
    app.router.add_get("/api/preview.mp4", preview)
    return app


def main():
    web.run_app(create_app(), host="0.0.0.0", port=8099, access_log=None)


if __name__ == "__main__":
    main()
