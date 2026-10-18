"""Reduce rawvideo pipe fragmentation, retaining portable subprocess fallback."""

import asyncio
import errno
import sys

RAWVIDEO_PIPE_BYTES = 1024 * 1024


async def rawvideo_process(*command, **options):
    """Use bounded Linux pipe capacity; never change framing or stream limits.

    The kernel allocates pages on demand. Larger pipes reduce wakeups while
    transferring multi-megabyte frames. Restricted/unprivileged installations
    can deny enlargement; in that case retain the platform defaults.
    """
    if sys.platform == "linux":
        try:
            return await asyncio.create_subprocess_exec(
                *command, pipesize=RAWVIDEO_PIPE_BYTES, **options
            )
        except OSError as error:
            if error.errno not in (errno.EPERM, errno.EACCES, errno.EINVAL, errno.ENOMEM):
                raise
    return await asyncio.create_subprocess_exec(*command, **options)
