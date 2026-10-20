"""Optional VAAPI, selected at runtime; software works without a GPU."""

import asyncio
import subprocess
from pathlib import Path


def probe(device, encoder=True, video_codec="h264"):
    try:
        command = [
            "ffmpeg",
            "-nostdin",
            "-v",
            "error",
            "-vaapi_device",
            device,
            "-f",
            "lavfi",
            "-i",
            "color=s=256x256:r=30",
            "-frames:v",
            "2",
        ]
        if encoder:
            codec = {"h264": "h264_vaapi", "hevc": "hevc_vaapi"}[video_codec]
            command += ["-vf", "format=nv12,hwupload", "-c:v", codec]
        command += ["-f", "null", "-"]
        result = subprocess.run(command, capture_output=True, timeout=10)
        return result.returncode == 0
    except (OSError, subprocess.TimeoutExpired):
        return False


async def select(settings):
    encoder, decoder = settings["video_encoder"], settings["video_decoder"]
    result = {"encoder": "cpu", "decoder": "cpu", "device": "", "fallback_reason": None}
    if encoder == decoder == "cpu":
        return result
    devices = (
        [settings["vaapi_device"]]
        if settings["vaapi_device"]
        else sorted(str(p) for p in Path("/dev/dri").glob("renderD*"))
    )
    device = None
    for candidate in devices:
        if await asyncio.to_thread(probe, candidate, False):
            device = candidate
            break
    if not device:
        if "vaapi" in (encoder, decoder):
            raise ValueError(
                "VAAPI requested but no working render device is available"
            )
        result["fallback_reason"] = "No working VAAPI device; using CPU"
        return result
    if encoder == "cpu":
        can_encode = False
    elif settings["video_codec"] == "h264":
        can_encode = await asyncio.to_thread(probe, device, True)
    else:
        can_encode = await asyncio.to_thread(
            probe, device, True, settings["video_codec"]
        )
    if encoder == "vaapi" and not can_encode:
        raise ValueError(
            f"Requested VAAPI {settings['video_codec'].upper()} encoder is unavailable"
        )
    result.update(
        device=device,
        encoder="vaapi" if can_encode else "cpu",
        decoder="vaapi" if decoder != "cpu" else "cpu",
    )
    if encoder == "auto" and not can_encode:
        result["fallback_reason"] = (
            f"VAAPI {settings['video_codec'].upper()} encoding unavailable; "
            "using CPU encoder"
        )
    return result
