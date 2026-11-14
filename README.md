# Agent

A professional Telegram group-management bot with mandatory moderation and
safety systems. Music, FileStore, Encoder and other tools are optional modules.

The shell plus moderation, group settings, filters, onboarding, reports and
verification always register, even with a narrow `PLUGINS` setting. They cannot
be disabled through the plugin panel or restored as disabled from old state.
Individual rules remain configurable by group; verification is off by default.

**In progress:** Owner-approved optional catalog, three atomic plugin slots per
group, group-scoped plugin teardown and an integrated Group Control Center.
The existing plugin panel still controls optional modules deployment-wide;
it is not yet the per-group activation UI. The 210-feature brief is a target,
not a claim of implemented coverage. See [the architecture audit](docs/GROUP_MANAGEMENT.md).

## Environment

| Variable | Required | What it does |
| --- | --- | --- |
| `BOT_TOKEN` | yes | From [@BotFather](https://t.me/BotFather). |
| `API_ID` / `API_HASH` | yes | From [my.telegram.org](https://my.telegram.org). |
| `OWNER_ID` | recommended | Unlocks `/owner`, `/plugins`, `/restart`, `/clonestats`. |
| `PLUGINS` | no | Which optional modules register; mandatory group core is always included. `*` includes all modules. |
| `SESSION_STRING` | for music | A user session is the only thing that can join a group call. |
| `LOG_CHANNEL` | no | Where the bot posts its event log; without it, the owner's DM. |
| `DATA_DIR` | no | Where local state (vault files, and JSON stores without a database) lives. Default `data`. |
| `DATABASE_URL` | no | PostgreSQL DSN. Set it and every store is kept in the database, scoped per bot. |
| `TOKEN_KEY` | no | Encrypts clone tokens at rest (Fernet). Unset ⇒ plaintext, announced. |
| `DB_REQUIRED` | no | `1` makes an unreachable `DATABASE_URL` a startup failure. |
| `STORAGE_CHANNEL` | no | A private channel id vault files are archived into (durable bytes). |
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

Every panel is a **rich message**: a real heading over a real table (Bot API
10.3), not a table drawn out of box characters. Tapping a button edits that same
message in place — `edit_message_text(rich_text=…)` keeps the native table, so
navigation does not downgrade the screen — and when Telegram or the client
cannot take a rich message, `utils/rich.py` redraws the table as an aligned
`<pre>` grid instead of flattening it into one run-on line. `/help` is a table of
sections with a count for each, each section is a table of commands with the
sentence behind each one, and `/help <command>` opens that command's own page
(the description, the section it belongs to, and whether this deployment has it).
`docs/UI_PREVIEW.md` is generated from the real handlers.

Panels that answer a question (`/about`, `/status`, `/owner`, `/plans`) end with
a row back to the menu, so reading one is never a dead end. Buttons carry Bot API
10.3 styles — green for "do this", grey for "this is off", red for "this
deletes" — and the info screen has a `copy_text` button so a user id can be
pasted without selecting text on a phone.

## Plugins

A plugin is a folder: the manifest and its handlers in `__init__.py`, helpers
beside it. The mandatory modules are `ops`, `core`, `moderation`, `group`,
`filters`, `welcome`, `reports` and `security`. They always register.

Default optional modules are `filestore`, `leech`, `linkshare`, `music`,
`postmaker`, `renamer` and `clone`. `encoder`, `premium` and `utilities` are
available through `PLUGINS`. An unselected optional module has no commands or
watchers. `PLUGINS=*` includes everything compiled in.

`/plugins` is a panel you can press: one button per plugin, green when it is on,
grey when it is off, locked for the shell and mandatory group core. Pressing one detaches or re-attaches
that plugin's handlers in place and redraws the panel; `/plugin <slug> on|off`
does the same from a script. A plugin that is enabled but registered nothing says
why — `music` without `SESSION_STRING`, `encoder` without ffmpeg.

## Optional plugin access and third-party code

Code installation approval is distinct from permission to use a plugin in a
group. **Third-party Python execution is disabled.** Source inspection and digest
approval are not sandboxes; neither the startup path nor `installer.load()` will
execute installed code. Built-in modules remain available through the existing
runtime. No promotional upstream branding is added.

Local staging and review APIs remain for inspection only. Symbolic links and
unsafe manifest paths are refused; activation rechecks staged source bytes.
A future external runtime needs an actual capability-scoped process boundary.

`platform/plugin_access.py` implements the PostgreSQL permission service:
Owner approval, per-group activation (three slots), configuration, history and
cleanup-pending resource records. Approval is rechecked under a catalog row lock;
slot reservation uses a group-specific transaction-scoped advisory lock. There
is no file fallback. This service is **not yet wired into the Telegram plugin
panel, every execution boundary or runtime task teardown**. The three-slot
product behavior is therefore not yet released end-to-end.

## Clones

`/clone <bot token> [profile]` runs this bot on another token: its own client,
its own session name, its own data directory (`data/clones/<bot_id>`), its own
database rows, built from the same code — with the plugins its **profile** names.

| Profile | What it registers |
| --- | --- |
| `standard` (default) | this deployment's `PLUGINS` — the clone behaves like the bot |
| `files` | file store, leech, links, rename, post only |
| `tiny` | `/start`, `/help`, `/menu` and nothing that touches files |

`ops` and `clone` are stripped from every restricted profile: a clone must not
reach this deployment's controls, and a clone must never mint another clone.

* `/mybots` is the control panel — every clone you own, with Start, Stop, Profile
  and Delete buttons; a press edits the panel in place. Choosing a profile
  restarts a running clone so it takes effect.
* `/delclone <bot id | @username>` removes the record and stops the client.
* `/clonestats` is the owner's view: how many clones exist, how many are running,
  and what the deployment's ceiling is.

### A clone has a state, not a boolean

`is_running` answered the wrong question: it could not tell a revoked token from
a crash from a deliberate stop. Every worker now carries a real state —
`queued → validating → starting → running`, with `degraded` for a client that is
connected but cannot be named, `stopping → stopped` for an orderly shutdown, and
`failed` with Telegram's own sentence attached. Impossible transitions raise
instead of being absorbed.

A supervisor task looks after the live clients for the life of the process: a
clone that drops its connection is marked degraded, stopped, and started again
with a capped backoff (15s doubling to 10 minutes, five attempts), so a revoked
token stops being retried and a transient blip recovers on its own. `/mybots`
shows the state in a column, prints the reason under the table for anything
failed, and `/clonestats` counts them.

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
| `/genlink [hours] [uses]` | Store the replied file and answer with a share link (deep link + copy button). |
| `/share <id> [hours] [uses]` | The same, for a file already in your vault — no second copy. |
| `/links`, `/revoke` | Every live link with the uses and hours it has left; revoke by token or button. |
| `/setcaption`, `/viewcaption`, `/delcaption` | The caption attached to files this chat receives; `{name}`, `{stem}`, `{size}`. |
| `/setthumb`, `/viewthumb`, `/delthumb` | The thumbnail attached to those files. |

A saved caption or thumbnail is applied by the sender (`/get`, `/leech`,
`/rename`), so it is a setting with an effect rather than a stored string.

### A share link is a workflow, not a string

`t.me/<bot>?start=link_<token>` is a real deep link: whoever opens it lands on
`/start` with a payload, `agent.platform.deeplinks` hands that payload to the
module that owns the `link` prefix, and the file arrives in the chat — no command
to type. The order of checks is fixed and each outcome has its own sentence:
signature, revocation, expiry, then the use cap. A link with `uses` set is
`consume`d *before* delivery, so a link that allows five downloads delivers five
and then says it is used up.

The router is the part worth copying: a payload prefix belongs to one module
(`link`, and later `verify`, `gift`, `ref`), registering it twice raises, and a
handler that throws is logged without taking `/start` down.

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

### One database, many bots

Every bot sharing the database keeps documents with the same names — `runtime`,
`premium`, `chats`, `links` — so an unscoped store would let a clone's plugin
switch turn off the main bot's. Each `Database` therefore carries a **scope**
(`main:<bot id>`, `clone:<bot id>`, or `global`) and every row and lease is
written as `<scope>:<name>`. The stores keep using plain names; the prefix exists
only in SQL. `clone:…` is applied by `CloneManager.settings_for`, so a clone's
vault, premium ledger and plugin state are its own *and* survive a redeploy on
any instance.

`DB_REQUIRED=1` turns "the URL is set but unreachable" into a startup failure
instead of a silent fall back to files — two competing sources of truth are worse
than a bot that refuses to start.

**Clone tokens are encrypted at rest.** With `TOKEN_KEY` set, records are written
as Fernet ciphertext (`v1:` prefix, AES-CBC + HMAC) and decrypted only in memory;
masking a token in a panel was never protection for the database. A key that
cannot be used is an error rather than a quiet downgrade, a record written before
encryption existed is rewritten as ciphertext on the next save, and a record this
key cannot read is skipped with a logged reason instead of taking the bot down.
Without a key the store still works in plaintext and says so once at startup.

### The vault survives a redeploy

Two halves, two lifetimes:

* **the index** — which file belongs to whom, its size and its hash — is a
  scoped `files` document in PostgreSQL, read back by `Storage.hydrate()` once the
  database is loaded;
* **the bytes** — on disk under `DATA_DIR` by default, or in a private Telegram
  storage channel when `STORAGE_CHANNEL` is set. A stored file is archived in the
  background and its `file_id` remembered, so delivery (`/get`, a redeemed share
  link) is one `reply_cached_media` call that works on an instance which has
  never seen the upload — which is exactly what a redeploy looks like.

Delivery lives in one place, `agent/utils/delivery.py`: cached `file_id` first,
then the disk, then an honest "the bytes are gone" instead of a traceback. Without
`STORAGE_CHANNEL` nothing changes — files stay on disk, and the README says so
rather than implying a durability the host does not have.

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
pytest -q                      # 541 tests
python -m pyflakes agent tests # no unused names
```

State is JSON on disk (`data/`), never a database: the surface is small enough
that a schema and a migration tool would be overhead, and the files are easy to
inspect and back up.
