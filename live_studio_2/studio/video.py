"""Independent decoders and a paced video feed for one persistent encoder."""

import asyncio
import time


class Source:
    def __init__(self, source, width, height, fps):
        self.id = source["id"]
        self.url = source["rtsp_url"]
        self.width = width
        self.height = height
        self.fps = fps
        self.size = width * height * 3 // 2
        self.frame = None
        self.received = None
        self.frames = 0
        self.process = None
        self.task = None
        self.stopping = False
        self.reconnects = 0
        self.decode_errors = 0
        self.decode_error_at = None

    @property
    def healthy(self):
        return self.received is not None and time.monotonic() - self.received < 5

    def command(self):
        graph = f"scale={self.width}:{self.height}:force_original_aspect_ratio=decrease,pad={self.width}:{self.height}:(ow-iw)/2:(oh-ih)/2,setsar=1,format=yuv420p"
        return [
            "ffmpeg",
            "-nostdin",
            "-hide_banner",
            "-v",
            "error",
            "-rtsp_transport",
            "tcp",
            "-timeout",
            "5000000",
            "-threads",
            "1",
            "-analyzeduration",
            "2000000",
            "-probesize",
            "4000000",
            "-fflags",
            "+discardcorrupt",
            "-err_detect",
            "explode",
            "-i",
            self.url,
            "-an",
            "-sn",
            "-vf",
            graph,
            "-filter_threads",
            "1",
            "-threads",
            "1",
            "-fps_mode",
            "passthrough",
            "-f",
            "rawvideo",
            "-pix_fmt",
            "yuv420p",
            "pipe:1",
        ]

    async def read_errors(self, process):
        # Classify locally: raw FFmpeg lines may contain camera credentials.
        while line := await process.stderr.readline():
            lower = line.lower()
            if any(marker in lower for marker in (
                b"could not find ref", b"error constructing", b"corrupt",
                b"invalid data", b"pps id out of range", b"error while decoding",
            )):
                self.decode_errors += 1
                self.decode_error_at = time.monotonic()

    async def receive(self):
        while not self.stopping:
            self.frame = None
            self.received = None
            errors_task = None
            try:
                self.process = await asyncio.create_subprocess_exec(
                    *self.command(),
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                    limit=self.size * 2,
                )
                errors_task = asyncio.create_task(self.read_errors(self.process))
                while not self.stopping:
                    frame = await asyncio.wait_for(
                        self.process.stdout.readexactly(self.size),
                        timeout=15 if self.received is None else 8,
                    )
                    self.frame = frame
                    self.received = time.monotonic()
                    self.frames += 1
            except (OSError, TimeoutError, asyncio.IncompleteReadError):
                pass
            finally:
                if errors_task:
                    errors_task.cancel()
                    await asyncio.gather(errors_task, return_exceptions=True)
                if self.process and self.process.returncode is None:
                    try:
                        self.process.terminate()
                    except ProcessLookupError:
                        pass
                    try:
                        await asyncio.wait_for(self.process.communicate(), 3)
                    except TimeoutError:
                        self.process.kill()
                        await self.process.communicate()
                self.process = None
                self.frame = None
                self.received = None
            if not self.stopping:
                self.reconnects += 1
                await asyncio.sleep(2)

    async def stop(self):
        self.stopping = True
        if self.task:
            self.task.cancel()
            await asyncio.gather(self.task, return_exceptions=True)


class VideoHub:
    def __init__(self, settings, director):
        self.settings = settings
        self.director = director
        self.sources = {
            s["id"]: Source(s, settings["width"], settings["height"], settings["fps"])
            for s in settings["sources"]
        }
        self.blank = bytes([16]) * (settings["width"] * settings["height"]) + bytes(
            [128]
        ) * (settings["width"] * settings["height"] // 2)
        self.written = 0
        self.switches = 0
        self.last_source = None

    def healthy(self):
        return {key: source.healthy for key, source in self.sources.items()}

    async def start(self):
        for source in self.sources.values():
            source.task = asyncio.create_task(source.receive())

    async def stop(self):
        await asyncio.gather(*(s.stop() for s in self.sources.values()))

    def current_frame(self):
        source = self.sources.get(self.director.active)
        return source.frame if source and source.healthy else self.blank

    async def feed(self, process):
        period = 1 / self.settings["fps"]
        due = time.monotonic()
        health_at = due
        try:
            while process.returncode is None:
                now = time.monotonic()
                if now >= health_at:
                    self.director.health_tick(self.healthy())
                    health_at = now + 5
                source = self.director.active
                if source != self.last_source:
                    self.switches += int(self.last_source is not None)
                    self.last_source = source
                process.stdin.write(self.current_frame())
                await asyncio.wait_for(process.stdin.drain(), 8)
                self.written += 1
                due += period
                # Drop missed wall-clock slots instead of sending a catch-up burst.
                if due < time.monotonic() - period:
                    due = time.monotonic()
                await asyncio.sleep(max(0, due - time.monotonic()))
        except (BrokenPipeError, ConnectionResetError):
            pass
        except TimeoutError:
            if process.returncode is None:
                try:
                    process.terminate()
                except ProcessLookupError:
                    pass
        finally:
            if process.stdin:
                process.stdin.close()

    def status(self):
        return {
            key: dict(
                healthy=s.healthy,
                frames=s.frames,
                last_frame_age=(
                    None
                    if s.received is None
                    else round(time.monotonic() - s.received, 2)
                ),
                reconnects=s.reconnects,
                decode_errors=s.decode_errors,
                last_decode_error_age=(None if s.decode_error_at is None else round(time.monotonic() - s.decode_error_at, 2)),
            )
            for key, s in self.sources.items()
        }


async def snapshot(source, settings, hub=None):
    """Return a fresh JPEG or fail; never serve a cached last frame as live."""
    current = hub.sources.get(source["id"]) if hub else None
    if hub and (not current or not current.healthy):
        raise ValueError("No fresh camera frame")
    if current:
        command = [
            "ffmpeg",
            "-nostdin",
            "-v",
            "error",
            "-fps_mode",
            "passthrough",
            "-f",
            "rawvideo",
            "-pixel_format",
            "yuv420p",
            "-video_size",
            f"{settings['width']}x{settings['height']}",
            "-i",
            "pipe:0",
        ]
        frame = current.frame
    else:
        command = [
            "ffmpeg",
            "-nostdin",
            "-v",
            "error",
            "-rtsp_transport",
            "tcp",
            "-timeout",
            "5000000",
            "-analyzeduration",
            "2000000",
            "-probesize",
            "4000000",
            "-fflags",
            "+discardcorrupt",
            "-err_detect",
            "explode",
            "-threads",
            "1",
            "-i",
            source["rtsp_url"],
        ]
        frame = None
    command += [
        "-frames:v",
        "1",
        "-vf",
        "scale=960:-2",
        "-filter_threads",
        "1",
        "-threads",
        "1",
        "-f",
        "image2pipe",
        "-vcodec",
        "mjpeg",
        "pipe:1",
    ]
    process = await asyncio.create_subprocess_exec(
        *command,
        stdin=asyncio.subprocess.PIPE if frame else asyncio.subprocess.DEVNULL,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    try:
        data, _ = await asyncio.wait_for(process.communicate(frame), 12)
        if process.returncode or not data.startswith(b"\xff\xd8"):
            raise ValueError("No fresh camera frame")
        # A source may have failed while JPEG was being encoded.
        if hub and not current.healthy:
            raise ValueError("Camera interrupted")
        return data
    finally:
        if process.returncode is None:
            process.kill()
            await process.wait()
