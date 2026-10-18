# Camera sidebar

The optional sidebar reuses immutable YUV420P frames from the live's existing
camera decoders. It opens no additional RTSP sessions. Each live has its own
configuration, renderer, refresh task, rail and bounded one-frame cache.

Enable `camera_sidebar` using the authenticated per-live configuration API or
Home Assistant's **Camera sidebar** switch. `sidebar_refresh_seconds` defaults
to 3 (range 2–30). Both settings apply without restarting the encoder, music or
RTMP connection. Turning the switch off immediately returns to full screen.
The feature currently supports 1920×1080 output only; unsupported dimensions or
missing optional dependencies preserve original video and report an error.

For external Python installations, install the project requirements (NumPy and
Pillow are imported only when enabled). The companion image includes them.
CPU encoding remains an explicit existing choice; this feature changes neither
the decoder nor encoder acceleration policy.

## Implementation

The main picture remains full resolution under a right-hand panel. The panel
covers part of the main picture; it does not shrink or distort it. Up to four
320×180 previews show the other selected cameras. A single-source live has no
rail. Coordinates and planes are even-aligned for 4:2:0. Stale cameras show a
signal placeholder. Inputs already contain the Source's aspect-correct padding.
More than five sources continue to work; the rail displays the first four
secondary sources in configured order.

A single background worker resizes Y/U/V planes separately at the configured
interval, and immediately when the selected camera or membership changes. Its
result is published only on the event loop, after checking the selection and
membership again. While the new rail renders, the original frame is used;
the previous rail cannot duplicate the new main camera. Cancelling the refresh
task joins outstanding finite worker work. Threads never publish live state.

The feeder copies a main frame once when it or the rail changes and writes the
prepared planes into that copy. Repeated frames reuse the composed buffer; it
is never mutated after publication. Original Source buffers remain immutable.
The 8-second drain timeout, frame-count clock, missed-slot handling and encoder
command remain unchanged. Rendering exceptions fall back to original video.

Existing FFmpeg text and ZMQ overlays are drawn after composition. The rail
occupies x=1550..1919, y=88..971 at maximum height. Custom overlay positions may
intersect it; use the existing overlay editor to adjust those layouts. The
clock/top bar and the default bottom ticker remain outside the panel.

`status.sidebar` reports refresh age, update count, preview camera IDs, health,
render time and sanitized errors. `status.feeder` reports compose/write/drain
mean/max times in milliseconds over each five-second feeder window.
`overlay/snapshot.jpg` includes the compositor and the current text layout;
this is a pre-encode preview, not an independent YouTube playback capture.

## Recovery and tests

First recovery action: turn off Camera sidebar for the affected live. Its FFmpeg
process and audio continue. Re-enable to retry a failed compositor. Shared Python
code updates require restarting the engine service, which also reconnects any
other lives managed by that service. Do not describe that as independent process
isolation. Per-live configuration, selection, stop and start are independent.

Run `python3 -m unittest discover -s live_studio/tests -v` with the engine on
PYTHONPATH and its dependencies/FFmpeg installed. Tests use generated frames and
streams; production monitoring and energy measurements must be reported
separately. No GPU model, private endpoint, live destination or credentials belong
in this repository.
