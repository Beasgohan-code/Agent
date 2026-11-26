# Meiko TypeTube adapter

Pinned dependency: `typetube@1.1.4` from https://github.com/playeon/typetube.
Reviewed upstream commit: b970886f351d92277371edcc4aff94744981001e.
MIT notice: `licenses/typetube-MIT.txt`.

For non-Docker installations, install Node.js 18+ and run:

```sh
npm ci --ignore-scripts --prefix tools/typetube
```

The Dockerfile includes Node and installs the pinned dependency in a separate build stage. Docker changes have not been image-build validated in this workspace.

Usage in a bot with Leech enabled:

```
/leech https://www.youtube.com/watch?v=dQw4w9WgXcQ
```

The same input works with `/mirror` and replied-link transfer commands. This slice downloads audio only. `-n` continues to set a custom output name; callers should preserve the suggested audio extension.

TypeTube's public cluster resolves a canonical YouTube video URL. The Python adapter permits only HTTPS googlevideo.com subdomain media URLs and public DNS destinations, then uses the existing bounded Meiko HTTP downloader to stream bytes. Redirect checks, size limits, job cancellation and temporary-file cleanup remain in Meiko rather than using the SDK's separate parallel download/mux pipeline.

No API key is passed. Canonicalization discards playlist/tracking query parameters. The helper gets the source URL over stdin, not command arguments; raw provider errors and signed media URLs are not returned in user notices. Resolution is killed after 25 seconds or cancellation. Node stdout is limited by the bridge's own allowlisted bounded JSON fields.

Music `/play` and admin-only `/playnext` also resolve YouTube links through the shared adapter. Existing voice availability and group activation gates remain required. Resolved signed URLs are session-only and cannot be saved by the stable-URL playlist store.

Queued YouTube tracks retain their canonical video URL in memory and resolve a fresh stream on queue advance (skip, natural completion or repeat). Failed resolution restores the original queue; signed source URLs are not logged by Music. This is not mid-stream recovery: seek still uses the current stream; replay now resolves fresh TypeTube audio before replacing playback, and a dropped connection during playback is not automatically resumed.

No playlists, arbitrary searches, paid Hi-Fi, video muxing or mid-stream URL-expiry retry yet. Public cluster availability, quotas and region restrictions are upstream-dependent. Live cluster resolution is untested here because the workspace outbound network allowlist excludes TypeTube and YouTube hosts. Unit/integration tests stub provider and download transports; they do not establish live provider availability.
