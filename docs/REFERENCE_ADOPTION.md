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

## LINK-SHAREBOT channel-invite replacement request

User explicitly requested replacing the current file-link Linkshare command
surface with `abhinai2244/LINK-SHAREBOT` behavior. Clarification: channel-invite
workflow, with both manual approval and per-channel opt-in auto-approval. Manual
is the default; do not install a blanket join-request auto-approver.

Read-only review pinned upstream revision
`265f2acbe720571e7c514cd32eea600292656fe2`: plugins/start.py, settings.py,
approve.py, route.py and bot.py. Declared commands are start, broadcast, settings,
genlink and batch. Upstream generates normal and request channel-invite deep links;
it is not the existing Agent vault-file bearer-link workflow. GitHub reports no
license identifier; no upstream code was copied/imported/executed. Its raw-error
logging, blanket approval listener and base64-only channel references are not
security patterns to import.

Current implementation phase is storage only: new scoped channel configuration,
manual/default and explicit boolean auto-approval preference, enabled state,
updated-by identity, awaited atomic writes and serialized 20-channel quota.
Independent concurrent field patches merge rather than overwrite. No disk/cache
fallback and no invite/approval/network effect is triggered by configuration.
Handler authority checks remain required before exposing writes.

Command migration remains unfinished: retain existing /start and /broadcast
owners, contextually extend existing /settings and /batch rather than duplicate
registrations, adapt /genlink to verified managed channels, and replace old
Linkshare creation controls after the new workflow is usable. Preserve existing
file-link redemption/storage and FileStore archive flows. No commands are removed
or rerouted by this storage phase; no full parity/working invites claim.

### Channel invite handler increment

Existing `/genlink` now routes explicit negative-channel IDs and channels/add/mode/
disable arguments to native channel management, without duplicate registrations.
Temporary transition syntax: `/genlink channels`, `/genlink add ID`, `/genlink mode
ID manual|auto`, `/genlink disable ID`, `/genlink ID`. Bot Owner only in matching
private chat; personal identity, actual channel identity and live invite authority
of both actor and bot are checked. This is narrower than upstream delegated bot
admins. It is not the final requested command surface: private `/settings` and
channel `/batch`, delegated management and legacy-command removal remain pending.

Creates direct Telegram normal/request invites, each expiring in 15 minutes;
normal invite has member limit one. Only valid acknowledged Telegram invite URLs
are rendered. Partial success preserves the confirmed invite and explicitly marks
unconfirmed creation; no blind retries. Disabled channels refuse new generation;
disabling does not revoke previously created invites. Authorization and Telegram
creation cannot be made one atomic transaction. Failed/ambiguous invite creation
may already have had an effect; inspect channel invites before explicit retries.

Auto/manual mode is a saved preference only: no join-request approval worker is
wired yet, and the interface says so. No blanket auto-approval, base64-only bot
redemption, incoming-content import or upstream source copy is introduced. Legacy
file sharing/redemption is retained during this explicitly incomplete migration.

### Scoped channel automatic approval

Supersedes the earlier preference-only limitation: the Linkshare runtime now owns
a join-request watcher. Enabled managed channels explicitly set to auto approve
ordinary channel requests after current actor identity, channel identity and bot
Owner/bot invite-right checks, then a fresh policy read. Manual, disabled,
unregistered and unavailable-storage paths never approve. Native guard queries
remain exclusively Security's human-review queue; group requests are untouched.
No retries, invite export, unsolicited DMs or raw provider error logging. A failed
or unacknowledged remote response is unknown, not proof of rejection. Plugin
runtime/gate controls own the watcher just like commands; no competing global
approval loop is installed. Telegram permission/effect and policy checks are not
one atomic transaction. Simultaneous Telegram update redelivery is not claimed to
be exactly-once. Existing outstanding Telegram invites are not revoked by mode
changes. Command parity, bot-mediated deep links and legacy command retirement
remain unfinished.

### Shared /settings routing

Existing Group command owner now serves `/settings` in both contexts, without a
second registration. Private chat delegates through Linkshare's runtime gate to
Owner-only channel configuration; groups retain existing administration checks
and panel. `/settings` lists managed channels; `/settings add ID`, `/settings mode
ID manual|auto`, `/settings disable ID` use awaited configuration with live channel
invite-right checks. Existing `/genlink` management aliases remain temporarily.

Manifest per-command scopes are used by both handler filters and Telegram command
publication. Only settings is widened; other Group commands stay group-only.
This is textual command configuration, not full upstream settings button parity.
Delegated bot admins, subscription/admin menus, channel batches, bot-mediated
links and legacy creation-command retirement remain unfinished. No stored files,
issued file tokens or unrelated command owners are removed.

### Legacy file-creation command retirement

User explicitly confirmed deletion/replacement of related old command logic after
clarification. Rechecked reference master: still pinned revision above. Retired
Linkshare file creation code (media downloads, vault sharing, TTL/use argument
parsing) rather than leaving it reachable behind /genlink. /genlink is now solely
the managed-channel handler; /share and /linkchannel are no longer declared or
registered. Removed the old subscription configuration handler but retained its
policy reader for previously issued file links. Updated menus and worker guidance.
No upstream source copied or executed.

/links and /revoke remain deliberate legacy maintenance exceptions to the target
five-command reference surface: deleting those would remove existing grant owners'
controls. Legacy deep-link redemption and old revoke buttons remain. Underlying
storage, caps, expiry, subscription checks and revocation still enforce old grants.
No file data or issued token records are deleted. FileStore-only worker /genlink
is an unrelated archive workflow and remains untouched. Full reference parity is
still incomplete: channel /batch routing, bot-mediated channel deep links,
settings-button/admin/subscription flows remain. Normal/request channel generation
is currently direct bounded Telegram invites, not upstream's encoded bot links.

### Channel /batch through existing command ownership

Private `/batch ID [ID ...]` with negative channel IDs and no replied message now
delegates from FileStore's existing batch owner through Linkshare's runtime gate
to the channel handler. One to five unique managed enabled channels; all targets
and current Owner/bot invite rights are validated before the first invite request.
Each channel then uses the existing verified generation path, rechecking authority
and policy. Replies identify their channel. Stops on refused/unconfirmed generation,
retains confirmed invites and warns to inspect channel invites before retrying.
No automatic retries or rollback/revocation claims. Exact enabled booleans required.

Replied-file batches and positive archive-range syntax remain unchanged. No extra
command registration. Limitation: the existing FileStore owner must be deployed and
runtime-active as well as Linkshare; disabling FileStore removes the owning handler.
Independent Linkshare-only `/batch` ownership is not yet implemented. Thus this is
not full reference deployment parity. Bot-mediated channel links and expanded
settings/admin/subscription UI remain unfinished; direct invites still used.

### Bot-mediated normal/request channel links

Supersedes direct-invite generation: /genlink and channel /batch now return normal
and request links under the plugin-owned `channel_` start prefix. Generation
validates management authority but does not create a Telegram invite. Tokens are
random opaque 144-bit values, stored only as digests in tenant-scoped durable rows;
normal/request modes are immutable per row. Issuance uses a channel row lock and
an awaited transaction for pair creation, with 200 live tokens per channel (100
pairs), 30-day expiry and opportunistic expired-row cleanup. Bot identity must be
available before issuance. No base64-only channel authority and no copied source.

Personal private-chat /start redemption resolves current enabled policy, preserves
the existing subscription gate, verifies channel identity and current Owner/bot
invite rights, then re-resolves the grant before requesting ONE 15-minute invite
of its mode. Normal invites allow one join; request invites use current manual/
auto approval. Invalid/expired/disabled/foreign-tenant tokens fail closed. No raw
provider errors or blind retries. Re-enabling a channel restores unexpired links;
disabling blocks bot redemption but cannot revoke previously issued Telegram
invites. Tokens are reusable bearer links for their lifetime, not per-user access
controls. Telegram effects and policy checks cannot be one atomic transaction.
No exactly-once delivery/redelivery protection or per-recipient rate limiter is
claimed; unconfirmed creation may have taken effect. Full reference parity still
needs independent Linkshare-only /batch routing and settings/admin/subscription UI.

### Clickable channel settings and explicit bot-link invalidation

Private /settings lists five channels per page with navigation and verified
controls: generate bot links, manual/auto approval, enable/disable, revoke bot
links. Buttons are plugin-owned actions, gated by current runtime and personal
Owner identity in matching private chat. Callback-origin message sender is never
used as actor; a copied request uses the clicker's checked identity and re-enters
the same command authorization/storage path. Channel mutation still verifies live
channel identity and current Owner/bot invite rights. Callback fields are strictly
parsed; chat-less, stale, foreign-user and missing-runtime requests refuse.

Revoke bot links prompts for confirmation. Nonces are random, Owner-bound through
the private context, limited to twenty outstanding, expire after two minutes and
are consumed once. Restart drops confirmations safely (not durable approvals).
The explicit command equivalent is `/settings invalidate ID confirm`. Invalidation
is an awaited scoped delete under the channel row lock also used for issuance;
new links issued after it can be valid. It cannot revoke already-created Telegram
invites, delivered copies or an invite request already in flight. No atomic remote
revocation claim. Existing disable/re-enable semantics are unchanged.

This is native reference-inspired channel UI, not complete upstream admin/fsub
parity. Standalone Linkshare-only batch dispatch, delegated admins and editable
required-subscription UI remain unfinished. No live Telegram validation performed.
