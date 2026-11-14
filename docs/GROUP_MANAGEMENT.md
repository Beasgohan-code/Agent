# Agent — group-management architecture audit

## Product contract

Agent is primarily a professional group-management bot. Moderation, group
settings, filters, welcome/goodbye, reports and verification are mandatory core
systems, alongside navigation and Owner operations. Core availability cannot be
disabled through `PLUGINS`, runtime controls or old persisted disabled flags.
Rules remain configurable: making verification available does not force every
new member to verify. Mandatory systems consume no optional slots.

Owner approval is global within a bot tenant. Authorized group administrators
may activate approved optional plugins for their own group: at most three active
per group. Installation trust approval and product availability approval are
separate decisions. The trusted-code installer is not a sandbox.

## Existing systems (source audit, not a 210-feature claim)

| System | Existing implementation | Important remaining work |
| --- | --- | --- |
| Moderation | `modules/moderation`: warnings, escalation, mute/unmute, kick, ban/unban, purge, notes, trust, audit view | Durable case identifiers, searchable cases, consistent action history |
| Permissions | `moderation.is_moderator`, per-action checks, protected-target checks | Review all mutation paths and callbacks for Telegram granular rights |
| Protection | Flood, duplicate, link/invite and keyword checks with configurable actions | Mention spam, raid detection, durable windows and escalation workflows |
| Group settings | `modules/group`: rules, pins, admin list, warn limit, lockdown | Integrated control center; preserve pre-lockdown chat permissions |
| Filters | Keyword response CRUD and non-command watcher | Rule priorities, richer conditions and safe automation |
| Onboarding | Welcome/goodbye; verification button, restriction and expiry | Persist pending verifications; restart currently loses pending timers |
| Reports | Report list, resolution callbacks and appeals | Search, pagination, case assignment and durable case lifecycle |
| Records | `platform/chats.py`: group-keyed members, settings, logs, reports | Relational member/case data and concurrency-safe writes |
| Presentation | Rich panels/tables, action routing and editable plugin panel | Unified permission-aware group dashboard and navigation |
| Optional runtime | Deployment selection, global handler attachment/removal, disabled-state persistence | Per-group dispatch, task/listener ownership and teardown |
| Analytics | Existing bounded activity records | Explicit metric definitions, retention, group aggregation and dashboard |

The group store is PostgreSQL-backed JSONB when configured, partitioned by group
inside a bot-scoped document. It is **not** safe for concurrent read/count/write
slot reservations. Optional modules still use the existing deployment-wide
runtime; this change does not silently impose three slots on existing groups.

## Next implementation boundaries

1. Audit command and callback permissions; separate mandatory event handling
   from optional execution. Today watchers use separate dispatcher groups, but
   startup/build still shares a process and is not a fault-isolated pipeline.
2. Introduce PostgreSQL catalog and activation tables keyed by tenant and group.
   Serialize all group activation mutations with a transaction-scoped group lock,
   recheck Owner approval inside the transaction, enforce a unique plugin row and
   count active/reserved slots while holding that lock. Global blocking must
   serialize against activation too. No local-file fallback for reservations.
3. Route commands, callbacks and controlled events through per-group eligibility.
   A globally registered handler is not itself a per-group activation. Remove
   group-owned subscriptions, jobs and listeners on disable, without detaching
   other groups' handlers. Failures must leave mandatory moderation operational.
4. Build the existing settings entry point into the Group Control Center using
   live data, authorization on every press, pagination and confirmations.
5. Reconcile the 210-capability target against tests and source, recording each
   capability as implemented, partial or planned. Do not manufacture commands to
   meet a count or port unsafe remote execution features as moderation tools.

## Compatibility in this pass

Narrow builds and clone profiles now retain the mandatory group core. `tiny`
means no optional tools, not no moderation. Existing optional deployment choices
remain unchanged. Previously disabled core modules become available on startup.
No new commands, external services or credentials are introduced.

## Render rolling deployment handover

For a Render **web service**, set its Health Check Path to `/health/live`.
The HTTP server binds to `0.0.0.0:$PORT` before database and Telegram startup.
This is process liveness, not a claim that Telegram is connected. A replacement
may remain in standby while the previous process owns the token lease. Once
Render retires the predecessor and it releases the lease (or its lease expires),
the replacement connects. Never delete or steal a live lease to force a deploy:
that risks duplicate bot sessions. A genuinely separate service using the same
token must be stopped. Background workers retain the bounded lease wait.

The shutdown wrapper closes HTTP, stops the heartbeat, releases only its own
lease and closes PostgreSQL even after startup failure. The heartbeat starts
immediately after acquisition, before Telegram, voice or clone initialization.

### Lease safety during database outages

An unavailable database is not evidence of lease ownership. Acquisition now
refuses unprotected startup, and failed renewals signal shutdown. Once a process
selects a PostgreSQL lease, it cannot silently downgrade to a container-local
file lock after disconnection. Web standby retries include a delay to avoid
hammering the database. Operators should expect reduced availability during a
database outage rather than duplicate bot responders.

Cleanup attempts continue through optional voice/clone shutdown failures so
Telegram disconnect is not skipped. Database cleanup also runs if HTTP cleanup
or lease release raises. These changes are covered by regression tests; live
Render rollout still needs to be verified on the deployed branch.

## Videl1 reference review — permission safety

Reviewed the local reference files `refs/Videl1/helper/chat_status.py` and
`refs/Videl1/modules/plugins/antiflood.py` for granular administrator rights,
restriction behavior and enforcement flow. They are behavioral references, not
code copied into Agent. Their presence does not establish feature parity.

Agent's lockdown previously unlocked groups with generic open permissions.
It now reads the current Telegram permissions, stores a group-scoped baseline,
and restores that baseline instead. Repeated lock/unlock operations are no-ops;
a missing legacy baseline or unreadable permissions refuses unsafe mutation.
Typos in the mode are rejected. Failed unlocks preserve recovery state. Local
concurrent requests are serialized per group; cross-process transactional group
state and crash-atomic Telegram/database updates are not implemented by this fix.
The existing document store's asynchronous persistence limitations still apply.

### Recovery-command review

`refs/Videl1/modules/commands/admin.py` restores Telegram's current group default
permissions during unmute recovery. Agent now uses that behavior for `/unmute`
instead of generic send/media permissions, refuses when defaults are unreadable,
and protects administrator targets. This restores current group defaults, not
any older per-member custom restriction; it is not a historical rollback.

Mute, unmute, kick, ban and unban now report Telegram RPC failures to the caller.
Flood waits are reported without blocking the update handler for a long sleep or
automatically replaying a destructive action. Tests verify failed requests do
not create success log entries. A kick remains two Telegram requests: if unban
fails after ban succeeds, the operation is partial, not transactional.

### Partial kick recovery

All three kick paths (manual command, warning escalation and anti-spam) now share
one implementation. A confirmed ban followed by an unconfirmed unban records
`kick:incomplete`, not a successful kick. The notice states that the member may
still be banned and provides `/unban <id>` as a recovery action. Flood-wait
failures include the retry delay. The bot does not automatically replay the ban.
The anti-spam watcher contains recovery-notice failures as well. This improves
observability and recovery, not atomicity across the two Telegram requests.

## Upgrade phase: security and relational plugin permissions

Completed in this phase:

- Unknown/missing target membership and lookup errors fail closed for moderation
  and automatic anti-spam actions. Warning escalation checks the target too.
- Third-party execution is refused even for approved digests. Automatic startup
  loading is removed. Inspection is not process isolation.
- Local plugin staging rejects symlinks and unsafe slugs; activation re-inspects
  source rather than trusting a stale inspection object.
- Required database mode refuses file reads as a fallback for absent documents,
  refuses offline file writes, and stops startup after a failed document load.
- Relational plugin-use service provides Owner approval, activation/deactivation,
  per-group configuration and history. Catalog row locks serialize revocation
  against activation; a group-specific advisory lock serializes slot checks.
- Revocation removes activation rows and marks resource records cleanup-pending
  atomically. Core never consumes slots. No JSONB count/write fallback exists.

Five additive tables are created by the normal database bootstrap:
`agent_plugin_catalog`, `agent_group_plugins`, `agent_plugin_config`,
`agent_plugin_history`, `agent_plugin_resources`. No existing data is dropped or
converted. Approval defaults to false. Configuration uses per-group JSONB rows,
not a shared document counter. Existing deployment plugin settings are not
silently converted to Owner approvals or group activations.

Not completed by this phase:

- Telegram catalog/activation UI and execution-boundary routing.
- Runtime job/listener teardown, including cleanup-pending resource processing.
- An external-process capability protocol (execution remains disabled).
- Relational members/cases, persistent verification, database recovery and
  document-store write consistency beyond the fail-closed changes listed above.
- Full Control Center, granular-permission audit of every callback, and the
  detailed 200+ capability matrix. The earlier audit is a system-level inventory,
  not a substitute for that requested matrix.

Do not treat the new service alone as end-to-end enforcement. Existing optional
commands still use the deployment-wide runtime until routing and teardown are
integrated. Mandatory core availability is retained.

Validation: full suite with a disposable PostgreSQL server: **626 passed**, no
skips. The integration test exercises concurrent activation, fourth-slot refusal,
group isolation, configuration isolation, deactivation, resource cleanup markers
and a revocation/activation race. It is opt-in via `AGENT_TEST_DATABASE_URL` when
running elsewhere; no production database is used by default. Without that
variable the normal run reports 625 passed and one skipped. `pgserver` was used
only in the local test environment, not added to application requirements.
Compile checks, pyflakes and whitespace checks passed.

Deployment: no new application environment variables. Existing `DATABASE_URL`
and `OWNER_ID` are used by the service; `DB_REQUIRED=1` now refuses legacy local
fallback. Import any needed local-only state deliberately before requiring the
database: this phase intentionally does not auto-import stale disk documents.
Keep Render's liveness path `/health/live`.

## Execution-routing phase (supersedes earlier routing/UI pending notes)

`platform/execution.py` now gates group optional-module commands, registered
callbacks/deep links and watcher callbacks using live PostgreSQL eligibility.
Callback/deep-link ownership is captured while the module builds. Mandatory
modules are not wrapped. Missing chat origins are refused rather than assumed
private. Private optional tools retain deployment-scoped use; their group-use
approval does not change private availability. Runtime disable still blocks
private callbacks and deep links.

Group invocation tasks are owned children, so cleanup cancels plugin work rather
than a shared dispatcher worker. JobQueue inherits group/module ownership through
execution context and rechecks approval before starting queued work. Group cleanup
cancels only matching jobs and invocation tasks. Music registers queue/call
cleanup and rechecks eligibility before advancing an ended stream. Global revoke
and group deactivate invoke local cleanup after commit; a two-second reconciler
handles other processes and existing deployment-wide toggles. New calls never
use a cached approval. Optional build failures restore callback registrations and
leave core modules available. Generic arbitrary-task/subscription ownership and
durable resource-row lifecycle processing are still incomplete.

### Telegram workflow

- Owner: `/plugin <slug> approve|revoke` changes global group-use permission.
  Existing Owner deployment-wide `on|off` controls remain separate.
- Group administrator: `/plugins`, or the button under `/settings`, opens a live
  paginated table of approval, activation and deployment availability. The panel
  shows actual remaining slots. It rechecks the presser's manage-chat rights,
  provides activation and a disable confirmation, and edits the same message.
- Private-only plugins are not offered for activation in groups; this prevents
  pretending that changing a catalog row makes private handlers group-safe.
- The full multi-section Control Center, searchable members/cases, plugin-specific
  configuration forms and group feature-data isolation remain incomplete.

No additional migration or application environment variable is needed beyond the
five tables introduced previously. Group optional execution now fails closed if
PostgreSQL or approval is absent. Deployments relying on group music must set up
DATABASE_URL, SESSION_STRING and Owner approval, then activate it in the group.
No live Telegram/Render rollout was exercised in this environment.

Validation: **641 passed**, with real disposable PostgreSQL enabled; compileall,
pyflakes and whitespace checks passed. Added regression tests for execution gates,
callback rechecks, queued-job rechecks, cross-group cancellation isolation,
owned-child cancellation, optional failure containment, presser authorization,
confirmation rendering, live slot counts and private-only availability.

## Verification safety phase

Verification callbacks now require a pending session, the correct group and the
exact prompt message. A stale button cannot lift restrictions. Callback ids are
bounded, positive-user/negative-group ids; malformed input is rejected. Membership
is refreshed before unrestriction, and current group defaults are restored rather
than generic open permissions. Telegram failure leaves the session/timer intact;
success is logged only after confirmation. Callback and timeout operations share
a per-member lock.

Timeouts refuse to kick unknown or administrator targets, skip departed members,
and share the partial-kick audit path used by moderation. Old timers cannot expire
a replacement session. Shutdown cancels verification timers. Join events are
serialized, check fresh membership and trusted-member exemptions, and escape names.
If prompt delivery fails after confirmed restriction, current group defaults are
used to roll back; failed rollback is recorded as `verify:recovery_required` for
administrator recovery. This cannot make Telegram's separate calls atomic.

Important remaining limitation: pending sessions and timers are still process-local
and are not restored after restart. The durable verification migration is not
included here. Existing members affected by a restart may need administrator
recovery. Turning verification off controls new onboarding; it does not undo
existing pending restrictions automatically.

Validation: **666 passed** with disposable PostgreSQL, plus compileall, pyflakes
and whitespace checks. Added safety tests for stale/cross-group/wrong-prompt
callbacks, membership changes, failed unrestriction, baseline restoration,
timeout protection, malformed ids, failed prompt rollback, duplicate join events
and lookup failure. No new migration, environment variable or dependency.

## Guided clone setup: FileStore first

The user-facing `/clone` flow is now private, expiring and interactive:
verified token → FileStore selection → optional log channel → required archive
channel → confirmation → startup. Token format is not identity: `getMe` must
confirm a matching bot, and identity is checked again on creation. Channel
configuration verifies both the operator and clone administrator memberships and
the clone's posting rights; permissions are checked again at confirmation.
The main bot cannot clone itself; duplicate records cannot overwrite ownership.

New credentials require TOKEN_KEY; setup does not invite secret submission when
encryption or capacity is unavailable. Drafts are process-local, expire after ten
minutes and can be cancelled with `/cancel`. Secret messages are deleted best
effort, but Telegram/client history is not guaranteed to erase them. Completed
records encrypt the token; draft representations exclude it. Bot tokens do not
reveal their human creator. The authenticated setup user becomes the Owner of
that clone tenant, not the parent deployment. Legacy clones keep their previous
Owner behavior unless created by the guided flow.

Creation/restart/profile changes require bot premium, sudo or deployment Owner
eligibility. Free allowance is now zero; bot premium allows three clones and
Owner/sudo remain capped by CLONE_LIMIT. Stop/delete remain available to the
record owner after premium expiry. The supervisor parks running ineligible
clones; restore does not start them. This is bot membership, not Telegram's own
Premium subscription. Owner-only, private `/sudo add|remove <id>` and `/sudo list`
manage delegated clone eligibility. Sudo does not grant parent Owner operations,
other users' clone ownership or bypass Telegram group rights.

Clone settings now isolate bot id, link signer, data scope, assistant session,
channel destinations and HTTP port. No profile includes recursive cloning.
Worker bootstrap loads its database and acquires its own lease before Telegram
startup; heartbeat loss stops the clone, and stop/failure releases resources.
A required selected plugin missing from the built registry refuses startup.
FileStore uses the supplied clone archive channel; optional group use still
requires that clone's Owner approval and group activation.

Reference review: Videl1's clone command/manager and Videl0's premium-emoji
metadata were inspected. Videl0 is an ignored reference checkout, not a shipped
runtime dependency. Three additional custom-emoji mappings (diamond, microphone,
speaker) use reference metadata with Unicode fallbacks. Telegram eligibility and
rendering are not guaranteed by knowing an emoji id.

Not included: Music assistant-session collection, remaining guided templates,
external-process clone isolation, media-plugin completeness, durable setup drafts
or the full group-management inventory. Music credentials are deliberately not
requested until a dedicated isolated assistant lifecycle is implemented.

Deployment: configure TOKEN_KEY before accepting new clone credentials. Existing
clone records remain readable; new channel, selected-plugin and managed-owner
fields are additive in the existing encrypted clone store. Sudo uses a scoped
PostgreSQL document (or standalone file), not environment-wide implicit powers.
No new application dependency or schema migration. Existing clones no longer
inherit the parent session or channels; supply their own configuration as needed.
No live Telegram calls were made during validation: API identity/channel checks
are tested with controlled responses, while PostgreSQL integration uses a real
disposable server.

Validation: full suite **681 passed**, compileall, pyflakes and whitespace checks
clean. Added guided setup, expiry, wrong-presser, channel-rights, revoked-token,
encryption, sudo authorization, private-only collection, credential isolation,
duplicate ownership, premium-loss and worker database/lease lifecycle tests.

### Primary catalog and sender-owned clones

Primary presentation order: Encoder, Moderation, Post maker, Music, Linkshare,
FileStore, Leech, AI Agent. Moderation remains mandatory and slot-free. Renamer
is still available explicitly; it is no longer in the default optional set.
AI Agent is a credential-gated `/ask` completion adapter, not an autonomous
operator. Parent AI keys/models are cleared in clone settings. The recorded
token sender is now the Owner for all clone records, including legacy ones,
scoped to the clone's database namespace.

Validation for this increment: **700 tests passed with disposable PostgreSQL**
(699 passed and one database test skipped without PostgreSQL); compileall,
pyflakes and diff whitespace checks passed. Provider tests use mocked HTTP;
no live Telegram or paid AI request was made.

Reference-review status: clone submission and manager behavior were inspected,
including sender ownership, token verification, duplicate handling, session
cleanup and client ownership. The remaining reference repository has **not**
received a complete behavioral/security audit yet. Guided clone selection is
still FileStore-only; the eight-feature catalog must not be mistaken for eight
finished guided clone templates. Music assistant setup remains outstanding.

### Guided-template expansion and reference inventory

The previous FileStore-only restriction is superseded: Encoder, Moderation,
Post maker, Linkshare and Leech now also have single-feature guided templates.
Every template retains the mandatory safety core. Each asks for an optional log
channel; only FileStore requires an archive channel. Saved selections are
allowlisted and must contain exactly one reviewed slug. Unsupported or multiple
saved selections fail closed instead of silently running a reduced feature set.
Startup still checks that the selected plugin actually registered commands;
missing encoder binaries or other dependencies prevent a false-success result.
Music and AI Agent templates remain gated pending per-clone credential setup.

`REFERENCE_INVENTORY.md` indexes all 255 Python files at the reference revision,
with content hashes, literal command candidates and process/client review sites.
It is reproducible using `python tools/reference_inventory.py refs/Videl1
docs/REFERENCE_INVENTORY.md` and never executes reference code. The reference
entry point `__main__.py` has an unterminated string at line 33 in that checkout;
this is recorded, not fixed in or imported into Agent. Reviewed entry-point
patterns also include import-time plugin discovery and global Music/AI clients;
Agent keeps explicit module registration and credential-gated initialization.
Reference developer shell/eval commands are not being adopted. Static coverage
is complete; manual feature-by-feature parity and security review remain open.

Guided selections are displayed by feature name in `/mybots` and the profile
picker, not mislabelled as the fallback `tiny` profile. The picker warns that a
legacy profile replaces a guided selection. Validation: **722 passed** against
disposable PostgreSQL; compileall, pyflakes and whitespace checks passed.
No live Telegram/media/provider validation was performed.

### Isolated AI clone credentials

AI Agent is now the seventh guided template. It requests an OpenAI key and model
in private only after bot identity verification. The wizard discloses external
question processing, best-effort deletion and Telegram-history limitations.
Keys/models are syntax-checked, not tested using a paid provider request. Provider
billing, model access and compatibility are confirmed only when `/ask` is used.

The clone store encrypts the additional key as `ai_api_key_enc`; it never writes
a plaintext AI key, even in legacy unkeyed mode. New credentials require a key
at rest. Clone token and AI key are excluded from dataclass reprs. The manager
uses AI credentials only for an explicit AI selection, never parent credentials.
Legacy profile changes clear the stored key/model; cancel, expiry, successful
creation and startup-failure cleanup clear draft secrets. Cancellation racing
with secret-message deletion cannot restore a discarded key. Failed store adds
roll back the in-memory record. This is stateless text completion, not a tool
agent. Music remains the only primary feature without a guided clone template.

Validation for AI clone setup: **726 tests passed** with disposable PostgreSQL;
compileall, pyflakes and whitespace checks passed. Paid provider calls and live
Telegram credential/session behavior have not been tested in this environment.

### Music lifecycle prerequisites

Music credential collection remains gated. Voice startup now has a 30-second
bound, serialized start/stop transitions, explicit user-account authorization
checks and cleanup for partial connection, initialization failure, timeout and
cancellation. Assistant bots are refused. Each stop/disconnect operation has a
10-second bound; call shutdown failure cannot skip Telegram disconnect. Startup
errors expose the exception category, not provider/library exception text which
could contain credentials. Shutdown also cleans partial, not-yet-connected
engines. This does not provide an OS-level sandbox or a guarantee against a
third-party library that suppresses cancellation indefinitely.

The clone manager now starts a configured voice engine after bot login, and
cleans voice, bot, database and lease on startup cancellation/failure. Guided
creation cancellation also removes the newly saved record and clears its draft
secrets. Music assistant credential verification, account-level exclusivity and
a safe private session workflow still need implementation before exposing the
Music template; no assistant credentials are being accepted prematurely.

Validation: **741 tests passed** with disposable PostgreSQL; compileall, pyflakes
and whitespace checks passed. Voice-library lifecycle tests use mock clients,
not live Telegram calls. No real assistant account was connected.
