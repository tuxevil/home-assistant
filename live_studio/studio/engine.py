"""One supervised FFmpeg worker, isolated from Home Assistant Core."""

import asyncio
import json
import time
import uuid
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from . import __version__
from .config import atomic_json, validate
from .director import Director
from .music import Music
from .video import VideoHub, snapshot

OVERLAYS = {
    "title",
    "timezone",
    "show_clock",
    "ticker",
    "cta",
    "cta_period",
    "cta_duration",
    "show_camera_name",
    "no_signal_text",
}


POLICY = {
    "minimum_margin",
    "day_bonus",
    "minimum_dwell",
    "confirmations",
    "comparison_interval",
    "preferred_camera",
}


class Engine:
    def __init__(self, data, media, options):
        self.data = Path(data)
        self.media = Path(media)
        self.data.mkdir(parents=True, exist_ok=True)
        self.media.mkdir(parents=True, exist_ok=True)
        self.options = options
        self.settings = validate(
            json.loads((self.data / "settings.json").read_text())
            if (self.data / "settings.json").exists()
            else {}
        )
        self.settings["destination_url"] = options.get("destination_url", "")
        self.settings = validate(self.settings)
        identity = self.data / "identity"
        if not identity.exists():
            identity.write_text(str(uuid.uuid4()))
        self.identity = identity.read_text().strip()
        self.overlay = self.data / "overlay"
        self.overlay.mkdir(exist_ok=True)
        self.state = "stopped"
        self.error = None
        self.metrics = {}
        self.process = None
        self.worker = None
        self.wanted = False
        self.mode = "preview"
        self.duration = 20
        self.last_frame = None
        self.sensor_text = ""
        self.sensor_updated = 0
        self.anchor = time.monotonic()
        self.music = None
        self.last_audio = 0
        self.start_offset = 0
        self.lock = asyncio.Lock()
        self.text_task = None
        self.director = Director(self.data, self.settings["sources"], self.settings)
        self.sources_revision = uuid.uuid4().hex
        self.hub = None
        self.output_id = None
        self.output_restarts = 0
        self.reload_music = False
        self.snapshot_lock = asyncio.Lock()
        self.font = Path("/usr/share/fonts/ttf-dejavu/DejaVuSans.ttf")

    def status(self):
        return dict(
            id=self.identity,
            version=__version__,
            state=self.state,
            mode=self.mode,
            source_configured=bool(self.settings["sources"]),
            sources_revision=self.sources_revision,
            selection=self.director.status_dict(),
            cameras={
                source["id"]: dict(
                    name=source["name"],
                    camera_entity=source["camera_entity"],
                    **(
                        self.hub.status().get(source["id"], {})
                        if self.hub
                        else dict(
                            healthy=None, frames=0, last_frame_age=None, reconnects=0
                        )
                    ),
                )
                for source in self.settings["sources"]
            },
            current_camera=next(
                (
                    dict(id=x["id"], name=x["name"], camera_entity=x["camera_entity"])
                    for x in self.settings["sources"]
                    if x["id"] == self.director.active
                ),
                None,
            ),
            current_video=bool(
                self.hub and self.hub.healthy().get(self.director.active)
            ),
            output_id=self.output_id,
            output_restarts=self.output_restarts,
            camera_switches=self.hub.switches if self.hub else 0,
            music_tracks=len(self.music.items) if self.music else 0,
            music_track=(
                self.music.items[
                    self.music.locate(self.start_offset + self.last_audio)[0]
                ]["name"]
                if self.music and self.music.items
                else None
            ),
            destination_configured=bool(self.settings["destination_url"]),
            fps=self.metrics.get("fps"),
            speed=self.metrics.get("speed"),
            frames=self.metrics.get("frame"),
            output_seconds=self.last_audio,
            last_frame_age=(
                None
                if self.last_frame is None
                else round(time.monotonic() - self.last_frame, 1)
            ),
            last_error=self.error,
            preview_available=(self.media / "preview.mp4").exists(),
        )

    def public_config(self):
        return {k: v for k, v in self.settings.items() if k != "destination_url"}

    async def configure(self, patch):
        if "destination_url" in patch:
            raise ValueError("Set destination in the companion options")
        if self.wanted and set(patch) - OVERLAYS - POLICY:
            raise ValueError("Stop the output before changing video or source settings")
        settings = validate(patch, self.settings)
        await asyncio.to_thread(
            atomic_json,
            self.data / "settings.json",
            {k: v for k, v in settings.items() if k != "destination_url"},
        )
        sources_changed = self.settings["sources"] != settings["sources"]
        policy_changed = any(self.settings[k] != settings[k] for k in POLICY)
        self.settings = settings
        self.director.settings = settings
        if sources_changed:
            self.sources_revision = uuid.uuid4().hex
            self.director = Director(self.data, settings["sources"], settings)
        elif policy_changed:
            self.director.reset()
            self.director.revision = uuid.uuid4().hex

    async def select(self, mode, camera_id=None):
        async with self.lock:
            self.director.select(mode, camera_id)

    async def comparison(self, body):
        async with self.lock:
            self.director.comparison(
                body,
                self.hub.healthy() if self.hub else {},
                self.wanted,
                self.sources_revision,
            )

    async def camera_snapshot(self, identity):
        source = next(
            (s for s in self.settings["sources"] if s["id"] == identity), None
        )
        if source is None:
            raise ValueError("Unknown camera")
        async with self.snapshot_lock:
            return await snapshot(source, self.settings, self.hub)

    async def texts(self):
        while True:
            now = time.monotonic()
            s = self.settings
            cta = (
                s["cta"]
                if (now - self.anchor) % s["cta_period"] < s["cta_duration"]
                else ""
            )
            values = dict(
                title=s["title"],
                clock=(
                    datetime.now(ZoneInfo(s["timezone"])).strftime("%Y-%m-%d  %H:%M:%S")
                    if s["show_clock"]
                    else ""
                ),
                ticker=s["ticker"],
                cta=cta,
                sensor=self.sensor_text if now - self.sensor_updated < 120 else "",
                source=(
                    self.settings["no_signal_text"]
                    if self.wanted
                    and self.hub
                    and not self.hub.healthy().get(self.director.active)
                    else (
                        next(
                            (
                                x["name"]
                                for x in self.settings["sources"]
                                if x["id"] == self.director.active
                            ),
                            "",
                        )
                        if self.settings["show_camera_name"]
                        else ""
                    )
                ),
            )
            for name, text in values.items():
                path = self.overlay / (name + ".txt")
                # Atomic replacement prevents FFmpeg from reading partial UTF-8.
                if name == "clock" or not path.exists() or path.read_text() != text:
                    temp = path.with_suffix(".tmp")
                    temp.write_text(text)
                    temp.replace(path)
            await asyncio.sleep(1)

    def graph(self):
        s = self.settings
        filters = [
            f"scale={s['width']}:{s['height']}:force_original_aspect_ratio=decrease",
            f"pad={s['width']}:{s['height']}:(ow-iw)/2:(oh-ih)/2",
            "setsar=1",
            f"fps={s['fps']}",
            "format=yuv420p",
        ]
        size = max(18, round(s["height"] / 38))
        bottom = max(72, round(s["height"] / 10))
        filters.append(
            f"drawbox=x=0:y=ih-{bottom}:w=iw:h={bottom}:color=black@0.45:t=fill"
        )
        positions = {
            "source": ("24", "h-th-132"),
            "title": ("24", "24"),
            "clock": ("w-tw-24", "24"),
            "sensor": ("24", f"h-{bottom-12}"),
            "ticker": ("w-mod(t*65\\,w+text_w)", "h-th-16"),
            "cta": ("w-tw-24", f"h-{bottom}-th-24"),
        }
        for name, (x, y) in positions.items():
            filters.append(
                f"drawtext=fontfile={self.font}:textfile={self.overlay}/{name}.txt:reload=1:expansion=none:fontsize={size}:fontcolor=white:shadowcolor=black:shadowx=1:shadowy=1:x={x}:y={y}"
            )
        return ",".join(filters)

    def command(self, listing):
        s = self.settings
        cmd = [
            "ffmpeg",
            "-nostdin",
            "-hide_banner",
            "-loglevel",
            "warning",
            "-y",
            "-stats_period",
            "1",
            "-progress",
            "pipe:1",
            "-thread_queue_size",
            "2",
            "-f",
            "rawvideo",
            "-pixel_format",
            "yuv420p",
            "-video_size",
            f"{s['width']}x{s['height']}",
            "-framerate",
            str(s["fps"]),
            "-i",
            "pipe:0",
        ]
        if listing:
            cmd += [
                "-re",
                "-stream_loop",
                "-1",
                "-f",
                "concat",
                "-safe",
                "0",
                "-i",
                str(listing),
            ]
        else:
            cmd += ["-re", "-f", "lavfi", "-i", "anullsrc=r=44100:cl=stereo"]
        cmd += [
            "-map",
            "0:v:0",
            "-map",
            "1:a:0",
            "-vf",
            self.graph(),
            "-c:v",
            "libx264",
            "-preset",
            "veryfast",
            "-threads",
            str(s["threads"]),
            "-filter_threads",
            "1",
            "-b:v",
            str(s["bitrate_kbps"]) + "k",
            "-maxrate",
            str(s["bitrate_kbps"]) + "k",
            "-bufsize",
            str(2 * s["bitrate_kbps"]) + "k",
            "-g",
            str(s["fps"] * 2),
            "-keyint_min",
            str(s["fps"] * 2),
            "-sc_threshold",
            "0",
            "-c:a",
            "aac",
            "-b:a",
            "128k",
            "-ar",
            "44100",
            "-ac",
            "2",
            "-af",
            "aresample=async=1:first_pts=0",
            "-max_muxing_queue_size",
            "1024",
        ]
        if self.mode == "preview":
            cmd += [
                "-t",
                str(self.duration),
                "-movflags",
                "+faststart",
                "-f",
                "mp4",
                str(self.media / "preview.part.mp4"),
            ]
        else:
            cmd += [
                "-flvflags",
                "no_duration_filesize",
                "-rw_timeout",
                "10000000",
                "-f",
                "flv",
                s["destination_url"],
            ]
        return cmd

    async def start(self, mode, duration=20):
        async with self.lock:
            if self.worker and not self.worker.done():
                raise ValueError("An output is already active")
            if mode not in ("preview", "live"):
                raise ValueError("Invalid output mode")
            if type(duration) is not int or not 5 <= duration <= 60:
                raise ValueError("Preview duration must be 5–60 seconds")
            if not self.settings["sources"]:
                raise ValueError("Configure an RTSP source first")
            if mode == "live" and not self.settings["destination_url"]:
                raise ValueError("Configure a destination first")
            self.mode = mode
            self.anchor = time.monotonic()
            self.duration = duration
            self.wanted = True
            self.error = None
            self.state = "starting"
            if mode == "live":
                await asyncio.to_thread(
                    atomic_json, self.data / "intent.json", {"resume_live": True}
                )
            self.worker = asyncio.create_task(self.run())

    async def stop(self, clear_intent=True):
        async with self.lock:
            self.wanted = False
            if clear_intent:
                await asyncio.to_thread(
                    atomic_json, self.data / "intent.json", {"resume_live": False}
                )
            if self.process and self.process.returncode is None:
                try:
                    self.process.terminate()
                except ProcessLookupError:
                    pass
            if self.worker:
                # Music preparation runs in a bounded worker; never abandon it
                # and start a second writer over the same playlist/cache files.
                await self.worker
            self.state = "stopped"

    async def progress(self):
        last_frame = -1
        last_save = 0
        while line := await self.process.stdout.readline():
            name, sep, value = line.decode(errors="replace").strip().partition("=")
            if not sep:
                continue
            self.metrics[name] = value
            try:
                if name == "frame" and int(value) > max(last_frame, 0):
                    if last_frame < 0:
                        self.anchor = time.monotonic()
                    last_frame = int(value)
                    self.last_frame = time.monotonic()
                    self.state = "running"
                    self.error = None
                if name == "out_time_us":
                    self.last_audio = max(self.last_audio, int(value) / 1e6)
            except ValueError:
                continue
            if self.music and self.music.items and time.monotonic() - last_save >= 5:
                await asyncio.to_thread(
                    self.music.save, self.start_offset + self.last_audio
                )
                last_save = time.monotonic()

    async def discard_errors(self):
        # FFmpeg diagnostics can contain RTSP credentials and ingest keys.
        # Never forward raw lines into logs, status or HA diagnostics.
        while await self.process.stderr.readline():
            pass

    async def watch(self):
        began = time.monotonic()
        checked_music = began
        while self.process.returncode is None:
            await asyncio.sleep(2)
            reference = self.last_frame or began
            if self.music and time.monotonic() - checked_music > 30:
                checked_music = time.monotonic()
                current = await asyncio.to_thread(self.music.signature)
                if current != self.music.initial:
                    self.reload_music = True
                    try:
                        self.process.terminate()
                    except ProcessLookupError:
                        pass
            if not self.wanted or time.monotonic() - reference > 45:
                if self.wanted:
                    self.error = "Video stopped advancing; reconnecting"
                try:
                    self.process.terminate()
                except ProcessLookupError:
                    pass
                try:
                    await asyncio.wait_for(self.process.wait(), 10)
                except TimeoutError:
                    self.process.kill()
                    await self.process.wait()
                break

    async def run(self):
        self.hub = VideoHub(self.settings, self.director)
        try:
            await self.hub.start()
            while self.wanted:
                self.last_audio = 0
                self.last_frame = None
                self.metrics = {}
                self.state = "starting"
                try:
                    self.music = Music(self.settings["music_directory"], self.data)
                    await asyncio.to_thread(self.music.prepare)
                    self.start_offset = self.music.resume() if self.music.items else 0
                    listing = (
                        await asyncio.to_thread(self.music.playlist, self.start_offset)
                        if self.music.items
                        else None
                    )
                    if not self.wanted:
                        break
                    # Avoid a black opening when a source can start promptly.
                    deadline = time.monotonic() + 12
                    while (
                        self.wanted
                        and not self.hub.healthy().get(self.director.active)
                        and time.monotonic() < deadline
                    ):
                        await asyncio.sleep(0.1)
                    if not self.wanted:
                        break
                    if not (self.overlay / "clock.txt").exists():
                        await asyncio.sleep(1.1)
                    self.output_id = uuid.uuid4().hex
                    self.output_restarts += 1
                    self.process = await asyncio.create_subprocess_exec(
                        *self.command(listing),
                        stdin=asyncio.subprocess.PIPE,
                        stdout=asyncio.subprocess.PIPE,
                        stderr=asyncio.subprocess.PIPE,
                    )
                    monitor = asyncio.create_task(self.watch())
                    feeder = asyncio.create_task(self.hub.feed(self.process))
                    readers = [
                        asyncio.create_task(self.progress()),
                        asyncio.create_task(self.discard_errors()),
                    ]
                    code = await self.process.wait()
                    feeder.cancel()
                    monitor.cancel()
                    await asyncio.gather(
                        feeder, monitor, *readers, return_exceptions=True
                    )
                    if self.music.items:
                        await asyncio.to_thread(
                            self.music.save, self.start_offset + self.last_audio
                        )
                    if self.mode == "preview":
                        if code == 0 and self.wanted:
                            (self.media / "preview.part.mp4").replace(
                                self.media / "preview.mp4"
                            )
                            self.state = "preview_completed"
                        elif self.wanted:
                            self.state = "error"
                            self.error = (
                                "Preview failed; check source and encoder settings"
                            )
                        self.wanted = False
                        break
                    if self.wanted:
                        self.error = "Output disconnected; retrying"
                except Exception:
                    self.error = "Unable to prepare or transmit; check configuration, music files and source"
                    if self.mode == "preview":
                        self.state = "error"
                        self.wanted = False
                        break
                finally:
                    if self.process and self.process.returncode is None:
                        self.process.kill()
                        await self.process.wait()
                    self.process = None
                if self.wanted:
                    self.state = "retrying"
                    if self.reload_music:
                        self.reload_music = False
                        continue
                    for _ in range(5):
                        if not self.wanted:
                            break
                        await asyncio.sleep(1)
        finally:
            await self.hub.stop()
            self.hub = None
        if self.state not in ("error", "preview_completed"):
            self.state = "stopped"
