"""Portable fallback and presentation-time regression tests."""

import unittest
from unittest.mock import patch

from studio.config import validate
from studio.hardware import select
from studio.video import FrameBuffer


class PortableHardwareTests(unittest.IsolatedAsyncioTestCase):
    async def test_cpu_needs_no_device_or_probe(self):
        with patch(
            "studio.hardware.probe",
            side_effect=AssertionError("CPU must not probe GPU"),
        ):
            result = await select(validate({}))
        self.assertEqual(result["encoder"], "cpu")
        self.assertEqual(result["decoder"], "cpu")

    async def test_auto_reports_software_fallback(self):
        with patch("studio.hardware.Path.glob", return_value=[]):
            result = await select(
                validate({"video_encoder": "auto", "video_decoder": "auto"})
            )
        self.assertEqual(result["encoder"], "cpu")
        self.assertIsNotNone(result["fallback_reason"])

    async def test_explicit_gpu_failure_is_visible(self):
        with patch("studio.hardware.probe", return_value=False):
            with self.assertRaises(ValueError):
                await select(
                    validate(
                        {
                            "video_encoder": "vaapi",
                            "vaapi_device": "/dev/dri/renderD129",
                        }
                    )
                )

    async def test_device_selection_is_not_vendor_or_node_number_specific(self):
        with patch("studio.hardware.probe", return_value=True):
            result = await select(
                validate(
                    {
                        "video_encoder": "vaapi",
                        "video_decoder": "cpu",
                        "vaapi_device": "/dev/dri/renderD131",
                    }
                )
            )
        self.assertEqual(result["device"], "/dev/dri/renderD131")
        self.assertEqual(result["encoder"], "vaapi")
        self.assertEqual(result["decoder"], "cpu")

    def test_bursty_arrivals_play_evenly_by_presentation_time(self):
        frames = FrameBuffer(0.25, 8)
        for index in range(4):
            frames.push(bytes([index + 1]), index / 15, 10 + index * 0.001)
        self.assertEqual(frames.at(10.251), b"\x01")
        self.assertEqual(frames.at(10.29), b"\x01")
        self.assertEqual(frames.at(10.32), b"\x02")
        self.assertEqual(frames.at(10.39), b"\x03")
        self.assertEqual(frames.at(10.46), b"\x04")

    def test_overdue_frames_skip_without_catchup_and_memory_is_bounded(self):
        frames = FrameBuffer(0.25, 4)
        for index in range(8):
            frames.push(bytes([index + 1]), index / 15, 10 + index / 15)
        self.assertEqual(len(frames.frames), 4)
        self.assertEqual(frames.at(11), b"\x08")

    def test_camera_clock_reset_recovers_instead_of_freezing(self):
        frames = FrameBuffer(0.25, 8)
        frames.push(b"old", 100, 10)
        frames.push(b"new", 0, 11)
        self.assertEqual(frames.resets, 1)
        self.assertEqual(frames.at(11.3), b"new")

    async def test_decode_only_device_keeps_hardware_decoding_when_encoding_falls_back(
        self,
    ):
        with patch(
            "studio.hardware.probe",
            side_effect=lambda device, encoder=True: not encoder,
        ):
            result = await select(
                validate(
                    {
                        "video_encoder": "auto",
                        "video_decoder": "vaapi",
                        "vaapi_device": "/dev/dri/renderD132",
                    }
                )
            )
        self.assertEqual(result["encoder"], "cpu")
        self.assertEqual(result["decoder"], "vaapi")
        self.assertIsNotNone(result["fallback_reason"])
