# Native bot mode integration

BotFather capability toggles allow Telegram to deliver additional update types;
they do not authorize privileged commands, credential replacement, or admission.

- **Guest chat:** a dedicated guest handler answers with short help through
  `answer_guest_query`. No ordinary send fallback, command dispatch, deep-link
  redemption, settings lookup, or credential processing occurs. Guest chat IDs
  are not treated as proof of membership. Tools still require the normal bot
  conversation and authorization. This is informational support, not guest AI.
- **Bot management:** creation/token-change events notify the creator privately.
  Eligible new bot IDs get an explicit `/clone managed BOT_ID` import instruction,
  bound to that Telegram-attested creator and bot for ten minutes. The event
  alone never exports a token or starts a worker. Explicit private import checks
  premium, encryption, capacity, ownership binding, expiry and draft state before
  exporting with the non-revoking API. Token identity is verified with `getMe`;
  cancellation, access, expiry and capacity are rechecked after network waits.
  The credential stays in the expiring private setup draft until the existing
  encrypted creation workflow receives final confirmation. No parent credentials
  are inherited. Existing bot IDs and the controller are never import targets:
  token-change events cannot replace saved credentials or transfer a clone.
  Offers are memory-only, bounded to 100 entries, and lost on restart. Ordinary
  manual private setup remains available. When the cached Telegram bot identity
  explicitly allows bot management, new and resumed token-step drafts offer
  **Create a bot with Telegram**. Its private, nonce-bound callback rechecks
  entitlement, capacity, encryption, draft state and capability before sending
  a one-time native creation keyboard. No extra identity lookup is required.
  Opening the native form neither attests bot ownership nor imports credentials;
  only the later managed-bot event can enable the explicit import instruction.
  Unknown/disabled capabilities leave manual setup available. Telegram client
  support and username availability still vary; suggestions are not reservations.
  Private notification delivery can fail if Telegram disallows it;
  there is no group fallback or secret-bearing error text added here.
- **Guard:** native join-request queries receive `QUEUE` (administrator review),
  never automatic approval or denial. An eight-second local timeout bounds the
  native request within Telegram's ten-second response requirement; network
  delays can still prevent delivery. Ordinary join requests are untouched.
  Existing post-join verification remains separate. No Web App challenge is
  advertised and Guard alone is not an anti-spam guarantee.

Handlers use existing plugin runtime gating and error routing. This does not
change plugin approval/activation policies, publish new commands, or enable
optional tools. Core mode handlers are controller-only under its existing
manifest; Guard follows the security module wherever that module is loaded.
Tests use synthetic updates and mocked native responses, not live Telegram.

## Validation

Initial native-handler phase: exact selective patch **2,387 passed** in 29.58
seconds; full working tree **2,469 passed** in 25.88 seconds, including unrelated
pending work. Both runs
used disposable real database storage; no tests skipped. Targeted static checks
and staged whitespace checks passed. Native tests cover separate handler types,
guest privilege isolation and no public fallback, Guard queuing/failure/deadline,
and managed-event identity checks/private notification without token access.
No live Telegram verification, deployment or production configuration changes.

Consent-based managed import phase: exact selective patch **2,409 passed** in
29.71 seconds; full working tree **2,491 passed** in 26.44 seconds, no skips.
Runs used disposable real database storage; credential exports and identity
responses were mocked. Added tests cover the native-notice-to-command route,
explicit final creation and encrypted persistence, per-user concurrent import,
creator/chat binding, expiry, capacity, encryption, existing/busy draft refusal,
post-network cancellation/revocation/capacity changes, identity mismatch and
export failure without credential disclosure. Targeted static and whitespace
checks passed. No live Telegram verification or deployment was performed.

Native creation UI phase: exact selective patch **2,425 passed** in 31.96 seconds;
full working tree **2,507 passed** in 28.13 seconds, no skips. Both runs used
disposable real database storage. Added coverage includes capability-gated new
and resumed drafts, wire serialization through the installed native library,
private/creator/nonce checks, unknown capability without network lookup,
advanced-draft refusal, cancellation, and post-acknowledgement premium/capacity/
encryption/capability changes. Targeted static and staged whitespace checks
passed. Telegram UI rendering and actual creation were not tested live; nothing
was deployed or changed in production.

## Private import links and offer generations

Managed-bot notices now include **Import into setup draft** when the controller's
cached, validated username is available. The private start link carries a random
nonce, not a bot credential. No extra identity lookup is performed; the existing
`/clone managed BOT_ID` instruction remains the fallback.

The clone module owns the `managed` deep-link prefix through the existing gated
router. Links are bound to the Telegram-attested creator, bot ID, latest event
nonce and ten-minute expiry. A forwarded link is not authority. Non-personal
senders and group contexts are refused. Each new event replaces the previous
nonce, invalidating older links and imports awaiting credential export or
identity verification. Both command and link imports check the same offer
generation after network waits. Successful import consumes that generation;
a newer event arriving during panel delivery is not accidentally consumed.
Nonce memory is bounded with the existing 100-offer limit and lost on restart.
No credentials are imported by the notice itself; final clone review and create
confirmation remain required. Existing clones still cannot be overwritten.

Validation: exact selective patch **2,438 passed** in 32.37 seconds; full working
tree **2,520 passed** in 32.00 seconds, no skips. Runs used disposable real
database storage and mocked Telegram responses. Tests cover the complete
notice/button/router/import path, command fallback without identity lookup,
creator/private-chat binding, malformed/stale/consumed links, bounded nonce
memory, and new events arriving during export or identity verification.
Targeted static and staged whitespace checks passed. No live Telegram test,
deployment, merge or production configuration change was performed.

Before this phase, the restored local checkout's history/index was reconciled
with the verified remote branch tip. All 510 checked working paths had identical
before/after hashes; pending work was preserved and staging was initially clean.

## Capability visibility and guest navigation

`/status` now separates **Reported enabled**, **Reported disabled**, and
**Not reported** for Telegram guest chat, bot management and Guard capabilities.
Only explicit boolean flags from the latest cached bot identity count as enabled
or disabled. Missing identity/fields are unknown, not assumed disabled. The card
labels this as cached capability metadata, not a live permission, delivery,
module-availability or authorization check. It does not call `get_me`.

Native guest help includes **Open private help** only when a validated cached
bot username is available. The button opens the bot's ordinary private chat;
it contains no incoming text, command arguments, redemption payload or privileged
callback. Unknown/invalid identity leaves text-only help. Replies still use only
the native guest response API, with no ordinary-message fallback.

Guard response routing was reviewed: security is protected group-management
core, so `PluginGate.wrap` returns its handler directly without optional-plugin
eligibility/storage/cleanup waits. A regression test locks down this boundary;
no gating or admission policy was loosened. The existing eight-second local
response timeout remains a bound from handler execution, not a guarantee about
Telegram delivery time or dispatcher scheduling.

Validation: exact selective patch **2,447 passed** in 30.28 seconds; full working
tree **2,529 passed** in 27.88 seconds, no skips. Runs used disposable real
database storage and mocked Telegram calls. Added coverage includes strict
boolean/unknown capability reporting, attached-client identity fallback,
private guest navigation without payload echo or network identity lookup,
invalid username refusal, and the protected Guard execution boundary. Targeted
static and staged whitespace checks passed. No live Telegram verification,
deployment, merge, or production configuration changes were performed.

## Shared setup cancellation and step boundaries

The ordinary setup workflow shared by manual and managed imports now verifies
both the live draft identity and its expected step after asynchronous checks.
Cancellation/expiry during premium eligibility can no longer restore an AI key,
advance an abandoned model/log step, or apply a stale setup callback. A rejected
old update cannot cancel a replacement draft created while the check waited.
AI and assistant-session acceptance recheck eligibility and live state after
best-effort credential-message deletion. No session/provider authorization is
claimed from syntax checks.

Channel validation stops after each outstanding Telegram read returns if its
draft was cancelled or expired, rather than continuing with cleared credentials.
Eligibility is rechecked before saving the destination. An input already queued
for one step cannot be reinterpreted as input for the next step after waiting
for the per-user lock. These are in-memory workflow checks; final create still
uses the existing encrypted store, concurrency limits and identity/permission
revalidation. No new commands, credentials, dependencies or worker writers were
introduced.

Validation: eight regression failures reproduced before the fix. Final exact
selective patch **2,462 passed** in 30.29 seconds; full working tree **2,544
passed** in 27.52 seconds, no skips. Fifteen added cases cover eligibility-time
cancellation/expiry, replacement draft safety, channel-read cancellation at
all three boundaries, post-validation revocation and queued-step isolation.
Both full runs used disposable real database storage; Telegram, eligibility and
session-format responses in the new race tests were controlled test doubles.
Targeted static and staged whitespace checks passed. No live Telegram tests,
deployment, merge, production changes or migration were performed.

## Final confirmation snapshot and draft-specific cleanup

Final clone creation now snapshots the reviewed configuration before callback
acknowledgement. A draft that returns to editing or changes fields during that
wait cannot proceed under the old Create press. The same live confirmation
snapshot is checked after identity, channel-permission and eligibility waits;
cancelled/expired validation stops before further channel reads. Current capacity
is re-read immediately before persistence, in addition to atomic store limits.

Setup cleanup can be constrained to the expected draft identity. Final-validation
failures and start completion therefore cannot discard a newer draft for the
same user. Changed drafts remain subject to a fresh review and Create press.
This does not alter encrypted persistence, worker ownership, store atomicity,
rollback policy or provider credentials. It does not claim to cancel an already
committed creation or solve transport uncertainty during persistence/startup.

Validation: six failing regressions reproduced before implementation. Final
exact selective patch **2,471 passed** in 44.77 seconds; full working tree
**2,553 passed** in 46.58 seconds, no skips. Nine new cases cover changes during
acknowledgement, cancellation/replacement at validation boundaries, old-request
failure cleanup, expiry before channel reads, and capacity lowered during
validation. Both suites used disposable real database storage; Telegram
responses and the new interleavings were test doubles. Static and staged
whitespace checks passed. No live Telegram test, deployment, merge, production
configuration change or migration was performed.

The restored checkout was again reconciled with the verified remote tip before
this phase, preserving all 510 checked working paths byte-for-byte and leaving
staging clean before selective edits.

## Save/start cancellation and uncertain acknowledgements

Cancellation during final persistence now clears only the expected setup draft
and re-raises cancellation. A draft already marked `starting` therefore cannot
remain indefinitely with its credential fields attached when its save wait is
interrupted. Clearing fields is not a guarantee of zeroing Python process memory.

A cancelled save has an uncertain commit outcome: this path does not retry the
write, delete a possibly committed record, or invoke worker startup. A committed
record remains authoritative and should be inspected through `/mybots` before
retrying. Existing lifecycle recovery still owns any later reconciliation; this
change does not promise rollback or that another authorized worker cannot act.

Startup-failure cleanup retains its existing single removal attempt. If storage
cleanup fails while startup was cancelled, the cancellation is no longer swallowed
as a normal error response. A type-only `#Errors` warning reports unavailable
cleanup without provider error text or credentials. Cancellation during cleanup
also clears the expected draft and propagates, without retrying the deletion.
Storage/worker lifecycle policies and encryption keys are unchanged.

Validation: three regression failures reproduced before the fix. Final exact
selective patch **2,476 passed** in 38.68 seconds; full working tree **2,558
passed** in 35.88 seconds, no skips. Five new cases cover cancelled saves before
and after commit, cancellation with cleanup failure, cancellation during cleanup,
and a real two-connection disposable-database test that cancels after an actual
commit and independently verifies the retained encrypted record. New worker and
Telegram interactions were mocked; both full suites used disposable real storage.
Static and staged whitespace checks passed. No live Telegram verification,
deployment, merge, production configuration change or migration was performed.
