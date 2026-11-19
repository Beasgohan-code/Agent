# Standing user requirements and delivery ledger

This is the project requirement record, not a claim that all work is finished.
Keep it current as commands are upgraded one by one. New explicit user decisions
can supersede items here; do not silently discard earlier constraints.

## Current status and document map

- Latest explicit user decisions supersede older phase notes. Keep languages
  paused until command improvements are finished; English only is released.
- [COMMAND_INVENTORY.md](COMMAND_INVENTORY.md): generated source declarations,
  aliases and targeted-review flags, **not** proof all behavior is complete.
- [USER_ADMIN_FEATURES.md](USER_ADMIN_FEATURES.md): chronological command behavior,
  limits and safety decisions. Later entries supersede earlier “missing” lists.
- [CODEBASE_AUDIT.md](CODEBASE_AUDIT.md): phase-specific source/test evidence;
  old baseline findings/test totals are not current release certification.
- [GROUP_MANAGEMENT.md](GROUP_MANAGEMENT.md), [MODERATION_PARITY.md](MODERATION_PARITY.md),
  [GENERAL_FEATURES.md](GENERAL_FEATURES.md), [MUSIC_PARITY.md](MUSIC_PARITY.md):
  architecture and feature ledgers; respect recorded scope and unresolved limits.
- [CLONE_CONTROL_CENTRE.md](CLONE_CONTROL_CENTRE.md) and
  [FILESTORE_CLONE_PARITY.md](FILESTORE_CLONE_PARITY.md): clone/FileStore workflows,
  authority boundaries and incremental delivery, not universal upstream parity.
- [ALWAYS_ON.md](ALWAYS_ON.md), [LOG_SAFETY.md](LOG_SAFETY.md),
  [EMOJI_THEME.md](EMOJI_THEME.md), [UI_PREVIEW.md](UI_PREVIEW.md): hosting/logging
  limits, presentation and offline visuals. No uptime or live-render guarantee.
- [REFERENCE_ADOPTION.md](REFERENCE_ADOPTION.md),
  [references/README.md](references/README.md), [REFERENCE_INVENTORY.md](REFERENCE_INVENTORY.md)
  and per-reference indexes are pinned static discovery, not execution or a full
  behavioral/security audit. Preserve licenses; do not run reference installers.
- [../README.md](../README.md) and
  [../tools/typetube/README.md](../tools/typetube/README.md): setup and adapter limits.

Current mention contract: @all uses clickable first names; @eall uses random
emoji labels; no joining/on-off prerequisite.20/message,5s pause, up to2000 returned
records; Telegram may return only part of a group. Optional command text only,
no automatic headings or success cards; /tagabort stops future batches.
Stop/error controls cannot recall an in-flight send. FloodWait/uncertain delivery
requires review; no automatic retry. No production deployment or startup-fix claim.

## Non-negotiable workflow

- **Never merge the PR.** Work on the Arena session's fixed current branch only.
- Retain Agent's identity and original branding. Do not fill README, help, start
  or about screens with other bots' credits. Reference audit documents may name
  reviewed sources. Never remove legally required notices from copied code;
  prefer original implementations where licensing does not permit reuse.
- Study the requested repositories' actual behavior. Static catalogs and README
  claims are not a full manual/security audit or proof that a feature works.
  The repository catalog covers 29 other public account repositories; wholesale
  importing every app, dependency, eval command or global client is not the goal.
- Upgrade commands/plugins **one by one**, preserve existing services, test
  changes, report limitations and do not claim 210 capabilities/full parity.
- No new worker-style commands. Retain profiles instead of reviving removed
  worker/per-worker plugin command surfaces.
- Never merge as part of “continue”, and never change live hosting/billing,
  production leases or secrets as an undocumented side effect.

## Database and isolation

- **No more local JSON runtime state.** Use the existing Render `DATABASE_URL`;
  database is mandatory for normal bot startup. Do not ask the user to reconnect/recreate their existing database.
- `/setlog` must survive restart/redeploy; `/unsetlog` must not resurrect an env
  default. Success means confirmed persistence, not an in-memory change or a
  background write merely being queued. Upgrade other mutable settings against
  that durability standard in later increments.
- Per-bot tenant and per-group feature data must remain isolated. Optional
  reservations must be atomic in database, not a process-local counter.
- Do not claim every document-backed setting has confirmed-write semantics:
  several older stores still use batched document writes and need further audit.

## Main feature catalog

1. Encoder
2. Moderation
3. Post maker
4. Music
5. Linkshare
6. FileStore
7. Leech
8. AI Agent

Moderation and essential group safety are mandatory and slot-free. Optional
extras consume at most **three slots per group**, with global Owner approval
followed by local administrator activation. Optional failure must not crash the
core. Disabling must clean affected tasks/listeners/calls without touching other
groups. Existing distinct services must be strengthened, not removed to make a
smaller feature count look complete. Verification recovery, durable moderation
cases, richer settings and generic durable cleanup remain part of the backlog.

## Clone studio

- The authenticated **token sender owns the clone**, not the parent deployment.
  `getMe` validates bot identity; it cannot reveal the human BotFather owner.
- Private premium/sudo/Owner-gated setup, verified token, button-driven feature
  selection, verified log/archive channels and rechecks before creation.
- Encrypt new bot tokens, AI keys and Music session credentials at rest. No
  parent assistant/provider credentials inherited by clones. No recursive clones.
- Isolate bot identity, session, data directory, database scope, link signer,
  channels and lifecycle/leases. Respect eligibility/capacity again at start.
- Music assistant onboarding requires consent, endpoint validation, authorization,
  account-level exclusivity and cleanup on cancellation/failure—not a shared
  global assistant. Live Telegram/voice validation is still outstanding.

## User interface and Telegram

- Native Rich Message tables and rich menus/buttons; no fake ASCII-box tables.
  Keep improving the rich path and be honest about Telegram/client fallbacks.
- Keep the existing ⚙️ Plugin runtime panel as the plugin screen; avoid duplicate
  competing plugin panels and “Command reference” framing.
- Register active working handlers with Telegram; unavailable features must not
  become fake commands. Keep private/group scopes and permission checks correct.
- User asked to disable the menu button: reset forced menu behavior to Telegram
  default. Do not claim it is fully hidden while retaining slash commands; the
  API has no such visibility value. Telegram may still render its own control.
- Provide alive, uptime and health reporting from actual process/probe state.
  Aim for always-on hosting/recovery; self-pings and displayed uptime are not a
  guarantee against a free service sleeping. Do not silently purchase a plan.

## Music reference target

Use the requested reference behavior as the feature target, including **all
Music-related commands**, not just play/pause. Track actual support and remaining
families in [MUSIC_PARITY.md](MUSIC_PARITY.md). Current additions include bounded
queues, serialized controls and scoped database saved playlists. Search/media
extraction, channel/video playback, effects, seek, lyrics, autoplay/voting,
request approvals, DJ delegation and recovery still need implementation and
verification. Do not register placeholders or silently alias unsupported video
or extractor behavior to basic direct-URL audio playback.

## Latest urgent correction

Log settings were still local-file-only. The current increment replaces that
production path with a dedicated bot-scoped database row, awaited writes,
pre-start hydration, persistent explicit clearing and database-refreshing `/log`.
A posting probe is sent before committing a new target. In database mode there
is no ephemeral-file fallback; old file-only selections must be saved once with
`/setlog` after deploying this correction. Previously lost ephemeral data cannot
be reconstructed. Standalone deployments without a database retain explicit
atomic local-file compatibility, clearly labelled as such.

## Latest extension: safe #Errors and no disk fallback

Unhandled handler errors must also notify the configured log destination as
`#Errors`. The incident center stores safe category/frame metadata and aggregated
counts in database, without copying raw exception arguments or incoming
messages. `/errors` is private and Owner-only. Repeated alerts are bounded.
The normal service now requires database regardless of the legacy DB_REQUIRED
flag. Remaining standalone JSON helper branches are legacy/test compatibility,
not a supported bot runtime mode. Temporary downloaded/encoded media is distinct
from JSON metadata. Continue upgrading mutable commands one by one; reference
feature extraction/manual review and full Music parity are still unfinished.

## Follow-up: public keep-alive and progressive UI upgrades

Match the public 300-second keep-alive behavior of the inspected reference,
continue command-by-command improvements, and increase modern premium-emoji UI
coverage. Implemented public-origin web-service heartbeat plus uptime telemetry
and themed Home/Help/profile/Ping headings; remaining commands are incremental
work, not a completed universal redesign. Preserve fallback and never claim
self-pinging guarantees uninterrupted hosting.


## Neutral implementation wording

Keep database-engine branding out of bot-facing text, setup prose and progress
updates. Describe availability, persistence and failure honestly using generic
storage wording; never imply a storage migration or remove failure warnings.
Internal connection protocols, capability identifiers, driver imports, SQL,
reference source paths and licenses must remain technically correct.


## Continuation order (recalled scope, not a completion claim)

1. Continue command-by-command behavior, authorization, rich UI and regression
   review from COMMAND_INVENTORY; declarations alone do not finish a command.
2. Preserve and finish the existing eight-tool feature work, FileStore clone
   parity and main/clone UI separation, clone control/reconciliation, Music
   source/session/recovery work and remaining moderation/general behavior. Use
   the linked ledgers; validate pending dirty slices separately, never bulk-stage.
3. Preserve premium/Owner limits, encrypted sender-owned credentials, isolation,
   mandatory safety and three-slot optional approval. No duplicate implementations
   or fake commands/providers; retain native rich tables and Plugin runtime.
4. Keep the requested mention output/pacing and neutral implementation wording.
   Test reliability/startup/logging without claiming an unresolved live failure
   fixed; sanitized hosting evidence is still needed for the reported startup issue.
5. Only after command work: inspect actual Videl1 language approach; release only
   fully translated/optimized locales with no English fallback. English only now.
6. Preserve licenses and unrelated work; verify isolated patches and working tree,
   publish only on this branch. No merge/deploy/production changes.
