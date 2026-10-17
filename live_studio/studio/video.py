"""Independent decoders and a paced video feed for one persistent encoder."""

import asyncio
import re
import time
from collections import deque


class FrameBuffer:
    """Play camera PTS against a monotonic clock, bounding latency and memory."""

    def __init__(self, delay=0.25, capacity=32):
        self.delay, self.capacity = delay, capacity
        self.frames = deque()
        self.anchor = None
        self.last_pts = None
        self.displayed = None
        self.resets = 0

    def push(self, frame, pts, arrived):
        if (
            self.anchor is None
            or (
                self.last_pts is not None
                and (pts < self.last_pts - 0.1 or pts - self.last_pts > 10)
            )
            or abs(arrived - (self.anchor + pts - self.delay)) > 2
        ):
            self.anchor = arrived - pts + self.delay
            self.frames.clear()
            self.resets += int(self.last_pts is not None)
        self.last_pts = pts
        self.frames.append((self.anchor + pts, frame))
        while len(self.frames) > self.capacity:
            self.frames.popleft()

    def at(self, now):
        while self.frames and self.frames[0][0] <= now:
            self.displayed = self.frames.popleft()[1]
        return self.displayed or (self.frames[0][1] if self.frames else None)


class Source:
    def __init__(self, source, width, height, fps, acceleration=None, buffer_ms=250):
        self.acceleration = acceleration or {"decoder": "cpu", "device": ""}
        self.decoder = self.acceleration["decoder"]
        self.decoder_fallback = source.get("_decoder_auto", False)
        self.buffer_ms = buffer_ms
        self.buffer = FrameBuffer(buffer_ms / 1000, max(8, fps * 2))
        self.timestamps = asyncio.Queue(maxsize=max(16, fps * 2))
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
        graph = f"scale={self.width}:{self.height}:force_original_aspect_ratio=decrease,pad={self.width}:{self.height}:(ow-iw)/2:(oh-ih)/2,setsar=1,format=yuv420p,setpts=PTS-STARTPTS,showinfo"
        command = [
            "ffmpeg",
            "-nostdin",
            "-hide_banner",
            "-v",
            "info",
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

        if self.decoder == "vaapi":
            i = command.index("-i")
            command[i:i] = [
                "-hwaccel",
                "vaapi",
                "-hwaccel_device",
                self.acceleration["device"],
                "-hwaccel_output_format",
                "vaapi",
            ]
            i = command.index("-vf") + 1
            command[i] = "hwdownload,format=nv12," + command[i]
        return command

    async def read_errors(self, process):
        # Classify locally: raw FFmpeg lines may contain camera credentials.
        while line := await process.stderr.readline():
            lower = line.lower()
            if b"showinfo" in lower:
                match = re.search(rb"\bn:\s*\d+.*?pts_time:([0-9.eE+-]+)", line)
                if match:
                    await self.timestamps.put(float(match[1]))
            if any(
                marker in lower
                for marker in (
                    b"could not find ref",
                    b"error constructing",
                    b"corrupt",
                    b"invalid data",
                    b"pps id out of range",
                    b"error while decoding",
                )
            ):
                self.decode_errors += 1
                self.decode_error_at = time.monotonic()

    async def receive(self):
        while not self.stopping:
            self.frame = None
            self.received = None
            self.buffer = FrameBuffer(self.buffer_ms / 1000, max(8, self.fps * 2))
            self.timestamps = asyncio.Queue(maxsize=max(16, self.fps * 2))
            connection_frames = 0
            errors_task = None
            try:
                command = self.command()
                timestamped = any("showinfo" in x for x in command)
                self.process = await asyncio.create_subprocess_exec(
                    *command,
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
                    arrived = time.monotonic()
                    pts = (
                        await asyncio.wait_for(self.timestamps.get(), 3)
                        if timestamped
                        else arrived
                    )
                    self.buffer.push(frame, pts, arrived)
                    self.buffer.at(arrived)
                    connection_frames += 1
                    self.frame = frame
                    self.received = arrived
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
                if (
                    not connection_frames
                    and self.decoder == "vaapi"
                    and self.decoder_fallback
                ):
                    self.decoder = "cpu"
                self.reconnects += 1
                await asyncio.sleep(2)

    async def stop(self):
        self.stopping = True
        if self.task:
            self.task.cancel()
            await asyncio.gather(self.task, return_exceptions=True)


class VideoHub:
    def __init__(self, settings, director, acceleration=None):
        self.settings = settings
        self.director = director
        self.sources = {
            s["id"]: Source(
                dict(s, _decoder_auto=settings.get("video_decoder") == "auto"),
                settings["width"],
                settings["height"],
                settings["fps"],
                acceleration,
                settings.get("source_buffer_ms", 250),
            )
            for s in settings["sources"]
        }
        self.blank = bytes([16]) * (settings["width"] * settings["height"]) + bytes(
            [128]
        ) * (settings["width"] * settings["height"] // 2)
        self.written = 0
        self.switches = 0
        self.last_source = None
        self.feed_fps = None
        self.selected_frame_fps = None
        self.feed_max_block_seconds = None

    def healthy(self):
        return {key: source.healthy for key, source in self.sources.items()}

    async def start(self):
        for source in self.sources.values():
            source.task = asyncio.create_task(source.receive())

    async def stop(self):
        await asyncio.gather(*(s.stop() for s in self.sources.values()))

    def current_frame(self):
        source = self.sources.get(self.director.active)
        return (
            (source.buffer.at(time.monotonic()) or source.frame)
            if source and source.healthy
            else self.blank
        )

    async def feed(self, process):
        period = 1 / self.settings["fps"]
        due = time.monotonic()
        health_at = due
        report_at = due
        sent = changed = 0
        longest_block = 0
        previous = None
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
                frame = self.current_frame()
                sent += 1
                changed += int(frame is not previous)
                previous = frame
                process.stdin.write(frame)
                wait_at = time.monotonic()
                await asyncio.wait_for(process.stdin.drain(), 8)
                longest_block = max(longest_block, time.monotonic() - wait_at)
                elapsed = time.monotonic() - report_at
                if elapsed >= 5:
                    self.feed_fps = round(sent / elapsed, 2)
                    self.selected_frame_fps = round(changed / elapsed, 2)
                    self.feed_max_block_seconds = round(longest_block, 3)
                    report_at = time.monotonic()
                    sent = changed = 0
                    longest_block = 0
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
                decoder=s.decoder,
                buffered_frames=len(s.buffer.frames),
                timestamp_resets=s.buffer.resets,
                decode_errors=s.decode_errors,
                last_decode_error_age=(
                    None
                    if s.decode_error_at is None
                    else round(time.monotonic() - s.decode_error_at, 2)
                ),
            )
            for key, s in self.sources.items()
        }


async def snapshot(source, settings, hub=None, graph=""):
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
        (graph + "," if graph else "") + "scale=960:-2",
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
