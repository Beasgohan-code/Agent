# Explicit repository adoption plan

The latest user mapping in `feature_sources.json` supersedes the assumption that
only the 29 account repositories are the feature targets. All seven specified
checkouts were cloned at pinned revisions into their requested ignored folders.
See FEATURE_SOURCE_CATALOG.md for static command evidence and name collisions.

## Source and runtime boundaries

These folders are study inputs, not active plugins. No package installer,
reference bot, session file, shipped secret-shaped file or deployment script was
executed/imported. They remain excluded from Docker. No source-code wholesale
copy or database migration has happened in this intake batch.

Agent retains Wzgram as the owner of the top-level `pyrogram` package. Do not
co-install Pyrofork/Kurigram/Pyrogram wheels over it. Richgram remains no-deps.
Verify APIs against installed Wzgram before adapting handlers. Aiogram is an
option only for an isolated feature whose requirements justify another client,
not an assumed dependency for all plugins. Neither a bot API fork nor Aiogram
replaces the native call engine/user-session requirements of Telegram VC.

## Feature-specific work queues

| Feature | First source paths checked | Integration direction and unresolved work |
| --- | --- | --- |
| Music | music/Videl0/videl/core/call.py; music/Videl0/videl/__main__.py; music/Playeon/playeon-bot/src/commands/playback/play.ts; music/Playeon/playeon-bot/src/core/command.ts | Compare native voice lifecycle separately from synchronized web rooms. Preserve consent, per-bot assistant leases and group locks. Search/seek/votes/lyrics/room UI require original isolated implementations and actual playback tests. Playeon is not silently substituted for Agent's engine. |
| Saver | saver/cantarella/session.py; saver/cantarella/thumbnail.py; saver/cantarella/settings.py | Review authorized export/login/logout/caption/thumbnail workflows. Do not import a global user session, collect credentials in groups or implement bypasses of access/content-protection controls. No Saver plugin is claimed as implemented yet; adding a plugin identity must reconcile the existing eight-feature policy. |
| Encoder | Encoder/VideoEncoder/plugins/encode.py; Encoder/VideoEncoder/plugins/queue.py; Encoder/VideoEncoder/plugins/settings.py | Map clip/trim/mux/audio/subtitle/options onto bounded jobs, cancellation and validated output. AGPL/nested licensing review before copying; do not import shell/exec/dependency installers. |
| FileStore | Filestore/main.py; Filestore/requirements.txt | Review archive/channel delivery, batch/deep links and per-clone configuration. Preserve authenticated ownership, SQL isolation and archive availability honesty; a root reuse license was not found. |
| Linkshare | Linkshare/plugins/settings.py; Linkshare/plugins/start.py | Review genlink/batch/start redemption and settings workflows, then design transactional grants before changing existing token formats. A root reuse license was not found. |
| Leech | leech/bot/helper/telegram_helper/bot_commands.py; leech/requirements.txt | Review static and plugin-generated commands, HTTP/torrent/cloud dependencies and status callbacks. Do not claim external daemons from command names. Preserve public-target validation and plan atomic quotas/durable recovery. AGPL/nested terms apply to code reuse. |

## Duplicate command handling

Keep distinct source command names; do not invent replacements because a menu
looks unfamiliar. A repeated name is only a collision candidate: `batch`,
`settings`, `status`, `clone`, `play`, `cancel`, `start` and `help` have different
semantics across these projects. Resolve actual registration conflicts using a
shared core handler or explicitly reviewed context/namespace, with exactly one
registered owner for a scope. Do not silently shadow a moderation or clone
command with a downloader command. The existing registry already refuses
multiple ownership; this intake does not change it.

The previous 15-name pruning remains in place until a new reference-backed
behavior is reviewed and deliberately restored. Nothing is automatically
deleted based on a candidate scanner. Dynamic regex/aliases and non-Python
registration need manual checks; two Python parse failures are recorded for
this new source set. Static counts are not a security audit or working parity.

## Licensing and identity

Playeon's custom license requires attribution and limits commercial use; do not
copy/rebrand its implementation/UI into Agent contrary to those terms. Ask for
permission where necessary, or implement independently from functional goals.
Encoder and CBML declare AGPL; Saver declares MIT; three checkouts have no root
license. Nested terms can differ. Keep required legal notices when copying
permitted code, while keeping normal Agent product screens free of unrelated
promotional credits. No license permission is inferred from a public URL.

Next delivery batches must identify exactly which handlers/features changed,
include isolated regression tests and state live-test limits. No merge or
production deployment is authorized by this plan.
