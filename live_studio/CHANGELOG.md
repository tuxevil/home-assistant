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
