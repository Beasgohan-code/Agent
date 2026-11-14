# Agent

A Telegram bot. Phase 1: `/start`, `/help`, `/ping`, user profile, inline
keyboards and callback navigation. Built on **wzgram** (client) and **richgram** (formatting).

## Environment

Only three variables, all required:

| Variable    | Where to get it                              |
| ----------- | -------------------------------------------- |
| `BOT_TOKEN` | [@BotFather](https://t.me/BotFather)         |
| `API_ID`    | [my.telegram.org](https://my.telegram.org) → API development tools |
| `API_HASH`  | same page as `API_ID`                        |

Nothing else needs to be set. No secrets belong in the repo or the image.

## Run locally

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
pip install --no-deps richgram==0.2.0     # see "richgram" note below

cp .env.example .env                      # then fill in the three values
python start.py                           # long polling
python start.py --check                   # validate config + wiring, no network
```

## Run with Docker

```bash
docker build -t agent .
docker run --rm -e BOT_TOKEN=... -e API_ID=... -e API_HASH=... agent
```

## Deploy on Render

The included `render.yaml` creates a **Background Worker** with
`runtime: docker`, so no HTTP server or keep-alive is involved. Either apply
the Blueprint or create the worker manually:

- Type: **Background Worker**
- Runtime: **Docker** (`./Dockerfile`)
- Start command: `python start.py` (already the image `CMD`)
- Environment: `BOT_TOKEN`, `API_ID`, `API_HASH`

Render sends `SIGTERM` on deploy/restart; the bot turns it into a graceful
disconnect.


## Health & watchdog

Modelled on Videl1's keep-alive and Meikoagent's watchdog, with the parts that
get accounts suspended removed.

**What it does**

- Probes Telegram (`getMe`) on a timer and records latency, failures and the
  last error.
- Derives a state: `starting` → `healthy` / `degraded` / `down`.
  Down = 3 consecutive failures *or* no successful probe for
  `WATCHDOG_INTERVAL_SECONDS × 10`.
- Reconnects a dropped socket before pinging.
- After `WATCHDOG_FATAL_AFTER` (default 5) failed probes it logs a CRITICAL
  line, disconnects cleanly and exits **1** so Docker/Render restarts the
  container. Rebuilding the client in-place is avoided on purpose — two update
  streams would double every reply.

**What it deliberately does *not* do**

- **No self-ping.** Nothing calls the bot's own endpoint to fake traffic. That
  is the practice your hosting terms punish and Videl1's `self_ping_loop` does.
- **No HTTP server by default.** A polling bot on a Background Worker needs
  none. Set `HEALTH_PORT` (or deploy as a web service, where the platform sets
  `PORT`) to expose:

  | Route | Purpose |
  | --- | --- |
  | `GET /health` | JSON state, uptime, latency, failures, version. **503** when down, so the platform's own health check restarts the container |
  | `GET /health/live` | `ok` — process liveness only, so a slow probe never kills a healthy container |
  | `GET /` | one-line banner |

**Checking the ping**

Two ways, depending on the deployment shape:

| Where | How | What you get |
| --- | --- | --- |
| Telegram | send `/ping` | state, uptime, Telegram latency, probe/failure counts, last update, last error |
| HTTP | `curl https://<service>/health` | the same numbers as JSON (needs `HEALTH_PORT` or a web service) |

`/ping` works on a Background Worker, where no port is exposed — that is the
reason it exists alongside the HTTP endpoint.

**Tuning (all optional)**

```bash
HEALTH_PORT=8080              # 0 = no endpoint
WATCHDOG_INTERVAL_SECONDS=30
WATCHDOG_TIMEOUT_SECONDS=20
WATCHDOG_FATAL_AFTER=5
```

Not implemented yet: Videl1's cross-instance lease (it needs shared storage to
be meaningful — see the no-database rule for this phase).

## Commands

The command surface follows **Meikoagent**: the same 21 commands, the same
argument shapes, the same defaults (a mute is 600 s, a purge is 10 messages).
Every one is wired to something real — none is a stub.

| Area | Commands |
| --- | --- |
| Core | `/start` `/help` `/menu` `/about` `/status` `/cancel` `/ping` `/owner` |
| Moderation (groups) | `/warn` `/warnings` `/warns` `/unwarn` `/mute` `/unmute` `/kick` `/ban` `/unban` `/purge` `/note` `/trust` `/antispam` `/modlog` |
| Filters (groups) | `/filter` `/filters` `/stopfilter` |
| Welcome (groups) | `/setwelcome` `/welcome` `/goodbye` |
| Utilities | `/id` `/info` `/time` |
| Renamer | `/autorename` `/rename` `/testrename` `/clean` |
| Operations (owner) | `/restart` `/watchdog` `/plugins` `/plugin` `/events` `/setlog` `/unsetlog` `/log` |
| Encoding | `/encode` `/encinfo` `/encpreset` `/enccancel` |
| Sharing | `/genlink` `/links` `/revoke` |

Aliases follow the reference too: `/h` for help, `/restart_bot` for start,
`/warns` for warnings.

Where this deliberately differs, because copying the reference would have meant
shipping a fake control:

* **`/cancel`** there answers "Cancelled" without cancelling anything. Here it
  cancels your real jobs and reports the count.
* **`/status`** reports this process's live counters (uptime, probes, failures,
  queued jobs) rather than placeholders.
* **`/antispam`** stores a policy *and* ships the watcher that enforces it —
  flood, duplicates, links, invites and keywords, with a real action. Settings
  that nothing reads would be decoration.
* **`/owner`** needs `OWNER_ID`; without it the command says so instead of
  guessing an owner. It is optional, like every other knob here.
* Every moderation command checks the caller's admin rights (and the specific
  privilege the action needs) plus that the target is not an administrator.

Moderation state (warnings, notes, trust, policy, audit log) lives in
`data/chats.json`. Chat message text is never stored — the anti-spam tracker
keeps a window in memory only.

Untested against live Telegram: there is no session or group in this sandbox,
so moderation is covered by tests that drive the handlers against a fake client
and assert the exact pyrogram calls. That is stated plainly rather than claimed
as deployment-tested.

## Keep-alive, one instance, restart (Videl1)

Videl1's lesson is that two live copies of one token answer every update twice.
Deploys overlap — Render and Railway start the new container before stopping the
old one — so "we deploy carefully" is not protection.

* **Lease.** `agent/platform/instance.py` takes a lease before connecting; a
  departing deploy releases it, so `/restart` is an immediate handover rather
  than a 60-second standoff. Videl1 keeps this in MongoDB; this bot has no
  database, so the same contract lives in a JSON file — owner, expiry,
  heartbeat, atomic takeover.
* **Heartbeat.** If another process takes the lease (this one was frozen past
  the TTL), the heartbeat stops the bot instead of double-serving.
* **Refusing is a feature.** When the lease cannot be taken, the process exits
  without connecting. That is the honest outcome; serving anyway is not.
* **`/watchdog`** reports the lease, uptime, latency, running jobs and disabled
  plugins; `/watchdog run` sweeps stale encoder working directories and purges
  expired links; `/watchdog clean` also prunes stored files older than 7 days.
  It reports the bytes it actually removed.
* **`/restart`** stops the process so its supervisor restarts it, after
  refusing while jobs are running unless you pass `force`. It says plainly that
  an unsupervised process will simply stay down.
* **`/health`** now carries the lease state, disabled plugins and event count,
  so a platform health check can see what the bot sees.

## Premium emoji and the UI layer

Screens are rich markup composed with **richgram**'s block builders and delivered
through its rich→HTML normaliser. Glyphs upgrade to custom emoji when a vetted id
exists:

* Ids come from **Videl0**'s curated map (`agent/ui/premium.py` documents the
  four packs: NewsEmoji, Telegram iOS Icons, @rijif, SoLo_HaMiD). None are
  invented — a fabricated id renders a broken glyph, which is worse than plain
  unicode.
* Videl0's own caveat holds: *ids alone do not grant Premium rendering*. If
  Telegram rejects the entity, the sender retries once with plain unicode and
  keeps working.
* `USE_PREMIUM_EMOJI=0` disables the layer entirely, as in Videl0.
* Glyphs with no vetted id (wave, rocket, user, id, help, trash, clock) stay
  unicode on purpose.

## The log channel (Videl1's botlog)

Everything notable is posted to one channel, tagged so it is searchable:

| Tag | When |
| --- | --- |
| `#BotStarted` / `#BotStopped` | process connect and shutdown |
| `#NewUser` / `#Start` | first-ever `/start`, then returning visits |
| `#NewGroup` | the bot was added to a group |
| `#Restart` / `#Plugin` / `#Watchdog` / `#Error` | operations, plugin switches, sweeps, handler errors |

`/setlog <channel id>`, or run `/setlog here` inside the channel. The target is
verified with `get_chat` first, so a channel the bot cannot reach is refused
rather than silently stored. With no channel set, events fall back to the
owner's DM — and with no owner either, `/log` says "nowhere yet" instead of
pretending.

`/setlog`, `/unsetlog` and `/log` are ours; Videl1 configures its channel purely
through `LOG_CHANNEL`. The environment variable still works and is overridden by
the command.

## Plugins you can switch at runtime

`/plugins` lists every module; `/plugin <slug> off` detaches that module's
handlers from the dispatcher — not a flag that later code might forget to check
— and persists the choice, so it stays off across restarts. `ops` cannot disable
itself. Watchers are detached too, so a disabled `moderation` stops enforcing
anti-spam rather than quietly continuing.

## Where each reference project went

| Reference | Contributed here | Still missing, and what it needs |
| --- | --- | --- |
| **Meikoagent** | the 21-command surface, plugin lifecycle, role checks | its AI/analytics/reports plugins need an API key and a database |
| **CBML** / **WZML-X** | filters, welcome/goodbye, `/id` `/info` `/time` | mirror/leech need aria2, rclone, Google credentials and MongoDB |
| **ENCODING-BOT** | the encoder module (real FFmpeg) | link downloads and cloud uploads need downloaders and storage creds |
| **LINK-SHAREBOT** | `/genlink` and the signed-link store | `/batch` needs a multi-file queue; `/broadcast` needs a users table |
| **Multi-FileStoreBot** | the shared file store behind `/genlink`/`/links` | per-user bots need one isolated client per token — not safe in-process |
| **playeon** | nothing yet | it is a streaming indexer: needs a web server and a file database |
| **save-restricted-content-bot** | nothing | it works by session-based access to protected content, which the project rules forbid |
| **Videl1** | keep-alive, watchdog, **single-instance lease, `/restart`** | — |
| **wzgram** | the client itself | — |

Nothing in the "still missing" column is registered as a command. A command
that cannot do its job is worse than a missing one.

## Deployment notes

* The image runs unprivileged (uid 10001), so `/app/data` is created and owned
  by that user in the Dockerfile. Without it, the very first write fails.
* If the data directory is still not writable, startup resolves a fallback
  under the temp directory and **says so** — stored files, links and settings
  then do not survive a restart. It does not pretend the volume is fine.
* A lease that cannot be written degrades to running without single-instance
  protection instead of crashing the deploy; `/watchdog` and `/health` report
  `degraded` when that happens.
* Logs carry the token prefix and a mask, never the secret, and never the
  `api_id`.

## Layout

```
start.py              entry point ("python start.py")
agent/config.py       environment loading + validation
agent/bot.py          client lifecycle, handler wiring, signals
agent/handlers/       commands (/start, /help) and callbacks
agent/ui/             theme, screens, inline keyboards
agent/utils/sender.py delivery with HTML + custom-emoji fallbacks
agent/platform/        plugin registry, job queue, storage, signed links
agent/modules/        encoder, linkshare (real handlers)
tests/                config, UI and bot tests
```

## Notes

**richgram is installed with `--no-deps`.** Its only runtime dependency is
`kurigram`, which ships its own top-level `pyrogram` package and overwrites
wzgram's files (observed: `pyrogram.__version__` became `2.2.27`). Installing
it without dependencies lets wzgram own `pyrogram`, and richgram still works
because all it needs is that package.

**richgram was renamed upstream.** `github.com/Badmunda05/richgram` now
redirects to `Badmunda05/nextgram`; `richgram` 0.2.0 on PyPI is the last
release under the old name and is what this project pins. `nextgram` 0.9.0 is
the actively maintained successor — a reasonable migration target later.

**Custom emoji IDs are not shipped.** Inventing one renders a broken glyph.
Add verified IDs to `CUSTOM_EMOJI_IDS` in `agent/ui/theme.py`; until then every
glyph uses its unicode fallback, and a rejection by Telegram is downgraded
automatically.
