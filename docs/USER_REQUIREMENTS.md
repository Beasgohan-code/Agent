# Standing user requirements and delivery ledger

This is the project requirement record, not a claim that all work is finished.
Keep it current as commands are upgraded one by one. New explicit user decisions
can supersede items here; do not silently discard earlier constraints.

## Non-negotiable workflow

- **Do not merge without a separate second explicit user confirmation naming the PR.**
  A previous single-request merge was reported as a mistake. First ask for
  confirmation; “continue” is never merge permission. Work only on the Arena
  session's fixed current branch. Do not revert prior merges without approval.
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
  PostgreSQL is mandatory for normal bot startup. Do not ask the user to reconnect/recreate their existing database.
- `/setlog` must survive restart/redeploy; `/unsetlog` must not resurrect an env
  default. Success means confirmed persistence, not an in-memory change or a
  background write merely being queued. Upgrade other mutable settings against
  that durability standard in later increments.
- Per-bot tenant and per-group feature data must remain isolated. Optional
  reservations must be atomic in PostgreSQL, not a process-local counter.
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
queues, serialized controls and scoped PostgreSQL saved playlists. Search/media
extraction, channel/video playback, effects, seek, lyrics, autoplay/voting,
request approvals, DJ delegation and recovery still need implementation and
verification. Do not register placeholders or silently alias unsupported video
or extractor behavior to basic direct-URL audio playback.

## Latest urgent correction

Log settings were still local-file-only. The current increment replaces that
production path with a dedicated bot-scoped PostgreSQL row, awaited writes,
pre-start hydration, persistent explicit clearing and database-refreshing `/log`.
A posting probe is sent before committing a new target. In database mode there
is no ephemeral-file fallback; old file-only selections must be saved once with
`/setlog` after deploying this correction. Previously lost ephemeral data cannot
be reconstructed. Standalone deployments without a database retain explicit
atomic local-file compatibility, clearly labelled as such.

## Latest extension: safe #Errors and no disk fallback

Unhandled handler errors must also notify the configured log destination as
`#Errors`. The incident center stores safe category/frame metadata and aggregated
counts in PostgreSQL, without copying raw exception arguments or incoming
messages. `/errors` is private and Owner-only. Repeated alerts are bounded.
The normal service now requires PostgreSQL regardless of the legacy DB_REQUIRED
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

## Latest command increment

Implemented group-admin/tenant-Owner `/voicehealth`: premium-styled native rich
panel showing allowlisted, group-local cached voice state, repeat/upcoming queue
and acknowledged volume. It performs no remote probe or mutation and exposes no
media sources, titles or assistant credentials. Quality settings, active network
voice tests, durable cleanup recovery and full reference parity remain pending.

### Continued UI pass

Upgraded `/queue`/`/q` with validated pagination and stable positions,
`/nowplaying` with richer group-local telemetry, and volume/control feedback
with premium-themed native panels and Unicode fallback. Continue auditing the
remaining commands one by one; this is not a universal UI/parity completion.
No merge without the separately confirmed PR-specific second approval.

### Saved library increment

Add `/playlistinfo name` for read-only, group/user/tenant-scoped saved title
previews, without selecting media source fields or probing media addresses.
Upgrade all saved-playlist result panels with premium theming, quota and empty
state guidance. Existing admin permissions, confirmed SQL saves and whole-list
load validation remain unchanged. Full Music/reference parity is still pending.

### Post Studio increment

Moved beyond Music: fixed the broken Post Maker publishing import, single-pass
substitution and dangerous silent truncation. Preview/publication now share the
same normalised HTML path, accept replied captions, enforce bounded composition,
and distinguish ambiguous send failures from acknowledged sends with failed
audit writes. Upgraded studio/template/status UI and added default-layout reset.
Template writes still use older background-flushed ChatStore; do not claim full
confirmed-write durability. Preview is group-visible, not a private draft.

### FileStore increment and live health observation

Continued beyond Music/Post Maker with FileStore pagination, personal-identity
checks, strict bounded command arguments, escaped metadata, richer archive/delete
status and sanitized failure feedback. Fixed the `/storestats` tier helper crash.
No changes to live plugin activation or persistence semantics. A user-requested
one-shot GET of the deployment's `/health` returned healthy at that instant;
it is not proof of historical uptime or end-to-end feature readiness.

### Linkshare command increment

`/links [page]` now browses all of the caller's records without displaying bearer
tokens, with current owner isolation and page checks. Creation arguments now
reject malformed/oversized values rather than silently clamping expiry/uses.
Personal-identity guards, safe genlink error categories, corrected filename
escaping and clearer revocation/copy warnings were added. Existing link storage
still background-flushes, and redemption caps are not newly made cross-process
atomic. Current token construction can reuse the same token for same file/owner
and expiry second; unique-grant token design remains a separate compatibility
upgrade, not solved by this UI increment.

### Reports & Appeals review increment

Added paged open/closed queues and full retained details, stricter close parsing,
personal-identity checks and premium review panels. Fixed zero-limit ChatStore
report slicing and escaped appeal owner notifications with explicit chat context.
Moderator command permissions do not make responses private. Background-flushed
storage, cross-process report sequencing and report-abuse throttling remain
unfinished; no “all bugs fixed” or reference-parity claim is justified.

### Greeting correctness increment

Fixed single-pass greeting substitution (names/chat titles cannot introduce
new placeholders), true membership transitions including restricted is_member
and departing administrators, multiline layout preservation, strict toggles and
personal-identity checks. Overlong input is rejected before the store's silent
1500-character truncation; oversized expanded delivery is refused, not sliced.
Welcome studio and update panels use the current theme. Greeting storage still
background-flushes; Telegram send failures remain isolated, not automatically
retried. This does not complete the all-feature bug audit or reference parity.

### Filter studio and improvement suggestions

Upgraded filter pagination/full-detail preview, multiline input preservation,
2000-character reply rejection, a 100-new-filter/group cap, personal-identity
checks and strict deletion arguments. Deleting now cleans author metadata.
Existing substring/first-stored-match semantics remain intentionally unchanged.
Management responses are group-visible and persistence still background-flushes.
Prioritized design suggestions are recorded in NEXT_IMPROVEMENTS.md, not claimed
as delivered features. Full-reference audit and complete parity remain pending.

### Confirmed Post Maker template persistence

Dedicated tenant/group SQL template rows now provide awaited saves/resets and
fresh reads for display/preview/publication, refusing configured-DB failures
without stale or file fallback. Existing PostgreSQL document values remain a
read-only compatibility source only until a dedicated row is explicitly saved.
Reset durably overrides old document values. Remaining greetings, filters,
reports and audit settings still need their own durability upgrades.

### Confirmed greeting settings

Dedicated SQL welcome/goodbye rows now support awaited saves/toggles and fresh
command/event reads. Atomic enabled-only updates preserve newer text against
stale caller state; explicit off survives reconnect. Legacy PostgreSQL document
layouts remain only until first explicit row creation, never as outage fallback.
Filters/reports/audits still need their own confirmed-write upgrades.

### Clone workflow polish

Repeated `/clone` now resumes the existing private draft without resetting its
expiry, nonce or credentials. Resume restores appropriate feature/consent/create
controls and gives stage-specific guidance without echoing secrets. Confirmation
uses a structured premium review card with isolated destinations and clear Owner
semantics. A starting draft is protected against lazy expiry/replacement while
manager startup owns it; explicit lifecycle completion still clears secrets.
Broader clone persistence/rollback/recovery work remains pending; no full workflow
redesign or live assistant validation is claimed.

### Encryption clarification and clone onboarding

User questioned whether TOKEN_KEY is needed. Explained its role and preserved
secure clone encryption rather than silently disabling it. Clone setup now
explains deployment-Owner responsibility, distinguishes the key from user bot
credentials and requests no secrets while encryption is missing. Empty clone
management directs users to guided private setup. Ordinary non-clone commands
do not require the key. No production secret was generated/changed or requested.

### Batch delivery preference and utilities batch

User explicitly requests grouped batches, with command-by-command testing inside
each batch rather than tiny isolated deliveries. Upgraded id/info/time/repo as
one batch: themed identity/profile panels, sender-chat honesty, moderator-gated
warning/trust metadata, validated IANA clock and corrected repository URL cell.
Keep listing changed commands and actual tests; no merge without second approval.

### Eight-command Encoder batch

Validated encode/compress/sample/toaudio/screens/encinfo/enccancel/encpreset
arguments and sender identity, corrected cancellation scope and empty downloads,
reaped cancelled probe/tool children and removed the unread stderr pipe/raw tool
error rendering. Existing real FFmpeg tests plus regression tests validate this
batch. Do not claim all media resource/sandbox/cleanup risks are resolved.

### Six-command transfer batch

Upgraded leech/mirror/tasklist/taskstatus/leechstats/taskbackend with personal
identity/argument validation, paged owned history, URL-free new transfer labels
and enqueue logs, withheld sensitive shared-job details/errors and caller-only
active counts. Shared task history remains process-local; this is not durable
transfer recovery or a full network/download security audit.
