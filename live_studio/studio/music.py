"""Normalize MP3 inputs once; retain playback position across reconnects."""

import hashlib
import json
import math
import subprocess
from pathlib import Path

from .config import atomic_json


class Music:
    def __init__(self, root, data):
        self.root = Path(root)
        self.data = Path(data)
        self.items = []

    def prepare(self):
        cache = self.data / "audio"
        cache.mkdir(exist_ok=True)
        self.items = []
        for original in sorted(self.root.glob("*.mp3")):
            stat = original.stat()
            key = hashlib.sha256(
                f"{original}:{stat.st_size}:{stat.st_mtime_ns}".encode()
            ).hexdigest()
            target = cache / (key + ".flac")
            metadata = cache / (key + ".json")
            if not target.exists():
                temp = target.with_suffix(".tmp.flac")
                subprocess.run(
                    [
                        "ffmpeg",
                        "-nostdin",
                        "-v",
                        "error",
                        "-y",
                        "-i",
                        str(original),
                        "-vn",
                        "-ac",
                        "2",
                        "-ar",
                        "44100",
                        "-c:a",
                        "flac",
                        str(temp),
                    ],
                    check=True,
                    timeout=1800,
                    capture_output=True,
                )
                temp.replace(target)
            if not metadata.exists():
                probe = subprocess.run(
                    [
                        "ffprobe",
                        "-v",
                        "error",
                        "-show_entries",
                        "format=duration",
                        "-of",
                        "json",
                        str(target),
                    ],
                    check=True,
                    capture_output=True,
                    text=True,
                    timeout=15,
                )
                atomic_json(
                    metadata,
                    {"duration": float(json.loads(probe.stdout)["format"]["duration"])},
                )
            duration = float(json.loads(metadata.read_text())["duration"])
            if not math.isfinite(duration) or duration <= 0:
                raise ValueError("Invalid music file")
            self.items.append(
                dict(path=str(target), name=original.name, duration=duration)
            )
        return self.items

    def locate(self, offset):
        if not self.items:
            raise ValueError("No music")
        offset = max(0, offset) % sum(i["duration"] for i in self.items)
        for index, item in enumerate(self.items):
            if offset < item["duration"]:
                return index, offset
            offset -= item["duration"]
        return 0, 0

    def resume(self):
        try:
            saved = json.loads((self.data / "audio_position.json").read_text())
            offset = 0
            for item in self.items:
                if item["path"] == saved["path"]:
                    position = float(saved["position"])
                    if math.isfinite(position):
                        return offset + max(
                            0, min(position, item["duration"] - 1 / 44100)
                        )
                offset += item["duration"]
        except (OSError, ValueError, KeyError, TypeError):
            pass
        return 0

    def save(self, offset):
        index, pos = self.locate(offset)
        atomic_json(
            self.data / "audio_position.json",
            dict(
                path=self.items[index]["path"],
                track=self.items[index]["name"],
                position=pos,
            ),
        )

    def playlist(self, offset):
        index, pos = self.locate(offset)
        pos = round(pos * 44100) / 44100
        item = self.items[index]
        pieces = []
        ending = []
        if 0 < pos < item["duration"] - 1 / 44100:
            tail = self.data / "tail.flac"
            head = self.data / "head.flac"
            subprocess.run(
                [
                    "ffmpeg",
                    "-nostdin",
                    "-v",
                    "error",
                    "-y",
                    "-i",
                    item["path"],
                    "-filter_complex",
                    f"[0:a]asplit=2[t][h];[t]atrim=start={pos:.9f},asetpts=PTS-STARTPTS[t1];[h]atrim=end={pos:.9f},asetpts=PTS-STARTPTS[h1]",
                    "-map",
                    "[t1]",
                    "-c:a",
                    "flac",
                    str(tail),
                    "-map",
                    "[h1]",
                    "-c:a",
                    "flac",
                    str(head),
                ],
                check=True,
                capture_output=True,
                timeout=120,
            )
            pieces = [(str(tail), item["duration"] - pos)]
            ending = [(str(head), pos)]
        else:
            pieces = [(item["path"], item["duration"])]
        pieces += [
            (i["path"], i["duration"])
            for i in self.items[index + 1 :] + self.items[:index]
        ]
        lines = ["ffconcat version 1.0"]
        for path, duration in pieces + ending:
            lines += ["file '" + path + "'", f"duration {duration:.9f}"]
        playlist = self.data / "playlist.ffconcat"
        playlist.write_text("\n".join(lines) + "\n")
        return playlist
