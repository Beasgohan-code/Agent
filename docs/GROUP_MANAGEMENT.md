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
