# 0.7.1

- Continue automatic camera selection among currently healthy views when another source is offline; never select a disconnected view from an old score.

# 0.7.0

- Optional complete broadcast design: framed 16:9 main, named secondary views, branded header and real-reading telemetry footer.
- Cached planar libswscale main scaling with portable Pillow fallback; one-second HUD and independent thumbnail refresh.
- Coherent camera transitions, discreet offline states, owned buffers and no new RTSP/FFmpeg processes.

# 0.6.0

- Optional per-live camera sidebar with cached YUV thumbnails, runtime bypass and feeder metrics.
- Reuse existing decoded camera buffers; preserve encoder/audio/RTMP and ZMQ overlays.
- Composed overlay snapshots and cancellation/stale-result regression tests.

## 0.5.1

- Add or remove per-live cameras while streaming, retaining unchanged decoders,
  the encoder, RTMP connection and music timeline.
- Select another local source if the active camera is removed; invalidate stale
  AI comparisons and retain manual/automatic selection mode.
- Remember unassigned cameras in a private persistent source library.

## 0.5.0

- Configure each overlay element independently: placement, visibility, size,
  scrolling mode/speed/direction, color, background and shadow.
- Move the information bar to the top or bottom; separate date and time formats.
- Apply layout edits over a private Unix command socket without restarting the
  encoder, RTMP connection or music. No TCP command listener is opened.
- Add fresh composed JPEG previews and safe, partial per-live layout updates.
- Retain legacy overlay flags and unchanged frame-count video timing.
- Use Debian13/FFmpeg7 for consistent runtime overlay editing in the bundled app.

## 0.4.1

- Fix camera motion collapsing to about1FPS after a slow RTMP handshake, even
  while overlays and reported output FPS remain smooth. The paced raw-video
  pipe now uses a frame-count clock instead of demux arrival timestamps.
- Expose actual compositor delivery and selected-camera frame rates separately
  from encoder output FPS, plus the longest pipe wait in the latest window.
- Fix fresh camera JPEG capture with current FFmpeg versions.
- Regression coverage uses a real RTMP receiver with delayed connection setup.

## 0.4.0

- Optional CPU/VAAPI/automatic processing, independent of HAOS or an external Linux host.
- Bounded presentation-timestamp buffering for uneven camera packet arrival.
- Portable music roots and font detection; external systemd example.

## 0.3.1

- Reject damaged source packets and decoding errors before overlay encoding.
- Preserve each camera's native frame cadence; resample only at the output.
- Expose sanitized per-camera decode error counters without logging private URLs.

# 0.3.0 — Multiple independent lives

- One companion hosts up to16 independently controlled lives, each with1–8camera
  streams, settings, ingest, encoder, music bookmark and preview folder.
- Create/list/rename/delete API, shared camera catalog and private per-live ingest
  management. New lives start stopped without a destination. Active lives cannot
  be deleted; a destination cannot be assigned twice to YouTube URL aliases.
- Legacy single-live identity, data files and API aliases remain compatible.
- Companion integration creates/manages lives and optional sensor lists per live.
- Long information lines scroll; unavailable readings disappear independently.

# 0.2.1 — Wall-clock video timing

- Timestamp incoming raw frames from the real clock and normalize the initial
  offset before FPS conversion. Scheduler delays no longer slow the output
  timeline and accumulate video/audio latency.
- Regression test throttles raw-frame delivery below the configured FPS and
  checks completion time plus audio/video duration agreement.

# 0.2.0 — Continuous camera selection

- Independent RTSP receivers feed one persistent encoder; camera changes preserve
  output connection and music. Freshness checks, reconnect screen and automatic
  failover are independent of optional visual scoring.
- Up to eight named sources with private URLs and optional HA entity mapping.
- Manual/automatic selection, bounded scoring API, stale-result rejection,
  configurable daylight preference, margin, confirmations and dwell time.
- Authenticated fresh snapshots, camera/selection health and continuity counters.
- MP3 directory changes detected during playback; playlist rebuild restarts output.
- Companion integration adds optional LLM Vision comparison and native controls.

# 0.1.1 — Preview message timing

- Reset the CTA schedule when starting a preview or live output so the initial message is visible.

# 0.1.0 — First development version

- One configurable RTSP source; H.264 CPU encoding, 1080p/15fps by default.
- Bounded local previews and an explicitly started RTMP/RTMPS output.
- MP3 playlist with normalization, looping and playback bookmarks.
- Clock, title, scrolling ticker, expiring sensor text and periodic CTA.
- Authenticated local API for the Home Assistant companion integration.
- No automatic broadcast creation, public messages or YouTube OAuth required.
