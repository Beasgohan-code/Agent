# My Bots control centre: implementation map and phased plan

## Actual surface and authority

My Bots is the Telegram `/mybots` / `/panel` interface in `agent/modules/clone/__init__.py`, not a browser application. This change upgrades that implementation; there is no new web mock, CSS framework or alternate database. Mobile layout means bounded native tables, short navigation rows and paginated lists; browser viewport tests would not prove Telegram rendering.

| Capability | Existing backend / UI | Gap and integration path |
|---|---|---|
| Saved identity, owner, channels, feature selection | `clone/store.py`, encrypted Clone records | Dashboard reads whitelisted fields; photo not fetched. Saved names/usernames are not a fresh Telegram verification. |
| Start, stop, restart, restore, supervision | `clone/manager.py`, `clone/lifecycle.py`; existing `clone:` controls | Preserve these implementations. New dashboard lifecycle controls need expected-revision/generation/actor checks at the durable mutation authority, not only a UI check. |
| Configuration writes and validation | `clone/configuration.py` canonical writer; `catalog.py`, `profiles.py`, `manager.settings_for` | Integrate new editors with `write(actor_id, expected_revision, request_id, changes)`. No new settings store. Current profile editor remains linked. |
| Configuration persistence | `platform/db.py` `agent_documents`; scoped `clones`, `clone_configuration:<id>`, request receipts | Encrypted snapshots, transaction/advisory locks, CAS; no new tables needed for this slice. DATABASE_URL remains authoritative. |
| Reconciliation and applied state | `clone/reconcile.py`, `revisions.py`; `agent_lease` worker/reconciler leases | Show desired/applied/pending metadata, not an inferred success. Application acknowledgement is revision/lease/generation fenced. |
| Guided creation | `clone/setup.py` identity verification, channels, selection, credentials, confirmation | Sessions currently in process, expiring; durable encrypted resume/checklists not implemented. Do not claim resume across restarts. |
| Worker help and discovery | `ui/workers.py`, registered manifests, callbacks | Worker-local guides/search/details exist. Controller directory in this slice reads the actual local worker registry, including disabled manifests and enabled-only command pages. |
| Group settings, rules, warnings, restrictions, notes | `modules/group`, `moderation`, `platform/group_rules.py`, `platform/chats.py` | Existing worker/group commands enforce group-admin authority. No generic controller notes editor; audit unsupported notes separately. |
| Anti-spam, blocklists, verification | `platform/antispam.py`, `blocklists.py`, `modules/security`, `group/controls.py` | Worker/group scoped, mandatory availability retained. Controller-wide arbitrary mutation is not added. |
| Greetings, filters, reports, federations | `modules/welcome`, `filters`, `reports`, `federations` | Use existing command/service validation; dashboard reports manifests, not fake Save/Reset buttons. |
| FileStore, Encoder, Linkshare, Leech | Corresponding `modules/*`, jobs/storage/link services | Per-worker settings/credentials and manifest requirements exist. Generic field editor needs feature-specific adapters and safe validation. |
| Music, Post Maker, AI Agent, Renamer, Utilities | Corresponding `modules/*` | Some depend on own credentials/capabilities; registered does not mean provider-ready. Preserve remote-playback refusal and AI privacy limitations. |
| Optional plugin approval / activation | `platform/plugin_access.py`, `modules/group/plugin_panel.py`, `ops` runtime controls | Owner approval + group activation + max 3 slots; mandatory moderation remains slot-free and cannot be disabled. |
| Logging, health, events | `platform/logs*`/logbook, `health.py`, `platform/clone_recovery.py` diagnostic records | Local activity/health only where worker exposes it; raw errors/credentials never rendered. Owner-safe event/log feed is not exposed in this slice. |
| Scheduling | Audit actual registered commands and job queue, not assumptions | No general scheduling configuration adapter exists in the dashboard. |
| Deletion | Existing `manager.stop`, `store.aremove` | Reuse cleanup authority; dashboard refresh rereads canonical store and rejects deleted records. Broader worker-data retention/deletion policy needs explicit audit. |

## Ordered implementation slices

1. **This slice:** owner-private per-clone dashboard, configuration metadata, actual local command/plugin catalogue, diagnostic availability, working My Bots entry/navigation. No new mutating callback. No schema changes.
2. Lifecycle UI hardening: durable owner/revision/generation admission for Start/Stop/Restart/Reconcile and confirmation/error recovery, including old callback compatibility. Test concurrent stop/start/delete/ownership changes using PostgreSQL before exposing new mutation buttons.
3. Revision-aware configuration editor: preview/validate/save supported non-secret fields first; then individually audited secret/feature adapters. Use canonical writer, receipt identities and reconciler; persist no UI-only toggles.
4. Durable onboarding/checklist and contextual help from effective runtime manifests, credentials presence (never values) and verified group permissions; encrypted unfinished drafts with expiry/cleanup.
5. Owner-private diagnostic timeline, command search/categories and configuration controls where genuinely supported; paginated My Bots search/filter/recent-management views based on real data.

## Delivered slice and limits

The dedicated `cc:` dashboard routes authorize only the saved clone owner in that owner's private chat, reloading the canonical registry on every press. Unlike legacy controller-admin management paths, these new views do not grant the deployment Owner access to another owner's dashboard. They make no mutation. Existing lifecycle and profile controls remain in place, including their existing policy; their hardening is a separate gate.

The new `CloneManager.observe_worker` returns only whitelisted local registry/health facts, never a Clone serialization, token, key, session, raw error or provider configuration value. No worker is constructed for a stopped/unobserved clone just to manufacture command counts. Local absence is **not** fleet-wide offline status. Displayed enabled plugins include shell/mandatory modules; counts are explicitly registration counts, not group grants. Built-in navigation outside PluginRegistry is sourced from the running bot's own effective catalogue.

Unsupported items are text labelled Unavailable, not nonfunctional buttons: profile-photo fetching, per-worker CPU/RAM (workers share a process), event/log viewer, generic configuration reset, per-command toggles, new direct lifecycle controls and durable onboarding resume. No isolated-worker or full platform completion claim. Source licences and clone credit-free worker screens remain unchanged.

Validation evidence is recorded in `CODEBASE_AUDIT.md`. Test clients are synthetic; PostgreSQL transactions are real and disposable. No deployment or PR merge is authorized.
