# Development validation — 0.3.0

Validated on 2026-10-17, AMD64 / FFmpeg8 / Home Assistant2026.10.1.

- 29 engine tests include creation, validation, duplicate ingest rejection,
  independent metadata, start/stop/delete, persisted per-live intent and damaged
  configuration isolation. Existing switching, AAC continuity and wall-clock
  regression tests remain in place.
- Two actual FFmpeg encoders ran simultaneously with generated sources. Stopping
  and restarting one preserved the other's PID, output ID, progress and preview.
- Two real HEVC camera streams fed two independent local RTMP receivers in one
  companion. Both carried H264/AAC and loaded30MP3tracks. Stopping/deleting A
  and renaming B preserved B's output ID and advancing timeline. Sensor metadata
  was present only in A; B's line stayed empty. No public destination was used.
- Isolated Home Assistant smoke test covers native create/connect flows,
  multi-camera selection, zero/multiple sensors per live, unavailable-reading
  removal, independent controls, private destination submission, active-delete
  rejection, identity-checked reconfiguration and version1 sensor migration.
- The optional Engine2 distribution is generated from canonical sources and built
  in CI. New lives do not require separate add-on installations.

The following earlier development measurements are retained for context; they are
not benchmarks for arbitrary numbers of simultaneous lives. Resource use grows
with each active encoder and its camera decoders. Multiday endurance, AArch64 and
GPU encoding remain outside these tests.

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
