# Upgrade batch: reliable shared rich UI delivery

## Changes

Shared send/reply/edit paths now distinguish explicit rich-format rejection
from unrelated delivery errors. Only explicit unsupported rich-feature errors
turn off native rendering process-wide. An invalid individual rich card falls
back locally. Unknown errors, transport timeouts, permissions and rate limits
propagate to existing caller error handling instead of attempting a second
send or permanently removing native tables from other plugins. A timeout can
have ambiguous delivery status, so an automatic second send is unsafe.

Rich reply fallback preserves its original keyboard and delivery options.
Caller-supplied reply parameters are respected instead of passed twice.
A noncallable send_rich_message attribute is no longer a capability signal.
Prebuilt rich panels are converted to their classic form if support was
disabled between construction and sending. Supported clients still receive
native Rich Message tables, and existing premium emoji/fallback styling is
retained. Existing menu/help/runtime-panel identities remain unchanged.

## Scope and verification

No commands added, removed or renamed. No dependency, database, stored-data,
production or clone-credential changes. No reference implementation copied.
This upgrades shared delivery used by multiple plugins, not all source features
or a new visual redesign.

Added 17 regression cases covering keyboards/options, explicit reply targets,
capability detection, local invalid-card fallback, prebuilt disabled cards and
transport/permission/rate errors across send/reply/edit. Full disposable
PostgreSQL suite: **991 passed**. Compileall, pyflakes and diff checks passed.
No live Telegram or visual client verification was performed.

## Remaining limits

Explicit rejection recognition currently covers RICH_MESSAGE_UNSUPPORTED,
RICH_MESSAGES_UNSUPPORTED, RICH_TEXT_UNSUPPORTED, RICH_TEXT_INVALID and
RICH_MESSAGE_INVALID. Unknown server error identifiers deliberately propagate
until verified, rather than being guessed as rich-format rejection. The
existing process-wide capability switch is not yet scoped per clone client.
Raw classic-string custom-emoji rejection and per-client capability discovery
remain separate work. Caller retry policies still require normal review.
Source integration, plugin-specific UI design, native music fetch safety and
end-to-end Telegram feature verification remain unfinished. No merge or
deployment is authorized by this batch.
