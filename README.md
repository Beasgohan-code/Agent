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

Optional, and off by default: `SESSION_STRING` (the user session the voice-chat
player joins with — a bot token cannot join a call, so without it the music
plugin registers no commands at all), `START_IMAGE` (the `/start` picture, a URL
Telegram fetches itself), `OWNER_ID`, `LOG_CHANNEL_ID` and the health/watchdog
knobs listed further down. See `.env.example`.

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


## Rich messages and tables

The UI is built on **Bot API 10.3 rich messages**: the panels are a real `<h2>`,
a real `<table>` and a real `<blockquote>`, rendered by Telegram rather than
drawn in ASCII inside `<pre>`. wzgram ships `send_rich_message`, so this works
with the same bot token as everything else.

Two fallbacks, both automatic:

- if Telegram refuses a rich message, `agent.utils.rich` switches
  `agent.ui.tables.set_rich(False)` for the whole process and every later panel
  is rendered as the monospace `<pre>` grid instead — one refusal, not one
  failure per message;
- the edited screens (`/menu` navigation) always use the monospace grid, because
  Telegram has no `edit_rich_message`: an edit that would have to be re-sent is
  worse than a table without borders.

## Premium

After Videl1: `/premium` shows your tier and what is left today, and the owner
grants it with `/addpremium <user_id> [days]` (`0` = lifetime), removes it with
`/delpremium` and lists it with `/premiumusers`. Premium buys three real
allowances and nothing else:

| Allowance | Free | Premium |
| --- | --- | --- |
| Vault quota | 64 MB | 256 MB |
| Transfers per day | 5 | 50 |
| Encodes per day | 3 | 25 |

They are enforced in `filestore` and `leech` before anything is written or
fetched, the counters reset at midnight UTC, and the state is `data/premium.json`.

## Plugin runtime, by button

`/plugins` is a panel you can press: one styled button per plugin (green when it
is on, grey when it is off, disabled for `ops`), and pressing one detaches or
re-attaches that plugin's handlers in place, then redraws the panel. `/plugin
<slug> on|off` still exists for scripts. `PLUGINS=leech,filestore` narrows a
build — an unselected plugin registers nothing at all, it does not half-work,
and `PLUGINS=*` (the default) registers everything compiled in.

Buttons use the Bot API 10.3 `style` field (primary / success / danger) and the
info screen carries a `copy_text` button, so the user id can be pasted without
selecting text on a phone.

## Layout

Every ported plugin is a package, not a single file: `MANIFEST` and the handlers
in `__init__.py`, the parts worth testing on their own beside it —
`filestore/vault.py`, `leech/transfer.py`, `music/{queue,sources}.py`,
`reports/queue.py`, `postmaker/templates.py`, `security/verify.py`,
`premium/limits.py`.

## Credits

The command surfaces, defaults and layouts in this bot come from the projects in
[`docs/CREDITS.md`](docs/CREDITS.md) — Meikoagent, Videl0/Videl1, CBML, WZML-X,
Multi-FileStoreBot, LINK-SHAREBOT, ENCODING-BOT, save-restricted-content-bot,
Playeon, plus richgram and wzgram at runtime. `/about` prints the same list, with
the licences that decided what could be reused and what was only read.

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

The command surface follows **Meikoagent** and **Videl1**: the same argument
shapes and defaults (a mute is 600 s, a purge is 10 messages), plus the group
panel a complete management bot needs. Every command is wired to something real
— none is a stub.

| Area | Commands |
| --- | --- |
| Core | `/start` `/help` `/menu` `/about` `/status` `/cancel` `/ping` `/owner` |
| Moderation (groups) | `/warn` `/warnings` `/warns` `/unwarn` `/mute` `/unmute` `/kick` `/ban` `/unban` `/purge` `/note` `/trust` `/antispam` `/modlog` |
| Group management (groups) | `/settings` `/rules` `/setrules` `/pin` `/unpin` `/admins` `/warnlimit` `/resetwarns` `/lockdown` |
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

### Group management

`/settings` is the panel: anti-spam policy, flood limit, link and invite rules,
keyword count, warn threshold, greetings, filter count, rules, trusted members
and the log channel — all read live from `data/chats.json` in one table. Nothing
in it is a stored copy of state that lives somewhere else.

| Command | What it does | Where it comes from |
| --- | --- | --- |
| `/settings` | Live settings panel for this group | Videl1 has `/settings`; this one is per-group |
| `/rules` `/setrules` | Publish and read the group's rules | ours (Videl1 keeps rules in its database, not in a command) |
| `/pin` `/unpin` | Pin a replied message, or `/unpin all` | ours |
| `/admins` | Administrator list read from Telegram | Videl1's `/admins` is bot staff; this is group admins |
| `/warnlimit` | Warnings needed to escalate, and the action | ours — and it is enforced |
| `/resetwarns` | Clear every active warning for a member | ours |
| `/lockdown` | Restrict the group to administrators, `/lockdown off` lifts it | Meikoagent's security plugin ships `lockdown` |

**`/warnlimit` is not decoration.** `/warn` reads the threshold, and when a
member reaches it the configured action (`mute` by default, or `kick`/`ban`) is
applied and logged as `warnlimit:<action>`. If the bot lacks the right to do it,
the reply says `Escalation failed: <ErrorType>` — a warning report never claims
an action that did not happen. `DEFAULT_WARN_LIMIT` is 3; `/warnlimit off`
disables escalation entirely.

Every one of these commands checks the caller's rights first (the specific
privilege Telegram requires, not just "is an admin") and refuses to act on an
administrator.

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

## The command menu

On start the bot publishes its command list to Telegram, split by scope: 30
private/anywhere commands in the default scope and 29 group-only ones
(moderation, group management, filters, greetings) in the group scope, so nobody
sees `/ban` in a DM. The list is built from the live registry, so a disabled plugin disappears
from the menu at the same time as it disappears from the dispatcher.

`/menubutton` does not exist because it does not need to: the chat menu button is
reset to the command list automatically. **The Bot API cannot hide the menu
button entirely** — the options are a web-app launcher, the command list, or the
default. "Deleted" here means it no longer points at anything custom, and
`SYNC_COMMANDS=0` skips the whole step.

## Tables, headings and rich output

A Telegram message has bold, italic, code, quotes, links — and no table. So a
table that actually lines up has to be monospace text inside `<pre>`, which is
what `agent/ui/tables.py` builds:

```
┌────────────┬─────────────┬──────┐
│ Plugin     │ State       │ Cmds │
├────────────┼─────────────┼──────┤
│ ops        │ on (locked) │    8 │
│ moderation │ on          │   14 │
└────────────┴─────────────┴──────┘
```

Three details make it work rather than almost work:

* **Width is display width.** East-Asian characters and emoji take two columns
  in a monospace font, so `len()` would drift. `text_width()` counts them and
  combining marks as zero.
* **Cells are escaped, never formatted.** Telegram does not parse nested tags
  inside `<pre>`, so a tag in a cell is stripped instead of shown literally.
* **Whitespace in `<pre>` survives normalisation.** richgram's rich→HTML
  normaliser collapses runs of spaces, which is right for prose and fatal for a
  grid — it squeezes every column to two spaces. `to_safe_html()` lifts `<pre>`
  blocks out before normalising and puts them back untouched. That is the bug
  that made the first version of these panels look broken.

`docs/UI_PREVIEW.md` is generated by running the real handlers against a fake
client, so it shows the actual layout rather than a mock-up.

Tables are used where there is real grid data (`/plugins`, `/settings`,
`/admins`, `/warnings`, `/modlog`, `/antispam`, `/events`, `/watchdog`,
`/status`, `/links`, `/filters`, `/encinfo`, `/encpreset`). Prose stays prose:
`/help` is a reference, and truncating the sentence that explains a command to
fit a column would defeat it. Emoji are kept *out* of cells for the same width
reason and stay in the headings, notes and footers around them.

**The client now runs with `parse_mode=HTML`.** Without it pyrogram sends the
markup as literal text, so every module reply appeared as `<b>Member muted</b>`
with the tags visible — the reason plain answers looked wrong.

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

`/plugins` is a table of every module with its state and command count;
`/plugin <slug> off` detaches that module's
handlers from the dispatcher — not a flag that later code might forget to check
— and persists the choice, so it stays off across restarts. `ops` cannot disable
itself. Watchers are detached too, so a disabled `moderation` stops enforcing
anti-spam rather than quietly continuing.

## Where each reference project went

| Reference | Contributed here | Still missing, and what it needs |
| --- | --- | --- |
| **Meikoagent** | the command surface, plugin lifecycle, role checks, `/lockdown` | its AI/analytics/reports plugins need an API key and a database |
| **CBML** / **WZML-X** | filters, welcome/goodbye, `/id` `/info` `/time` | mirror/leech need aria2, rclone, Google credentials and MongoDB |
| **ENCODING-BOT** | the encoder module (real FFmpeg) | link downloads and cloud uploads need downloaders and storage creds |
| **LINK-SHAREBOT** | `/genlink` and the signed-link store | `/batch` needs a multi-file queue; `/broadcast` needs a users table |
| **Multi-FileStoreBot** | the shared file store behind `/genlink`/`/links` | per-user bots need one isolated client per token — not safe in-process |
| **playeon** | nothing yet | it is a streaming indexer: needs a web server and a file database |
| **save-restricted-content-bot** | nothing | it works by session-based access to protected content, which the project rules forbid |
| **Videl1** | keep-alive, watchdog, **single-instance lease, `/restart`**, `/settings` and `/admins` naming | — |
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

## Plugin runtime, by button

`/plugins` is a panel you can press: one styled button per plugin (green when it
is on, grey when it is off, disabled for `ops`), and pressing one detaches or
re-attaches that plugin's handlers in place, then redraws the panel. `/plugin
<slug> on|off` still exists for scripts. `PLUGINS=leech,filestore` narrows a
build — an unselected plugin registers nothing at all, it does not half-work,
and `PLUGINS=*` (the default) registers everything compiled in.

Buttons use the Bot API 10.3 `style` field (primary / success / danger) and the
info screen carries a `copy_text` button, so the user id can be pasted without
selecting text on a phone.

## Layout

```
start.py              entry point ("python start.py")
agent/config.py       environment loading + validation
agent/bot.py          client lifecycle, handler wiring, signals
agent/handlers/       commands (/start, /help) and callbacks
agent/ui/             theme, screens, tables, premium emoji, inline keyboards
agent/utils/sender.py delivery with HTML + custom-emoji fallbacks
agent/platform/        plugin registry, job queue, storage, signed links
agent/modules/        core, moderation, group, filters, welcome, encoder,
                      linkshare, renamer, utilities, ops
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
