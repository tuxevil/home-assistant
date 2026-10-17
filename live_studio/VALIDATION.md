# Development validation — 0.1.1

Validated on 2026-10-17. These short tests establish a working prototype, not a
24/7 endurance certification.

- Engine built on AMD64 using Alpine 3.23, FFmpeg 8.0.1 and Python 3.12.
- Ten automated tests: configuration bounds, literal text, bookmarks, API
  authentication, rejected invalid operations, live text updates, sensor expiry,
  credential-free status restart/stop intent and the initial CTA schedule.
- Isolated Home Assistant 2026.10.1: installation flow, bad-token rejection,
  seven native entities, options flow, selected sensor, editable ticker,
  diagnostics and unload. CI repeats this test with a fake companion.
- Actual RTSP source, 2880×1620 HEVC: local 20-second MP4 output at configured
  1920×1080/15fps, H.264 + AAC, including music and an in-flight ticker update.
- Container capped at 1.5 vCPU and 600 MiB. During sampled encoding, CPU peaked
  at approximately 82% of one vCPU and reported memory at 381 MiB. Ryzen 9 7945HX
  host; Home Assistant VM has 3 vCPU. Preparation and startup are additional work.
- Local RTMP receiver: successful H.264/AAC output, automatic reconnect after
  killing only the test encoder, and intentional stop remaining stopped after
  restarting the test container. No public ingest was used for these tests.
- Production sender and its public broadcast were not replaced.

AArch64, GPU encoding, multiple scenes and continuous camera switching have not
been validated or implemented in this release. Longer local endurance tests and
visual review should precede migration of an existing broadcast.
