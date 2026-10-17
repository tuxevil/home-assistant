"""Regression checks for corrupted input and independent native cadence."""
import asyncio
import unittest
from types import SimpleNamespace
from studio.video import Source

class InputTests(unittest.IsolatedAsyncioTestCase):
    async def test_output_rate_does_not_resample_camera_frames_twice(self):
        import subprocess
        import tempfile
        from pathlib import Path
        def check():
            with tempfile.TemporaryDirectory() as directory:
                clip = str(Path(directory) / 'source.mkv')
                subprocess.run(['ffmpeg','-v','error','-f','lavfi','-i','testsrc2=s=160x96:r=15:d=2','-c:v','ffv1','-y',clip], check=True, capture_output=True)
                source = Source({'id':'wide','rtsp_url':'rtsp://camera.invalid/main'},160,96,30)
                command = source.command()
                after_input = command[command.index('-i')+2:]
                pixels = subprocess.check_output(['ffmpeg','-nostdin','-v','error','-i',clip]+after_input)
                self.assertEqual(len(pixels)//source.size,30, 'A 15 FPS camera must produce 30 original frames in two seconds even when the live outputs 30 FPS')
        await asyncio.to_thread(check)

    async def test_only_sanitized_error_counters_survive(self):
        s = Source({'id':'wide','rtsp_url':'rtsp://camera.invalid/main'},640,360,30)
        stderr = asyncio.StreamReader()
        stderr.feed_data(b'rtsp://username:password@camera.invalid: invalid data\n')
        stderr.feed_data(b'Could not find ref with POC 7\n')
        stderr.feed_data(b'ordinary information\n')
        stderr.feed_eof()
        await s.read_errors(SimpleNamespace(stderr=stderr))
        self.assertEqual(s.decode_errors, 2)
        self.assertIsNotNone(s.decode_error_at)
        self.assertFalse(any('password' in str(value) for key,value in vars(s).items()))
