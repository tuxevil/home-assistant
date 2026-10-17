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
