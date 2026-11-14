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
