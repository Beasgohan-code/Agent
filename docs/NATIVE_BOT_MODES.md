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

## Creation completion versus ready-message delivery

Once persistence and worker startup return successfully, setup clears the draft
and releases the global creation lock before building/sending the ready message.
A slow notification therefore does not serialize other owners' creations behind
Telegram delivery. The card uses the created record's identity and plugin
selection, not a potentially changed setup draft.

A failed or timed-out ready notification no longer enters the creation-error
handler or sends a misleading second "creation unconfirmed" message. There is
no added resend, rollback, deletion, worker stop or creation retry. A type-only
`#Errors` warning reports unconfirmed notification delivery without raw provider
text or credentials. Cancellation still propagates and leaves the successfully
saved/running clone intact. Users can inspect `/mybots` if the message is missing;
this is not proof that Telegram displayed or delivered any notification.

Validation: three failures reproduced before implementation. Final exact
selective patch **2,482 passed** in 37.70 seconds; full working tree **2,564
passed** in 34.98 seconds, no skips. Six new cases cover notification error and
timeout without resend, cancellation without rollback, secret-safe logs, lock
release, and a controlled two-owner interleaving where the second creation
finishes while the first owner's notification is blocked. Both full suites used
disposable real database storage; new notification/worker interleavings were
controlled test doubles, not live performance measurements. Static and staged
whitespace checks passed. No live Telegram verification, deployment, merge,
production configuration change or migration was performed.

## Supporting identity commands: reply accuracy and bounded profile reads

`/id`, `/info`, and `/userinfo` now resolve unloaded replies with the existing
shared reply resolver. An unavailable or wrong-chat reply fails closed instead
of silently selecting the caller. Explicit profile targets bypass reply loading;
`/myinfo` always selects the caller without fetching a reply. Sender-chat replies
never expose a synthetic personal sender as the hidden human administrator.

Private profiles skip membership and moderator queries and label membership not
applicable. Group membership, authorization and optional moderation reads each
have a five-second bound. Storage or lookup errors preserve the public profile,
with unavailable metadata where appropriate; authorization failure never grants
access to moderation details. Diagnostics log exception types, not raw messages.
Cancellation propagates and does not send a fallback profile. These are per-read
bounds, not an end-to-end delivery deadline.

Validation: initial targeted suite reproduced nine failures before implementation.
Fourteen regression cases added overall. Exact selective patch: **2,496 passed**
in 31.22 seconds; full working tree: **2,578 passed** in 31.39 seconds, no skips.
Both full suites used disposable real database storage; identity API calls and
controlled timeout/cancellation tests used test doubles, not live Telegram.
Focused suite: **43 passed**. Changed-file static and staged whitespace checks
passed. No deployment, merge, production changes or live Telegram verification.

## Shared reply resolver: loaded-reference validation

Already-loaded replies now validate an available reply reference before returning
a target: the reference must be a positive integer, and the source ID must be an
integer matching it. Topic-header references are rejected before either the
loaded or fetched path. Existing same-chat validation remains in place. Valid
loaded replies remain network-free; legacy loaded messages without a separate
reply-reference field retain their existing behavior.

Three regression tests cover six invalid loaded-reference/topic combinations,
valid loaded-reply reuse, and moderation resolution refusing a mismatched reply
instead of selecting either its sender or an explicit fallback ID. Two tests
failed before implementation. Exact selective patch: **2,499 passed** in 37.27
seconds; full working tree: **2,581 passed** in 31.45 seconds, no skips, both with
disposable real database storage. The initial focused run without that storage
had 55 passed and one storage-dependent skip; full runs cover it. Changed-file
static and staged whitespace checks passed. No live Telegram verification,
production changes, deployment or merge.

## Administrator command text-mention targeting

Promotion and strict administrator target parsing now bind a text mention to the
first target argument by its Telegram UTF-16 offset and length. Missing,
duplicate, misplaced, out-of-range or split-surrogate spans are rejected rather
than selecting an unrelated entity. Valid multiword and non-BMP display names
resolve without a user lookup. Promotion titles are parsed after the complete
mention and pass the same length/control-character validation as other targets;
strict target commands reject trailing arguments. Reply targeting and live
permission checks remain unchanged.

Validation: 13 new cases failed before implementation. Added 15 cases overall,
including command-handler checks that malformed mentions cause neither user
lookup nor administrator/title mutations. Two old mention fixtures were updated
to include actual visible target text and Telegram-style spans; one was caught
by the first full run. Final exact selective patch: **2,514 passed** in 29.07
seconds; full working tree: **2,596 passed** in 28.78 seconds, no skips, both with
disposable real database storage. Changed-file static and staged whitespace
checks passed. Telegram calls used test doubles: no live verification,
deployment, merge or production changes.

## Moderation username lookup bounds and safe errors

The shared restriction target parser bounds username lookups to five seconds and
accepts only positive, signed-64-bit personal integer IDs (not booleans). Provider
errors and invalid lookup results become a locally authored `TargetLookupError`;
logs contain exception types, not raw provider text. Approval commands distinguish
that safe lookup error from syntax errors, avoiding misleading usage-only replies.
Cancellation propagates without retry, and no target is selected on lookup failure.
This bound applies to the username read, not the whole moderation operation.

Four new regression tests cover provider errors before restriction mutation,
six invalid result identities, timeout cleanup, and cancellation without retry.
Three tests failed before implementation. Final exact selective patch: **2,518
passed** in 31.86 seconds; full working tree: **2,600 passed** in 28.26 seconds,
no skips, both with disposable real database storage. Focused tests initially
without storage: 26 passed, 16 storage-dependent skips; full runs cover those.
Changed-file static and staged whitespace checks passed. Telegram calls used
test doubles; no live verification, deployment, merge or production changes.

## Moderation text-mention span integrity

The shared restriction parser computes the target argument's actual UTF-16
offset rather than searching for its text inside the whole command. Names that
also occur within the command word therefore resolve correctly. At the target
position, duplicate entities, nonpositive/noninteger or oversized lengths,
split-surrogate boundaries and spans ending inside a visible name are rejected
with locally authored validation errors. Valid multiword/non-BMP target names
preserve the remainder as the reason; mentions later in that reason remain
allowed and do not change the selected target. Reply and username behavior is
unchanged.

Three new regression tests include eight malformed span lengths, duplicate
target entities, a Unicode multiword target with a second mention in the reason,
and a command-substring target. Two failed before implementation. Exact selective
patch: **2,521 passed** in 31.36 seconds; full working tree: **2,603 passed** in
28.76 seconds, no skips, both with disposable real database storage. Focused run
without storage: 51 passed, one storage-dependent skip; full runs cover it.
Changed-file static and staged whitespace checks passed. Telegram interactions
used test doubles; no live verification, deployment, merge or production changes.

## Warning variants: outcome versus notification delivery

After `/dwarn` or a partial `/swarn` records its final outcome, a failure sending
the outcome notification no longer enters the action-error handler, rewrites the
recorded outcome as unconfirmed, or attempts a fallback reply. It emits only a
type-only notification warning. No warning, escalation or deletion is replayed.
Cancellation during notification still propagates without rewriting the outcome.
This change does not claim delivery or change handling of failures before the
final outcome is recorded.

Seven added regression cases cover notification exceptions/timeouts for applied
and partial outcomes, including partial silent warnings, secret-safe logging,
no resend or action replay, and cancellation. The initial tests reproduced two
failures before implementation, then coverage expanded across outcome variants.
Focused tests: **13 passed**. Exact selective patch: **2,528 passed** in 32.26
seconds; full working tree: **2,610 passed** in 29.59 seconds, no skips. Both full
suites used disposable real database storage; new warning/notification tests use
controlled doubles, not live Telegram or durable-outcome integration proof.
Changed-file static and staged whitespace checks passed. No deployment, merge,
production changes or live verification.

## Delete-warning cleanup: partial outcomes and bounded requests

After the warning write and any escalation, `/dwarn` message deletion now has a
ten-second request bound. Exceptions and timeouts are classified as partial
cleanup results rather than making the recorded warning sound uncertain. The
handler records partial once and reports the warning count with cleanup marked
unconfirmed. No warning, escalation or deletion retry is introduced; diagnostics
contain only exception types. Cancellation during cleanup still propagates,
leaves the admitted outcome unresolved, and sends no completion claim.

Initial tests reproduced two cleanup-failure misclassifications. Four additional
regression cases overall cover provider error, timeout, cancellation of a blocked
delete request, and command cancellation during cleanup. Focused tests: **17
passed**. Exact selective patch: **2,532 passed** in 32.57 seconds; full working
tree: **2,614 passed** in 30.67 seconds, no skips. Both full suites used disposable
real database storage; cleanup interleavings and Telegram requests used controlled
doubles, not live Telegram or durable-outcome integration proof. Changed-file
static and staged whitespace checks passed. No deployment, merge or production
changes.

## Warning secondary audit failures do not suppress required actions

After a confirmed warning write, failure of the secondary local audit log no
longer skips threshold escalation or `/dwarn` cleanup. It is logged with only the
exception type, contributes a partial final outcome, and is disclosed separately
as “Local audit unconfirmed.” Successful cleanup/escalation is not incorrectly
labelled failed merely because that audit log failed. Even `/swarn` discloses
this partial result instead of silently hiding the audit gap. Durable intent
admission and the final outcome write remain required; no automatic warning,
escalation, cleanup or audit retry is added.

Two new regression cases failed before implementation and now verify exactly one
warning write, escalation, outcome record and notification, plus command-specific
cleanup and secret-safe diagnostics. Focused tests: **19 passed**. Exact selective
patch: **2,534 passed** in 32.67 seconds; full working tree: **2,616 passed** in
29.67 seconds, no skips. Both full suites used disposable real database storage;
new audit-failure cases use controlled doubles, not live Telegram or durable
outcome integration proof. Changed-file static and staged whitespace checks
passed. No deployment, merge or production changes.

## Warning authority after configuration reads and uncertain outcome writes

Warning variants now recheck Restrict members authority after the threshold
configuration read, plus Delete messages authority for `/dwarn`, before durable
intent admission. Revocation during that read prevents admission, warning write
and cleanup. These are live checks, not atomic permission guarantees across
Telegram and storage.

A failed final outcome write no longer obscures the already-confirmed warning,
retries the outcome, or leaks raw storage errors. The notification distinguishes
“Warning recorded” from “Outcome recording unconfirmed,” including for `/swarn`.
The outcome could already have committed when its acknowledgement was lost, so
no replacement outcome write is attempted. Cancellation propagates without a
completion claim.

Nine regression cases failed before implementation. Twelve added cases overall
cover configuration-read revocation and final-outcome failures, including three
real-storage scenarios using independent writer/reader connections: failure
before commit, lost acknowledgement after commit, and cancellation after commit.
Readers verify the saved warning and pending/applied outcome, and real intent
admission blocks command redelivery from repeating warning writes or cleanup.
Final exact selective patch: **2,546 passed** in 32.95 seconds; full working tree:
**2,628 passed** in 29.43 seconds, no skips, both with disposable real database
storage. Telegram and injected failure boundaries use controlled doubles, not
live Telegram. Changed-file static and staged whitespace checks passed. No
production changes, deployment or merge.

## Warning pre-action read deadlines

Warning variants now bound each pre-action authority, protected-target, bot
identity/membership and threshold-configuration read to five seconds. A stalled
read therefore does not indefinitely retain an unadmitted command. These are
per-read bounds, not a whole-command deadline; warning/outcome writes and
escalation semantics are unchanged.

Two new blocked-read tests failed before implementation. They now confirm timeout
cleanup and no intent admission, warning write or deletion when bot identity or
threshold reads stall. The existing cleanup deadline test was adjusted to allow
the new five-second reads while still accelerating only its ten-second deletion
bound. Focused run without storage: 30 passed, three storage-dependent skips.
Final exact selective patch: **2,548 passed** in 32.88 seconds; full working tree:
**2,630 passed** in 31.48 seconds, no skips, both with disposable real database
storage. Changed-file static and staged whitespace checks passed. New blocked
reads use controlled doubles; no live Telegram, deployment, merge or production
changes.

## Base moderation: confirmed actions versus result-card delivery

Ban, unban, kick and mute no longer attempt a fallback result card after an error
in local presentation or notification following Telegram acknowledgement. Their
confirmed action and audit remain intact; no membership/restriction operation is
replayed. Cancellation still propagates. Mute discards any unbound process-local
undo control if result-card delivery fails or is cancelled, rather than retaining
an unusable control until expiry. No claim of Telegram message delivery is made.

Twelve regression cases cover error/timeout and cancellation for all four
commands, with no resend, no action replay, retained audits, secret-safe logs and
mute-control cleanup. Initial targeted run reproduced eight resend failures and
a test-fixture issue (no action router); router-enabled coverage verifies actual
control cleanup. Focused suite: **35 passed**. Exact selective patch: **2,560
passed** in 28.48 seconds; full working tree: **2,642 passed** in 29.49 seconds,
no skips, both with disposable real database storage. New delivery cases use
controlled doubles, not live Telegram. Changed-file static and staged whitespace
checks passed. No deployment, merge or production changes.

## Mute undo callback: preserve confirmed unmute on notification failure

The one-use mute undo callback now tracks Telegram acknowledgement separately
from its callback answer and result card. Once unmute is acknowledged, failure
in either notification no longer triggers a misleading “Unmute unconfirmed”
alert or an additional callback answer. The control remains consumed and the
audit remains intact. Cancellation propagates; no unmute or notification retry
is added. Pre-acknowledgement errors retain existing uncertainty guidance.

Six new regression cases cover callback-answer versus result-card failures,
timeouts and cancellations, including no duplicate answer, no raw error logging,
retained audit and replay refusal without another restriction request. Four
failed before implementation. Focused tests: **31 passed**. Exact selective
patch: **2,566 passed** in 28.69 seconds; full working tree: **2,648 passed** in
26.65 seconds, no skips, both with disposable real database storage. New callback
cases use controlled doubles, not live Telegram. Changed-file static and staged
whitespace checks passed. No deployment, merge or production changes.
