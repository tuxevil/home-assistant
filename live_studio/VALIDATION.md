# Development validation — 0.2.1

Validated on 2026-10-17. AMD64, Alpine 3.23, FFmpeg 8.0.1; Home Assistant 2026.10.1.
These tests validate the development candidate, not uninterrupted 24/7 operation.

- 22 automated engine tests: existing API/configuration/bookmark checks plus
  manual/automatic selection, day/night preference, dwell, confirmations, health
  failover and expired/duplicate/in-flight comparison rejection.
- Generated red/blue video switches verify the same encoder PID/output ID,
  decoded frame colors and AAC energy across changes and short playlist loops.
- A generated decoder was killed and restored: fresh snapshot rejection,
  automatic alternate source and unchanged encoder session were verified.
- Isolated real Home Assistant lifecycle: 20 native entities for two cameras,
  options menus, text, numbers, manual/automatic selection, sensor/daylight,
  optional mocked vision provider, sanitized provider failure and unload.
- Two actual 2880×1620 HEVC RTSP sources, 30 MP3 tracks loaded, local RTMP receiver,
  H.264 1920×1080/15fps + AAC. Ten-minute test with eight manual source changes
  confirmed one encoder session, current video and no output reconnection.
- Container limited to 1.8 vCPU and 1100 MiB. Typical sampled use approximately
  1.5–1.7 logical CPUs and 565–615 MiB; preparation/JPEG capture add work. On a
  Ryzen 9 7945HX VM with 3 vCPU. These measurements include decoding both cameras.
- Production sender was not restarted, replaced or used as the test destination.

AArch64 hardware, GPU encoding, more than two real sources and multiday endurance
remain unvalidated. Public event/OAuth/Analytics and external notification
migrations require the separate checks in [MIGRATION.md](MIGRATION.md).

The initial 0.2.0 capped-CPU endurance run revealed approximately 0.94x media-clock
progress despite stable source switching. 0.2.1 uses wall-clock input timestamps;
the delayed-feed regression verifies that slow raw delivery cannot accumulate
that drift. This correction requires updating the engine; the integration remains
0.2.0.
