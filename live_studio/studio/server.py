"""Authenticated local control API; never starts a live on installation."""

import asyncio
import hmac
import json
import os
from pathlib import Path

from aiohttp import web

from .config import clean_text
from .manager import LiveManager


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
    manager = LiveManager(data, media, options)
    app["manager"] = manager
    app["engine"] = manager.engines.get("default")

    def live_id(request):
        return request.match_info.get("live_id", "default")

    def current(request):
        identity = live_id(request)
        if identity not in manager.records:
            raise web.HTTPNotFound(text="Unknown live")
        return manager.get(identity)

    async def status(request):
        current(request)
        return web.json_response(manager.status(live_id(request)))

    async def config(request):
        engine = current(request)
        if request.method == "POST":
            patch = await request.json()
            if not isinstance(patch, dict):
                raise ValueError()
            async with engine.lock:
                await engine.configure(patch)
        return web.json_response(engine.public_config())

    async def metadata(request):
        engine = current(request)
        body = await request.json()
        if (
            not isinstance(body, dict)
            or "sensor_text" not in body
            or set(body) - {"sensor_text", "daylight"}
        ):
            raise ValueError()
        # Older integrations still send this retired field; accept and ignore it.
        daylight = body.get("daylight")
        if daylight is not None and type(daylight) is not bool:
            raise ValueError("Invalid daylight")
        engine.sensor_text = clean_text(body["sensor_text"], 1000)
        engine.sensor_updated = asyncio.get_running_loop().time()
        return web.json_response({"ok": True})

    async def start(request):
        engine = current(request)
        body = await request.json()
        if not isinstance(body, dict) or set(body) - {"mode", "duration"}:
            raise ValueError()
        await engine.start(body.get("mode", "preview"), body.get("duration", 20))
        return web.json_response(manager.status(live_id(request)))

    async def stop(request):
        engine = current(request)
        await engine.stop()
        return web.json_response(manager.status(live_id(request)))

    async def overlay_image(request):
        try:
            data = await current(request).overlay_snapshot()
        except (ValueError, OSError, TimeoutError):
            raise web.HTTPServiceUnavailable(text="No fresh overlay image") from None
        return web.Response(
            body=data, content_type="image/jpeg", headers={"Cache-Control": "no-store"}
        )

    async def preview(request):
        engine = current(request)
        path = engine.media / "preview.mp4"
        if not path.exists():
            raise web.HTTPNotFound()
        return web.FileResponse(path)

    async def select(request):
        engine = current(request)
        body = await request.json()
        if (
            not isinstance(body, dict)
            or not set(body) <= {"mode", "camera_id"}
            or "mode" not in body
        ):
            raise ValueError()
        await engine.select(body["mode"], body.get("camera_id"))
        return web.json_response(manager.status(live_id(request)))

    async def comparison(request):
        engine = current(request)
        await engine.comparison(await request.json())
        return web.json_response(manager.status(live_id(request)))

    async def camera(request):
        engine = current(request)
        try:
            data = await engine.camera_snapshot(request.match_info["identity"])
        except (ValueError, TimeoutError):
            raise web.HTTPServiceUnavailable(text="No fresh camera frame") from None
        return web.Response(
            body=data, content_type="image/jpeg", headers={"Cache-Control": "no-store"}
        )

    async def server_status(request):
        return web.json_response(manager.server_status())

    async def lives(request):
        if request.method == "POST":
            return web.json_response(
                await manager.create(await request.json()), status=201
            )
        return web.json_response(manager.list_lives())

    async def live_details(request):
        identity = live_id(request)
        if identity not in manager.records:
            raise web.HTTPNotFound(text="Unknown live")
        if request.method == "DELETE":
            return web.json_response(await manager.delete(identity))
        if request.method == "PATCH":
            return web.json_response(
                await manager.rename(identity, await request.json())
            )
        return web.json_response(manager.status(identity))

    async def destination(request):
        return web.json_response(
            await manager.destination(live_id(request), await request.json())
        )

    async def catalog(request):
        return web.json_response(manager.catalog())

    async def startup(app):
        await manager.startup()

    async def cleanup(app):
        await manager.cleanup()

    app.on_startup.append(startup)
    app.on_cleanup.append(cleanup)
    app.router.add_get("/api/server", server_status)
    app.router.add_get("/api/lives", lives)
    app.router.add_post("/api/lives", lives)
    app.router.add_get("/api/catalog", catalog)
    app.router.add_get("/api/lives/{live_id}", live_details)
    app.router.add_patch("/api/lives/{live_id}", live_details)
    app.router.add_delete("/api/lives/{live_id}", live_details)
    for prefix in ["/api", "/api/lives/{live_id}"]:
        app.router.add_get(prefix + "/status", status)
        app.router.add_get(prefix + "/config", config)
        app.router.add_post(prefix + "/config", config)
        app.router.add_post(prefix + "/metadata", metadata)
        app.router.add_post(prefix + "/start", start)
        app.router.add_post(prefix + "/stop", stop)
        app.router.add_get(prefix + "/preview.mp4", preview)
        app.router.add_get(prefix + "/overlay/snapshot.jpg", overlay_image)
        app.router.add_post(prefix + "/selection", select)
        app.router.add_post(prefix + "/comparison", comparison)
        app.router.add_post(prefix + "/destination", destination)
        app.router.add_get(prefix + "/cameras/{identity}/snapshot.jpg", camera)
    return app


def main():
    web.run_app(create_app(), host="0.0.0.0", port=8099, access_log=None)


if __name__ == "__main__":
    main()
