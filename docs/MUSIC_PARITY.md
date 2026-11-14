# Music behavior migration

Target reference: the pinned `Videl0` checkout in
[the source inventory](references/Videl0.md). Original Agent implementations are
used; reference source is not copied or imported. This is an implementation
ledger, **not** a claim that the entire reference Music system has been ported.

## Available when voice capability is configured

Agent registers 24 base group-only Music commands plus four saved-playlist commands when PostgreSQL is connected:

`play`, `playnext`, `pause`, `resume`, `skip`, `stop`, `end`, `resetplayer`,
`queue`, `q`, `nowplaying`, `leave`, `loop`, `shuffle`, `clear`, `clearqueue`,
`remove`, `move`, `jump`, `replay`, `volume`, `volumeup`, `volumedown`, `history`.

PostgreSQL adds `saveplaylist`, `playlist`, `playlists`, `deleteplaylist`.

- `/play` accepts a direct media URL or replied Telegram media, not a song-name
  search or a YouTube watch page. `/playnext` uses those same sources and is admin-only.
- `/loop off|one|all` repeats nothing, the current track or the queue. Explicit
  `/skip` overrides repeat-one. Automatic stream completion respects it.
- `/remove <upcoming position>`, `/move <from> <to>` and `/jump <position>` use
  one-based upcoming positions, protecting the current track from list edits.
  Jump changes playback only through the voice engine; failure restores order.
- `/clear` and `/clearqueue` preserve current playback; `/stop`, `/end` and
  `/resetplayer` clear the queue and leave. `/leave` drops stale queue state.
- `/replay` restarts the current source after engine acknowledgement. Expired
  signed URLs can fail; no destructive retry loop is used.
- `/volume <20-200>` and 20-point volume-up/down steps update stored settings
  only after acknowledgement. Without a prior change, 100% is a baseline,
  not a measured remote volume value.
- `/history` contains at most 15 acknowledged titles per retained group, in
  process memory only; it is not Telegram chat history. History and volume
  caches retain at most 200 groups; cleanup removes the affected group's data.
- Queue edits, replay, repeat modes, shuffle and volume require group admin or
  this bot tenant's Owner. Existing transport controls also allow the current
  requester. This does not grant new users moderation permissions.
- Group commands, transport callbacks and stream-end transitions share a
  per-group lock. Different groups do not block one another. Queues cap at
  50 tracks; displays show at most 15 entries. Failed transitions restore the
  local queue, but Telegram effects cannot be made transactionally atomic.
- Global approval, three optional group slots and activation checks still apply.
  Missing voice dependencies or a session register **no** Music commands.

## Remaining command families — not registered as placeholders

These were found by reviewing `videl/modules/__init__.py`, the named module
handlers, `videl/app/routes.py` and the music plugin registrations. Static
extraction alone does not discover every dynamic registration or web feature.

| Reference commands | State / prerequisite |
| --- | --- |
| `vplay`, `cplay`, `cvplay`, `channelplay` | Pending: explicit audio/video mode, linked-channel authorization and destination isolation |
| `autoplay`, `voteskip` | Pending: bounded recommendations; verified membership, quorum and expiry |
| `saveplaylist`, `playlist`, `playlists`, `deleteplaylist` | Implemented with PostgreSQL and the saved-metadata limits below; expired/local/signed sources and automatic idle playback are not supported |
| `seek`, `seekback` | Pending: acknowledged source changes, duration/live-stream checks and engine progress reconciliation |
| `speed`, `speedreset`, `bass`, `bassoff`, `effecton`, `effectoff`, `effects` | Pending: validated FFmpeg filter pipelines, resource bounds and acknowledged live transitions |
| `lyrics` | Pending: configured provider, attribution/licensing and bounded escaped output |
| `song`, `vsong`, `download` | Pending: extractor, SSRF/redirect validation, media rights, bounded downloads and cancellation |
| `restorequeue` | Pending: durable safe upcoming metadata; never automatically replay an interrupted current track |
| `requests`, `dj` | Pending: durable approvals and membership-checked expiring DJ delegation |
| `voicequality`, `voicehealth` | Pending: validated quality profiles and credential-safe detailed voice diagnostics |

The reference's `restart` is a general owner operation; Agent already has its
own owner-only restart command and does not create another Music-owned copy.
The reference's web rooms, lyrics/search callbacks and media cache are separate
features, not hidden support behind the command names above.

## Alive / keep-alive behavior

The reference keep-alive endpoint reports heartbeat age and uptime. Agent now
exposes equivalent original JSON reporting at `/` and `/alive`: bot identity,
version, status, uptime, last-success age and UTC time. No successful Telegram
probe means `starting`, not a fabricated alive heartbeat. Healthy is `alive`;
a down monitor is `stale`. `/health` retains the operational health response;
`/health/live` answers process liveness and `/health/ready` returns 200 only for
a healthy Telegram probe state (503 for starting, degraded or down).

Telegram `/alive` is an alias for the measured `/status` screen, not a worker
command. The existing watchdog remains in charge of Telegram probes and fatal
restart policy. HTTP runs on `0.0.0.0` and `PORT`/`HEALTH_PORT` as before. Nothing
pings itself; this does not defeat Render free-service sleep or replace a paid
always-on worker. The async server can time out under an event-loop stall,
allowing the platform's own liveness check to detect it.

Validation for this increment: **793 tests passed** with disposable PostgreSQL;
compilation, pyflakes and whitespace checks passed. Voice-engine interactions
are mocked in command tests. Actual streaming, linked-channel behavior and
external media providers have not been validated. Stream-end notifications are
serialized per group but do not yet carry per-track generation fencing.

## Saved playlists

All four commands require group admin or this bot tenant's Owner. Names are
1–32 lowercase ASCII letters, digits, underscores or hyphens. Each list belongs
to the authenticated user in the current group and bot tenant; other admins do
not implicitly gain access to that user's lists. Saved metadata lives in the
relational `agent_music_playlists` table, not an unscoped in-memory cache.

`/saveplaylist name` snapshots current plus upcoming tracks and **replaces your
same-named list** here. Maximum: 10 lists per user/group/bot and 20 tracks per
list, with bounded titles and URLs. PostgreSQL serializes quota checks and the
write in one transaction. Lists remain until explicitly deleted; disabling Music
stops execution but does not erase intentionally saved metadata. Automated
retention/group-deletion integration remains open; this is not a hard-expiry store.

Only stable public HTTP(S) URLs are stored. Local Telegram download paths,
embedded credentials, query strings, fragments and control characters are
refused, so signed query URLs cannot accidentally become saved credentials.
Do not save secret URLs: access tokens embedded in path segments cannot be
reliably detected. Playlist listings show names and counts, not source URLs.

Loading validates the entire saved list again, including DNS, then checks current
Music activation and capacity. Start a fresh track with `/play` first; `/playlist
name` only appends upcoming tracks, never starts or replaces playback. All tracks
must fit under the 50-track queue limit or none are added. Loading is serialized
with other same-group Music actions; duplicate explicit loads intentionally add
duplicates. A failed reply does not guarantee that the preceding mutation failed:
check `/queue` before retrying. Saved metadata survives process restarts; current
playback and runtime queues still do not.

URL validation is admission checking, **not** a pinned outbound proxy. Native
streaming retains redirect/DNS-rebinding limitations; DNS revalidation does not
prove that a URL remains safe forever or that its content is playable/licensed.
No extractor or media download is performed while saving/loading metadata.
