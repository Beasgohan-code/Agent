# Encoder batch: eight-command validation and lifecycle pass

> Command availability changed after the reference-pruning request. See
> [current removals and replacement](COMMAND_SURFACE_CHANGES.md); older command
> instructions below are historical where they conflict.

All Encoder handlers now require a personal user identity. `/encode` accepts one
supported preset only; `/compress`, `/toaudio`, `/screens`, `/encinfo` and
`/encpreset` reject extra arguments rather than pretending to support them.
`/screens` remains a fixed-layout contact sheet, not a count-selectable feature.
`/sample [start] [length]` explicitly requires finite numbers: start 0–86400,
length above zero up to 300. Invalid values are refused before downloading,
rather than silently defaulted/clamped. Existing media replies are still needed.

`/enccancel [job_id]` now cancels only the caller's `encoder` module jobs, fixing
its accidental reach into unrelated downloads. Extra arguments are refused.
`/compress` and `/encinfo` handle an empty download result without Path(None)
errors. Probe failures return safe guidance. Compression cancellation is no
longer described as an ordinary conversion failure.

Probe cancellation/timeout kills and reaps its FFmpeg child. Tool execution no
longer leaves an unread stderr pipe that can fill and deadlock; stderr is
intentionally discarded and errors report exit status without raw paths/media
metadata. Other exceptional exits while consuming progress also reap the child.
This sacrifices raw stderr diagnosis to bound leakage and avoid the blocked
pipe. Shared job error text is not rendered by Encoder command failure replies.

Validation feedback uses the current premium panel theme and normal fallback.
Real FFmpeg probe/encode/output-validation tests remain part of the suite, plus
noisy-stderr and cancellation regressions. Live Telegram uploads, hard run-time
limits for every conversion, disk cleanup/quotas, SSRF-safe demuxing and a
complete hostile-media sandbox are not solved by this increment.
