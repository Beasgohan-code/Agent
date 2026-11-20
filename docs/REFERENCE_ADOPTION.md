# Reference adoption ledger

The complete local checkout catalog is [here](references/README.md). It records
29 public repositories, their exact revisions, tracked file-type counts and
Python command/process/client candidates. Clones live under ignored `refs/`;
no reference source, package installer or startup script is executed by Agent.
These are implementation references, not credits, dependencies or parity claims.

## Current decisions

| Area | Reference behavior inspected | Agent decision/status |
| --- | --- | --- |
| Clone ownership | Token submitter stored as owner in clone command/manager | Implemented: submitter owns only its isolated bot tenant |
| Clone configuration | File-store reference README describes per-clone settings, links and access controls | Keep explicit, verified guided templates; unlimited cloning, cross-clone universal links and database transfer are not imported |
| Music lifecycle | Music reference `main.py` starts assistant/call engine, then shuts them down before the bot HTTP session | Separate per-bot engine, bounded partial-start cleanup and database-wide assistant-account guard retained; no module-global assistant imported |
| Music session | Music reference assistant factory uses an in-memory user session | Current branch already includes consent-first encrypted onboarding; Telegram endpoint restrictions, account authorization and exclusivity apply before readiness |
| Downloader | Downloader reference advertises domain dispatch, HLS/DASH and cloud upload | Candidate backlog only; README claims are not validated support. Keep SSRF checks and bounded downloads; no downloader package imported or auto-installed |
| Developer commands | Static index locates eval, exec and shell/process entry points | Do not adopt arbitrary shell/eval commands for clone owners |
| Non-Python apps | Catalog includes Android, hosting and web projects | File-type/revision inventory only; no claim of Java/Kotlin/TypeScript behavioral audit or migration into a Telegram bot |
| Licensing | Checkout-specific licenses and nested component terms can differ | No blanket reuse permission inferred. Use original behavior implementations where licensing is absent/incompatible; never strip mandatory notices from copied code |

## Production log correction

The supplied Render log shows lease handover followed by successful Telegram
login and watchdog health. It does not show a Telegram login crash. The later
shutdown attempts `#BotStopped` after `client.stop()`, producing `Client has not
been started yet`. Shutdown now emits the event and drains this bot's pending
log tasks **before** disconnect. Drain time is capped at five seconds, each send
has a ten-second timeout, and unfinished posts are cancelled rather than holding
shutdown open. Closing one clone's logbook cannot drain another bot's tasks.
Late events are ignored once draining begins. This notification describes the
shutdown transition; delivery is best-effort, not a durable audit guarantee.

Reference sources, tools/docs and runtime data are now excluded from Docker's
build context as well as from application `COPY` instructions. This reduces
upload/cache size and avoids sending downloaded reference or credential data to
the image builder. Nothing here changes Render environment variables, deletes
leases, merges the PR or validates a new production deploy.

## Still open

- Manual review of every feature, registration path and dynamic command.
- Non-Python source analysis beyond tracked file-type coverage.
- License-by-license and nested-dependency reuse decisions before copying code.
- Behavior parity for useful features, with isolation and regression tests first.
- Real Telegram voice playback/session testing and production shutdown validation.

A static catalog covering all files is **not** the same as extracting and safely
integrating every feature. Duplicate plugins, unrestricted credential handling,
unsafe admin tools and unrelated apps will not be imported wholesale.

Validation for this increment: **772 tests passed** with disposable database
and the optional Telethon parser installed. Static compilation, pyflakes and
whitespace checks passed. Pending log tasks are capped at 200 per bot and track
dropped excess notifications. No production redeploy or live Telegram validation
has been performed.
