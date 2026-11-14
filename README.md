# Agent

A Telegram bot that does three jobs and does them with the same machinery: it
keeps files, it runs a group, and it plays music into a voice chat. One job
queue, one file store, one link signer and one settings panel sit underneath, so
a file saved by one command can be fetched, renamed, linked and re-sent by
another.

Sixty-nine commands register in a default deployment — sixty-one without a
voice session, because the music plugin refuses to register commands it cannot
run. Everything is a plugin, so
a leaner build is a one-line change (`PLUGINS=…`), and every panel you see is
built from the live state of this process rather than a stored copy of it.

## Environment

| Variable | Required | What it does |
| --- | --- | --- |
| `BOT_TOKEN` | yes | From [@BotFather](https://t.me/BotFather). |
| `API_ID` / `API_HASH` | yes | From [my.telegram.org](https://my.telegram.org). |
| `OWNER_ID` | recommended | Unlocks `/owner`, `/plugins`, `/restart`, `/clonestats`. |
| `PLUGINS` | no | Which plugins register. Default is the nine below; `*` is everything. |
| `SESSION_STRING` | for music | A user session is the only thing that can join a group call. |
| `LOG_CHANNEL` | no | Where the bot posts its event log; without it, the owner's DM. |
| `DATA_DIR` | no | Where local state (vault files, and JSON stores without a database) lives. Default `data`. |
| `DATABASE_URL` | no | PostgreSQL DSN. Set it and every store is kept in the database. |
| `CLONE_LIMIT` | no | How many clones this deployment will run at once. Default `5`. |
| `START_IMAGE` | no | Picture above `/start`; `0` keeps the text only. |
| `HEALTH_PORT` / `PORT` | no | Exposes `/health` and `/health/live`. |
| `USE_PREMIUM_EMOJI` | no | `0` disables custom emoji and uses plain glyphs. |

`SYNC_COMMANDS`, `WATCHDOG_*` and `HEARTBEAT_*` tune the menu, the watchdog and
the instance lease; `.env.example` lists them all with their defaults.

## Run locally

```sh
python -m venv .venv && . .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env      # fill BOT_TOKEN, API_ID, API_HASH
python -m agent
```

Docker, Render and a plain VPS all work from the same image; the health endpoint
turns on by itself when the platform provides a port.

## What the screens look like

`/start` is three things: who the bot is, a table with the live command count,
and three commands worth trying. `/help` is the full reference, split into
sections that only list commands this deployment actually registered — a plugin
that could not start (music without a session) is absent, not a dead button.

Panels that answer a question (`/about`, `/status`, `/owner`, `/plans`) end with
a row back to the menu, so reading one is never a dead end. Buttons carry Bot API
10.3 styles — green for "do this", grey for "this is off", red for "this
deletes" — and the info screen has a `copy_text` button so a user id can be
pasted without selecting text on a phone.

## Plugins

A plugin is a folder: the manifest and its handlers in `__init__.py`, helpers
beside it. Every module is compiled in; which ones *register* is the deployment's
choice.

The default build registers nine: `ops` and `core` (the shell — controls and
front door, always on and never switchable off), plus `filestore`, `leech`,
`linkshare`, `moderation`, `music`, `postmaker`, `renamer` and `clone`.

The others — `encoder`, `filters`, `group`, `premium`, `reports`, `security`,
`utilities`, `welcome` — register nothing until a deployment names them:
`PLUGINS=encoder,security`. An unselected plugin has no commands, no watchers and
no menu entries, so it cannot half-work. `PLUGINS=*` turns everything on.

`/plugins` is a panel you can press: one button per plugin, green when it is on,
grey when it is off, disabled for the shell. Pressing one detaches or re-attaches
that plugin's handlers in place and redraws the panel; `/plugin <slug> on|off`
does the same from a script. A plugin that is enabled but registered nothing says
why — `music` without `SESSION_STRING`, `encoder` without ffmpeg.

## Clones

`/clone <bot token>` runs this bot on another token: its own client, its own
session name, its own data directory (`data/clones/<bot_id>`), built from the
same code. It behaves like this bot, because it *is* this bot.

* `/mybots` is the control panel — every clone you own, with Start, Stop and
  Delete buttons; a press edits the panel in place.
* `/delclone <bot id | @username>` removes the record and stops the client.
* `/clonestats` is the owner's view: how many clones exist, how many are running,
  and what the deployment's ceiling is.

Limits are real: one clone on a free account, three with premium (`/premium`),
and `CLONE_LIMIT` caps the whole deployment. A clone does **not** inherit
`OWNER_ID`, so adding one never hands anyone owner commands, and its vault is its
own — two clones cannot read each other's files. Clones that were running are
started again when the process restarts; a token Telegram refuses is reported
with Telegram's own sentence and leaves no record behind.

## Vault, links, captions

| Command | What it does |
| --- | --- |
| `/fsave` | Keep a replied file in your vault (20 MB cap — the Bot API's, not ours). |
| `/batch [n]` | Save a run of consecutive files, starting at the replied one. |
| `/files`, `/check <id>`, `/get <id>`, `/del <id>` | List, inspect, re-send and delete vault entries. |
| `/genlink`, `/links`, `/revoke` | Signed, expiring, revocable links to a file you own. |
| `/setcaption`, `/viewcaption`, `/delcaption` | The caption attached to files this chat receives; `{name}`, `{stem}`, `{size}`. |
| `/setthumb`, `/viewthumb`, `/delthumb` | The thumbnail attached to those files. |

A saved caption or thumbnail is applied by the sender (`/get`, `/leech`,
`/rename`), so it is a setting with an effect rather than a stored string.

## Downloads, encoding, music

`/leech <url>` streams an HTTP(S) file to disk and sends it; `/mirror` also keeps
it in the vault. URLs are checked before a request is made — http/https only, no
embedded credentials, no address that only resolves from inside the host — and
the transfers are ordinary jobs, so `/cancel` stops them and `/tasklist` shows
them.

The encoder plugin runs real FFmpeg (system binary, or the `imageio-ffmpeg`
wheel): `/encode` with presets and live progress, `/compress` for the fast
preset by name, `/sample [start] [length]` for a stream-copied clip, `/toaudio`
for the audio track as MP3, `/screens` for a 3×3 contact sheet, and `/encinfo`
to probe what a file actually is. Every tool feeds the same job queue, so
`/enccancel` kills the child process instead of politely forgetting it, and every
produced file comes back with the chat's caption and thumbnail attached. The music player drives `pytgcalls` with a Telethon
user session, and is gated on capability: without `SESSION_STRING` the module
registers zero commands and `/plugins` says why. `/play` and `/nowplaying` answer
with a card, and the card is the remote — pause/resume, skip, and a red
stop-and-clear, for staff or whoever queued the track.

## Where state lives

Two modes, same behaviour:

* **JSON files** (`data/`) by default — one process, small state, no server to run.
* **PostgreSQL** when `DATABASE_URL` is set. Each store becomes one row in
  `agent_documents` (`name`, `value jsonb`), and the single-instance lease becomes
  a row in `agent_lease`, so two containers finally see each other. The schema is
  applied on boot; there is nothing to migrate by hand.

Writes are queued and flushed by one background task, so a handler never waits on
the network, and the last value for a document wins — a store never writes a
partial one. If the database is missing, unreachable, or `asyncpg` is not
installed, the bot logs one warning and keeps running on its files: losing the
database must not take the bot down. `/db` (owner) states which backend is live,
the host, how many documents are loaded and whether writes are queued; `/status`
carries the same answer in one row.

**The vault is the exception.** Files live on the host's disk under `DATA_DIR`;
the database holds the index and the links. A multi-instance deployment that
wants shared *files* needs object storage, and this bot does not pretend
otherwise.

## Premium

Premium raises three numbers and hides nothing:

| Allowance | Free | Premium |
| --- | --- | --- |
| Vault quota | 64 MB | 256 MB |
| Transfers per day | 5 | 50 |
| Encodes per day | 3 | 25 |
| Clones | 1 | 3 |

`/premium` shows your tier and what is left today, `/plans` compares the two, and
`/myplan` is the one-screen version. The owner grants it with `/addpremium <id>
[days]` (`0` = lifetime) and takes it away with `/delpremium`. Counters reset at
midnight UTC; enforcement lives in the vault, the leech queue and the encoder,
so the panel can never quote a limit nothing applies.

## Running a group

Moderation (`/warn`, `/mute`, `/kick`, `/ban`, `/purge`, `/antispam`, `/modlog`)
checks the caller's rights **and** that the target is not an administrator before
it calls Telegram. `/settings` shows every per-group setting this bot actually
enforces, read live from the chat store. Greetings, filters, rules, reports,
posts and member verification are their own plugins and can be switched on with
`PLUGINS=` — or at runtime, from the panel, if they are compiled in.

## One instance, a watchdog, a log

Two processes polling one token answer every update twice, so a copy takes a
lease before connecting, renews it with a heartbeat, and releases it on
shutdown — which is also what makes `/restart` a handover rather than a
60-second standoff. The watchdog probes Telegram on a timer and asks the
supervisor to restart when the link stays down; it never pings the bot's own
endpoint to fake liveness.

Every notable event (new user, new group, plugin toggled, restart, error) is
posted to `LOG_CHANNEL` with a searchable hashtag, or to the owner's DM when no
channel is set. `/setlog`, `/unsetlog` and `/log` manage it.

## Layout

```
agent/
  bot.py            client lifecycle, handler wiring, clones, lease
  config.py         environment → frozen Settings
  handlers/         /start, /help, /ping and the callback router
  modules/          one folder per plugin
  platform/         queues, storage, links, chats, premium, attachments, …
  ui/               screens, tables, keyboards, theme
  utils/            rich delivery and the sender
tests/              the suite; every module is testable without Telegram
```

```sh
pytest -q                      # 430 tests
python -m pyflakes agent tests # no unused names
```

State is JSON on disk (`data/`), never a database: the surface is small enough
that a schema and a migration tool would be overhead, and the files are easy to
inspect and back up.
