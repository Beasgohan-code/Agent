# Agent

A professional Telegram group-management bot with mandatory moderation and
safety systems. Music, FileStore, Encoder and other tools are optional modules.

The shell plus moderation, group settings, filters, onboarding, reports and
verification always register, even with a narrow `PLUGINS` setting. They cannot
be disabled through the plugin panel or restored as disabled from old state.
Individual rules remain configurable by group; verification is off by default.

**In progress:** the full Group Control Center, durable resource teardown and
plugin-specific per-group data/configuration workflows. The group plugin panel
now provides approval-aware three-slot activation; the private Owner runtime
panel still controls deployment-wide availability. The 210-feature brief is a target,
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
| `DATA_DIR` | no | Temporary media/vault working directory. Metadata is PostgreSQL-backed. Default `data`. |
| `DATABASE_URL` | **yes** | PostgreSQL DSN. Set it and every store is kept in the database, scoped per bot. |
| `TOKEN_KEY` | no | Encrypts clone tokens at rest (Fernet). Unset ⇒ plaintext, announced. |
| `DB_REQUIRED` | no | Legacy flag; PostgreSQL is now always required. `0` does not enable local state. |
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
`postmaker`, `encoder`, `ai_agent` and `clone`. `renamer`, `premium` and `utilities` are
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

`platform/plugin_access.py` implements PostgreSQL Owner approval, three optional
slots per group, configuration and activation history. Approval is rechecked
under a catalog row lock; reservation uses a group-specific transaction lock.
There is no file fallback. In groups, optional command, callback, deep-link and
watcher entry points check live eligibility. Mandatory moderation bypasses the
optional gate. Private tools retain deployment-scoped behavior and do not consume
group slots; global approval is currently a group-use permission.

- Owner: `/plugin music approve` or `/plugin music revoke` controls global
  group-use approval. Deployment-wide on/off remains a separate Owner control.
- Administrators: `/plugins` in a group, or the plugin button under `/settings`,
  shows actual availability and slots. Activation rechecks management rights;
  disabling asks for confirmation. Private-only modules are not offered as group
  features. Music also needs a configured voice session.
- Group-owned invocation tasks and queued jobs are cancelled on local revocation
  or disable. Music releases its queue/call. Other processes reconcile active
  scopes every two seconds; new requests always check PostgreSQL directly.

This is the plugin slice of the Control Center, not its complete implementation.
Generic durable job/subscription cleanup, plugin-specific configuration forms,
full per-group feature-data migration and external process isolation remain open.

## Clones

Send **`/clone` in private** to open Clone studio. This requires bot premium,
sudo access or the bot Owner. `TOKEN_KEY` must be configured before credentials
are requested. Guided setup supports **Encoder, Moderation, Post maker,
Linkshare, FileStore, Leech, Music and AI Agent**, one plugin at a
time:

1. Send a token from @BotFather. Agent checks `getMe` and the bot id; format alone
   is not accepted as identity. Secret messages are deleted best-effort.
2. Choose a reviewed template with a button. Mandatory group core stays available.
3. For AI Agent, privately supply your own OpenAI key and model id first.
   No paid validation request is made; compatibility is checked on first use.
   Then send a log channel id, or `skip`.
4. For FileStore, send the archive channel id. Both the operator and clone must be
   channel administrators; the clone needs posting permission. Rights are checked
   again before creation.
5. Confirm creation. The signed-in setup user becomes the clone's Owner, in its
   own bot tenant—not an Owner of this deployment. Telegram does not reveal a
   bot's human owner from its token, so Agent does not pretend to fetch one.

Drafts expire after ten minutes; `/cancel` discards one. Draft tokens are held in
memory, not persisted. Completed tokens are encrypted. Telegram chat history is
not a credential vault; message deletion cannot guarantee erasure from clients.
Music setup is offered only with connected PostgreSQL and installed voice
libraries. It requires explicit consent before accepting a dedicated account's
pre-generated Telethon session. Phone numbers, passwords and OTPs are never
requested. Session structure is checked offline; Telegram user authorization
and account exclusivity are checked when the clone starts. No group call is
joined during setup.

The legacy `/clone <token> [standard|files|tiny]` path remains private, encrypted
and premium/sudo/Owner-gated. Guided setup selects one reviewed feature; changing its
profile later replaces that selection with the chosen legacy template. All
profiles keep mandatory group core. No clone profile includes recursive cloning.

* `/mybots` controls Start, Stop, Profile and Delete. Starting/reconfiguring
  rechecks eligibility; users can still stop/delete existing clones after expiry.
* `/delclone <bot id | @username>` removes a record and stops its client.
* `/clonestats` is the deployment Owner's summary.
* Owner-only `/sudo add <user id>`, `/sudo remove <user id>` and `/sudo list`
  manage delegated clone eligibility in private. Sudo does **not** confer Owner
  commands, group administrator rights or access to other users' clones.

### A clone has a state, not a boolean

`is_running` answered the wrong question: it could not tell a revoked token from
a crash from a deliberate stop. Every worker now carries a real state —
`queued → validating → starting → running`, with `degraded` for a client that is
connected but cannot be named, `stopping → stopped` for an orderly shutdown, and
`failed` with a sanitized error category attached. Impossible transitions raise
instead of being absorbed.

A supervisor checks live clients, parks ineligible owners' clones, and attempts
restart after a connection drop. `/mybots` shows states and sanitized failure
reasons; `/clonestats` counts them. Lease-loss monitoring disconnects the affected
clone rather than allowing it to continue without confirmed ownership.

Free members cannot create or restart clones. Bot premium allows three;
Owner/sudo users remain subject to `CLONE_LIMIT`. Eligibility is rechecked on
startup and supervisor passes; an ineligible running clone is stopped and parked.

Each clone has its own bot id, link signer, session name, data directory and
PostgreSQL scope. It does not inherit the parent assistant session, log/archive
channels or HTTP port. Clone database loading and exclusive lease acquisition
happen before Telegram startup; shutdown releases its lease and database.
Clones are still clients in the parent process, not OS-process isolation.

## Vault, links, captions

| Command | What it does |
| --- | --- |
| `/batch [count]` | Save replied consecutive files to your vault; use `/batch 1` for one file. |
| `/batch [n]` | Save a run of consecutive files, starting at the replied one. |
| `/files`, `/check <id>`, `/get <id>`, `/del <id>` | List, inspect, re-send and delete vault entries. |
| `/genlink [hours] [uses]` | Store the replied file and answer with a share link (deep link + copy button). |
| `/share <id> [hours] [uses]` | The same, for a file already in your vault — no second copy. |
| `/links`, `/revoke` | Every live link with the uses and hours it has left; revoke by token or button. |
| `/setcaption`, `/viewcaption` | The caption attached to files this chat receives; `{name}`, `{stem}`, `{size}`. |
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
the transfers are ordinary jobs, so `/cancel` stops your active jobs.

The encoder plugin runs real FFmpeg (system binary, or the `imageio-ffmpeg`
wheel): `/encode` with presets and live progress, `/compress` for the fast
preset by name, `/sample [start] [length]` for a stream-copied clip, `/toaudio`
for the audio track as MP3, `/screens` for a 3×3 contact sheet, and `/mediainfo`
to probe what a file actually is. Every tool feeds the same job queue, so
`/cancel` kills the child process instead of politely forgetting it, and every
produced file comes back with the chat's caption and thumbnail attached. The music player drives `pytgcalls` with a Telethon
user session, and is gated on capability: without `SESSION_STRING` the module
registers zero commands and `/plugins` says why. `/play` and `/nowplaying` answer
with a card, and the card is the remote — pause/resume, skip, and a red
stop-and-clear, for staff or whoever queued the track.

## Where state lives

The bot runtime requires PostgreSQL. Missing credentials, a failed connection
or failed initial state load refuse startup; there is no local JSON fallback.
The old `DB_REQUIRED=0` option no longer enables disk-backed operation.

Legacy document stores use bot-scoped PostgreSQL JSONB rows; plugin approval,
Music playlists, log destinations and incident aggregation use dedicated tables.
Some older stores still batch writes in memory before flushing: this change
removes disk fallback, not every outstanding confirmed-write limitation. `/setlog`
uses awaited SQL and confirms only after persistence. Temporary media files can
still use disk; media bytes are not PostgreSQL metadata.

Low-level standalone file helpers remain for legacy/test compatibility, but the
normal bot/clone service lifecycle does not start in that mode. Do not deploy
those helpers as a replacement persistence system.

### One database, many bots

Every bot sharing the database keeps documents with the same names — `runtime`,
`premium`, `chats`, `links` — so an unscoped store would let a clone's plugin
switch turn off the main bot's. Each `Database` therefore carries a **scope**
(`main:<bot id>`, `clone:<bot id>`, or `global`) and every row and lease is
written as `<scope>:<name>`. The stores keep using plain names; the prefix exists
only in SQL. `clone:…` is applied by `CloneManager.settings_for`, so a clone's
vault, premium ledger and plugin state are its own *and* survive a redeploy on
any instance.

Normal bot startup always requires PostgreSQL. The legacy `DB_REQUIRED=0`
flag does not enable local JSON fallback.

**Clone tokens are encrypted at rest.** With `TOKEN_KEY` set, records are written
as Fernet ciphertext (`v1:` prefix, AES-CBC + HMAC) and decrypted only in memory;
masking a token in a panel was never protection for the database. A key that
cannot be used is an error rather than a quiet downgrade, a record written before
encryption existed is rewritten as ciphertext on the next save, and a record this
key cannot read is skipped with a logged reason instead of taking the bot down.
Guided clone setup requires this key before asking for credentials. Legacy
low-level stores support plaintext compatibility, but that is not a recommended
clone workflow. Ordinary non-clone commands do not require `TOKEN_KEY`. See
[Encryption setup](docs/ENCRYPTION_SETUP.md).

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
channel is set. `/setlog` and `/log` manage it.

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

Runtime state is PostgreSQL-backed. Local JSON helpers are legacy/test-only;
the normal service refuses to start without PostgreSQL.

## Primary feature catalog and AI Agent

The primary catalog is Encoder, Moderation, Post maker, Music, Linkshare,
FileStore, Leech and AI Agent. Moderation is mandatory and slot-free; optional
features still require global Owner approval and group-admin activation, with
at most three active per group. Dependency availability is shown honestly.

AI Agent provides explicit `/ask <question>` text completions when both
`AI_API_KEY` and `AI_MODEL` are configured. It sends that question to OpenAI,
not group history. It has no tools, moderation authority or autonomous actions.
Obvious token/key patterns are rejected, but this is not a comprehensive secret
scanner: never include private information. Responses are untrusted AI output.
Requests have bounded size, concurrency, timeout and a per-user cooldown.
No key means no `/ask` handler. Parent AI credentials never pass into clones.
AI Agent clones instead require their own private guided key/model setup; keys
are encrypted at rest and cleared from cancelled or expired drafts. Changing a
clone to a legacy profile removes its stored AI credentials.

Every clone uses its recorded token sender as its own tenant Owner, including
legacy records. This does not grant ownership of the parent bot. Telegram token
validation confirms a bot identity, not the human BotFather account owner.

### Music assistant isolation

When PostgreSQL is configured, voice engines reserve their verified Telegram
assistant account across bot tenants before starting calls. The same account
cannot be acquired twice in that database, even with different session strings.
Connection loss triggers shutdown and blocks new voice operations. Each active
assistant uses one database pool connection. This does not fence external
Telegram clients or deployments using another database, and failure detection
is not instantaneous. Use a dedicated account. Database-free legacy deployments
do not have distributed assistant exclusivity. Music clone onboarding therefore
requires PostgreSQL. Only production Telethon IPv4 sessions using port 443 and
allowlisted Telegram DC networks are accepted; arbitrary session endpoints are
rejected before any connection. Parent assistant credentials are never reused.
Changing to a legacy profile clears the stored assistant session. Revoke it in
Telegram Devices to invalidate account access; deleting local ciphertext alone
does not revoke Telegram authorization.

### Alive reporting and expanded Music controls

`/` and `/alive` now report measured heartbeat age, uptime and UTC time as JSON.
`/health/ready` returns 200 only once Telegram probes are healthy; the existing
`/health/live` remains process liveness. Telegram `/alive` opens the live status
screen. Web services with `RENDER_EXTERNAL_URL` and `PORT` now self-ping
`/health` every 300 seconds (10-second timeout); this cannot prevent all
free-tier sleep or guarantee uninterrupted hosting. See `docs/ALWAYS_ON.md`.

Music has 24 base group commands when its dependencies and assistant are
configured, plus four saved-playlist commands when PostgreSQL is connected, including queue editing, repeat modes, shuffle, replay, volume,
play-next and recent session titles. Song-name search, YouTube watch-page
extraction, effects, seeking and linked-channel playback are **not** claimed as
supported yet. See [Music behavior migration](docs/MUSIC_PARITY.md) for exact
commands, permissions, source limits and the remaining reference command list.

### Uptime and Telegram registration

`/uptime` shows measured process uptime and Telegram probe counts. With
`SYNC_COMMANDS=1` (default), active handler commands are registered with Telegram
at startup and refreshed after runtime plugin changes, including for clones.
Group lists include shared `/start`, `/help`, `/ping` and `/uptime` controls.
Unavailable plugins do not publish pretend commands; authorization/activation
checks still apply.

The forced Commands menu button is removed in favor of Telegram's default.
Telegram may still show its built-in Menu button: there is no API for hiding it
while keeping registered slash commands. See [always-on deployment and uptime](docs/ALWAYS_ON.md)
for the reference keep-alive behavior, monitoring endpoints and hosting setup.
A sleeping free service is not an always-on host; the existing Blueprint uses a
paid `starter` worker. Applying that plan is a deployment decision, not something
this code silently purchases or changes on your live service.

### Saved Music playlists

Admins can use `/saveplaylist name`, `/playlists`, `/playlist name` and
`/deleteplaylist name`. Lists are PostgreSQL-backed and isolated by bot, group
and user, with atomic quotas (10 lists, 20 tracks each). Saving replaces your
same-named list. Only stable public HTTP(S) media URLs are accepted—not local
files, credentials or signed query URLs. Start fresh playback before loading;
loading appends the whole validated list only if it fits, without replacing the
current track. Lists persist until deleted. See the Music migration document
for URL-validation limitations and the remaining feature backlog.

### Persistent log destination

With `DATABASE_URL` configured, `/setlog <negative channel id>` tests posting
permission and saves the destination directly to PostgreSQL **before** confirming
success. `/log` rereads the database. The former `/unsetlog` command has been
retired; existing explicit-clear records remain respected. Main bot and clone settings
are separate. A configured but unavailable database never silently redirects
these settings to an ephemeral JSON file.

**After deploying this correction, run `/setlog` once again** to save your old
file-only selection in PostgreSQL. Data already lost from an old Render disk
cannot be recovered. Without a database, standalone file compatibility remains
clearly labelled; it is not redeploy-safe hosting storage.

[Standing user requirements](docs/USER_REQUIREMENTS.md) records the continuing
scope and constraints for command-by-command upgrades. This log-setting fix does
not mean every older batched settings store already has confirmed-write semantics.

### Safe error incident center

Unhandled handler failures generate **#Errors** log notifications with a stable
incident ID, error category, handler, safe frame locations and occurrence count.
Raw exception arguments, update/message text, usernames, tokens and local
variables are not intentionally collected. Repeats are aggregated in PostgreSQL
and alerts are throttled to once per fingerprint per minute per process.
Owner-only `/errors` in private shows the latest 10 incident groups in this bot.
At most 100 distinct groups are retained per tenant, pruned on incident writes.
This is bounded operational diagnosis, not an immutable moderation audit trail.
Caught component errors and failures before Telegram connection are not all
forwarded through this boundary. No live deployment has been validated here.
