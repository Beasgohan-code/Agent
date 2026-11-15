# Miss Rose workflow integration status

The Miss Rose documentation remains part of Meiko's group-management scope. It
has not been replaced by the downloader/clone work and is not claimed complete.

## Source of truth

- Reviewed sitemap: https://missrose.org/sitemap.xml
- Per-feature source URLs, implementation paths, tests and limitations:
  [`group_management_review.json`](group_management_review.json)
- Cross-repository task and validation history:
  [`implementation_checklist.json`](implementation_checklist.json)
- Reproduce the local declaration audit:
  `.venv/bin/python tools/group_management_audit.py`

The saved review covers **50 documentation pages and 31 feature groups**:
18 partial, 11 not implemented, one reference-only and one implemented with
differences. This counts reviewed feature groups, not completed commands or
proof of runtime parity. Source pages were not re-fetched during the history
reconciliation because the workspace outbound allowlist excludes missrose.org.

## Product boundaries that remain in force

- Group moderation/core stays available and consumes no optional-plugin slots.
- Ordinary optional plugins require tenant Owner approval and group-admin
  activation, with at most three optional plugins active per group.
- `/trust` and retired vault commands are not reintroduced by historical docs.
- Existing command/callback/storage identities, permissions and attribution are
  preserved unless an explicitly reviewed change says otherwise.
- Clone workers reuse AgentBot. Premium gating and clone-owned encrypted
  credentials still apply; group controls do not bypass those requirements.

## Remaining work

Use each feature's `differences_and_remaining` field for exact scope. Major
unfinished areas include typed locks, cross-chat federation ban enforcement,
warning-authority normalization and restart-safe onboarding. Partial metadata or
preference commands must not be mistaken for enforcement or notification
services. All seven supplied reference repositories and TypeTube remain in
scope alongside the Rose workflows.

## Historical documentation

The README and existing `docs/references/` files were preserved during remote
history reconciliation rather than accepting their deletion. Older architecture
and parity documents describe earlier checkpoints and may contain stale
examples. The current source and the JSON audits above take precedence; old
mentions do not register commands, enable plugins or authorize data migrations.

No production deployment, schema migration or pull-request merge is implied by
this status document. Docker builds and live Telegram/voice/TypeTube/provider
verification are still separate pending checks.
