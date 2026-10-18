"""Verify pipe tuning and recoverability on restricted hosts."""

import asyncio
import errno
import sys
import unittest
from unittest.mock import AsyncMock, patch

from studio.process import RAWVIDEO_PIPE_BYTES, rawvideo_process


class RawvideoProcessTests(unittest.IsolatedAsyncioTestCase):
    async def test_linux_uses_bounded_pipe_capacity_and_preserves_options(self):
        spawn = AsyncMock(return_value=object())
        with patch("studio.process.sys.platform", "linux"), patch("studio.process.asyncio.create_subprocess_exec", spawn):
            result = await rawvideo_process("ffmpeg", "-f", "rawvideo", limit=6220800)
        self.assertIs(result, spawn.return_value)
        self.assertEqual(spawn.await_args.kwargs, dict(pipesize=RAWVIDEO_PIPE_BYTES, limit=6220800))

    async def test_restricted_kernel_retries_with_platform_defaults(self):
        for code in (errno.EPERM, errno.EACCES, errno.EINVAL, errno.ENOMEM):
            spawn = AsyncMock(side_effect=[OSError(code, "restricted"), object()])
            with patch("studio.process.sys.platform", "linux"), patch("studio.process.asyncio.create_subprocess_exec", spawn):
                await rawvideo_process("ffmpeg", stdin=-1)
            self.assertEqual(spawn.await_count, 2)
            self.assertEqual(spawn.await_args.kwargs, dict(stdin=-1))

    async def test_missing_executable_is_not_retried(self):
        spawn = AsyncMock(side_effect=FileNotFoundError(errno.ENOENT, "missing"))
        with patch("studio.process.sys.platform", "linux"), patch("studio.process.asyncio.create_subprocess_exec", spawn):
            with self.assertRaises(FileNotFoundError):
                await rawvideo_process("missing")
        self.assertEqual(spawn.await_count, 1)

    async def test_other_platforms_keep_native_pipe_defaults(self):
        spawn = AsyncMock()
        with patch("studio.process.sys.platform", "darwin"), patch("studio.process.asyncio.create_subprocess_exec", spawn):
            await rawvideo_process("ffmpeg", stdout=-1)
        self.assertEqual(spawn.await_args.kwargs, dict(stdout=-1))

    async def test_real_subprocess_preserves_complete_yuv_frame(self):
        size = 3110400
        process = await rawvideo_process(
            sys.executable, "-c",
            "import sys;sys.stdout.buffer.write(bytes([123])*3110400)",
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
            limit=size * 2,
        )
        output, errors = await asyncio.wait_for(process.communicate(), 10)
        self.assertEqual(process.returncode, 0)
        self.assertEqual(errors, b"")
        self.assertEqual(output, bytes([123]) * size)
