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

## Explicit unmute command: actor validation, bounds and notifications

`/unmute` now rejects bot and out-of-range actor identities before authority
reads. Protected-target and final authority reads have five-second bounds.
Generic provider failures are handled by the existing local moderation responder
with type-only diagnostics and safe uncertainty guidance. Once Telegram confirms
unmute, failure delivering its result card is contained and does not generate a
misleading API-failure reply, replay a restriction or undo its audit. Cancellation
continues to propagate.

Nine regression cases cover delivery error/timeout/API-error/cancellation,
invalid actors, redacted generic provider failure and blocked pre-action reads.
Six initial cases failed before implementation. Focused tests: **72 passed**
before adding the two blocked-read cases. Final exact selective patch: **2,575
passed** in 28.73 seconds; full working tree: **2,657 passed** in 25.97 seconds,
no skips, both with disposable real database storage. New provider and deadline
cases use controlled doubles, not live Telegram. Changed-file static and staged
whitespace checks passed. No deployment, merge or production changes.

## Purge validation, bounded batch deletion and honest receipts

`/purge` now validates a personal group administrator identity, positive ASCII
count (default 10, retained 100-ID cap), command message ID and argument count
before deletion. Invalid counts no longer fall back to deleting ten messages.
Live caller Delete messages permission is checked twice around bot-rights reads;
all permission reads are bounded to five seconds. One batch request for the
preceding IDs replaces up to 100 sequential requests and has a ten-second bound.
This is fewer client calls, not a live latency or server-performance claim.

The installed client's implementation was inspected: `delete_messages` returns
`r.pts_count`. A positive integer acknowledgement is not treated as an exact
removal count; the native rich receipt and audit explicitly state that the exact
count is unknown. Missing/false/zero acknowledgements are unconfirmed and not
audited as success. Acknowledged receipt failure never triggers a second deletion
or fallback result message. Cancellation propagates, secondary audit failures are
disclosed, and existing receipt cleanup timing remains unchanged.

Seventeen new regression cases cover invalid counts, missing acknowledgements,
identity rejection, final permission loss, request timeout, receipt failure and
cancellation. Nine failed before implementation. Existing range tests now assert
one batch and the honest receipt instead of a fictional exact removal count.
Final exact selective patch: **2,592 passed** in 30.04 seconds; full working tree:
**2,674 passed** in 26.18 seconds, no skips, both with disposable real database
storage. New deletion tests use controlled doubles, not live Telegram. Changed-
file static and staged whitespace checks passed. No deployment, merge or
production changes.

## Silent purge cleanup authority and notification separation

`/spurge` now validates the actor's signed-64-bit personal identity and rechecks
caller and bot Delete messages authority after the range acknowledgement/audit
and before deleting the command. Lost rights retain the command and disclose
that cleanup was not requested. Failures during those reads are distinguished
from uncertain command deletion requests. These live checks do not provide an
atomic permission guarantee across Telegram calls.

Notification failures are contained with type-only diagnostics rather than
entering another responder. In particular, failed delivery of the secondary
audit warning does not produce a misleading command-cleanup warning or second
reply; no range or command deletion is retried. Cancellation still propagates.

Six added regression cases cover caller/bot rights loss, oversized actor, and
audit-notice error/timeout/cancellation. Four initial cases failed before
implementation. Focused tests: **23 passed**. Exact selective patch: **2,598
passed** in 28.73 seconds; full working tree: **2,680 passed** in 29.83 seconds,
no skips, both with disposable real database storage. New Telegram/notification
cases use controlled doubles, not live Telegram. Changed-file static and staged
whitespace checks passed. No deployment, merge or production changes.

## Warning removals: durable replay admission and committed delivery

Member warning-removal commands `/rmwarn`, `/unwarn`, `/resetwarn` and the group
alias `/resetwarns` now use the existing tenant/group/message-scoped durable
intent admission before clearing warnings. Concurrent or redelivered copies of
one command cannot clear another warning or remove warnings added after the
original clear. This reuses the existing intent table; no schema migration or
new store is introduced. Normal service database mode has durable admission;
legacy standalone test compatibility does not acquire new replay guarantees.

The outcome is recorded once after the clear. Outcome-write uncertainty is
reported without retrying that write or the clear. Committed result-card failure
is logged without a fallback resend. Group-wide `/resetallwarns` retains its
existing atomic reset admission and also benefits from committed-delivery
separation. No Telegram ban or mute is changed by warning removal. Unfinished
admissions are not automatically retried or rolled back.

Initial regressions reproduced duplicate clearing across two independent real
storage connections and a duplicate notification. Five new cases overall cover
committed-card failure and concurrent/replayed delivery of all four member-clear
commands. Each real-storage case adds a new warning after the original clear and
verifies redelivery preserves it. Exact selective patch: **2,603 passed** in
32.20 seconds; full working tree: **2,685 passed** in 27.60 seconds, no skips,
both with disposable real database storage. Telegram calls use controlled
doubles, not live verification. Changed-file static and staged whitespace checks
passed. No deployment, merge or production changes.

## Help UI: direct command discovery and contextual return navigation

Controller Help categories now expose up to eight direct command-detail buttons
in two-column rows, alongside existing pagination and menu navigation. Search
matches open exact command details instead of requiring another category search.
Detail screens return to the command's current page computed from the live
registered catalogue, not a fixed first page. Finite read-only callback routes
never dispatch command actions; worker navigation remains separate and rejects
controller category/detail routes through the existing worker guard.

Detail tables distinguish registration from activation/permission checks and no
longer guess that an unregistered plugin was switched off. Unknown registries are
labelled not checked. Viewing Help does not execute a command or grant access.
Description/section cells are escaped once, preserving readable ampersands and
safe markup. Native rich tables, themed buttons, controller contact links and
worker branding remain in place. The existing reproducible offline UI preview
now includes a category page and reflects the updated navigation; it is not a
Telegram screenshot or a live delivery claim.

Six added regressions cover direct detail routes, live-page return, unavailable
wording, search navigation, all category/page callback routes and one-pass HTML
escaping. Four initial tests failed before implementation; older expectations
were updated for intentional navigation changes. First full runs identified the
outdated generated preview; it was regenerated and both suites rerun. Final
exact selective patch: **2,609 passed** in 27.42 seconds; full working tree:
**2,691 passed** in 28.70 seconds, no skips, both with disposable real database
storage. Static/whitespace checks passed. Unrelated music catalogue changes were
excluded from staging. No live Telegram, deployment, merge or production changes.

## Clone command Help: preparation and reviewed usage

Selected, registered clone command-detail screens now put reviewed “How to use”
and “Before sending” guidance before their existing declared requirements. Main
encoding, compression, posting, transfer, AI, rename, music and group-settings
entry points have guidance checked against the existing handlers. FileStore
`/genlink` explicitly describes its Owner/private guided ingestion, separately
from Linkshare's media-reply link creation. Renamer onboarding now correctly
explains application of the current chat filename template, not arbitrary filename
arguments. Unknown commands retain their existing description/requirement detail;
this is not a claim that every command has a complete usage guide.

All details label registration separately from activation/readiness/access.
Existing selection/live-registry checks, contextual back navigation, read-only
copy controls, native tables and clone branding boundaries remain unchanged.
No command execution, access grant, provider call or credential lookup is added.
The offline preview now includes isolated Encoder and FileStore detail fixtures;
it is not a Telegram screenshot or live readiness verification.

Ten new cases cover eight entry-point guidance variants, FileStore versus
Linkshare behavior, and selection/stale-registry boundaries. Nine failed before
implementation. Focused worker UI suites: **45 passed**. Exact selective patch:
**2,619 passed** in 31.50 seconds; full working tree: **2,701 passed** in 28.22
seconds, no skips, both with disposable real database storage. Static and staged
whitespace checks passed. No live Telegram, deployment, merge or production changes.

## Feature-oriented Help: Blacklist, Welcome and Federations

At the user's request, controller Help now separates Blacklist, Welcome & goodbye
and Federations from broad Moderation/Group management lists. Each feature has
an overview, actual command syntax, behavior/permission notes and practical
examples. Existing native tables, themed two-column command buttons, pagination,
contextual detail navigation and live-registration filtering remain. Commands
have one category home. `/help groups`, `/help federation` and `/help greetings`
provide natural entry points. Copyable ASCII commands are retained rather than
nonfunctional mathematical-alphabet slash commands.

The Blacklist page documents native `/blocklist` commands and parenthesized
batches, separate message deletion, actual modes and approved/staff exemptions.
It does not invent the sample's `/addblacklist` or sticker-specific commands.
Welcome documents real placeholders and membership-update limits. Federation
Help explicitly states that ban synchronization is unavailable. Feature examples
are filtered by registration and do not execute settings changes. Worker-owned
navigation and branding stay separate; these feature pages are controller Help.

Five new tests cover module routes, real syntax, behavior limits, filtered
examples, unique category ownership and conservative message lengths. Three
initial cases failed before implementation. A full-run navigation test was
updated to measure actionable command routes instead of assuming command-only
code spans; feature pages now contain syntax and examples too. Final exact
selective patch: **2,624 passed** in 26.93 seconds; full working tree: **2,706
passed** in 27.49 seconds, no skips, both with disposable real database storage.
Offline preview includes the three feature pages. Static/whitespace checks passed.
Unrelated music catalogue changes remain unstaged. No live Telegram, deployment,
production changes or PR merge; the user explicitly corrected the merge request.

## Focused group Help: warnings, locks, anti-flood, filters and topics

Five additional feature categories replace their entries in broad group lists:
Warnings, Locks, Anti-flood, Filters and Topics. Each has a purpose, handler-
reviewed syntax, behavior limits and registration-filtered examples. Warning
history is distinguished from restrictions; locks do not advertise custom
punishments; flood counters are explicitly process-local; filter replies are
plain text; topic management explains forum/Manage topics requirements and the
absence of topic deletion. Existing expiry/confirmation and routing limits are
retained. No new commands or enforcement behaviors are introduced by Help.

Direct command detail pages for feature guides now include their syntax and
module safety notes when registered, instead of only a brief menu description.
The Home protection shortcut follows its actual warning entry point. Category
ownership remains unique; native rich tables, copyable commands, pagination,
contextual navigation and controller/worker separation remain unchanged.

Four added regressions cover all five module examples, unavailable-example
filtering, direct feature detail syntax and the Home warning route. Two initial
cases failed before implementation. Existing exhaustive tests also validate
unique feature ownership, message-size limits and callbacks for every page.
An intermediate category edit dropped an icon tuple field; targeted tests caught
it before full validation and it was repaired. Final exact selective patch:
**2,628 passed** in 30.45 seconds; full working tree: **2,710 passed** in 28.16
seconds, no skips, both with disposable real database storage. Offline preview
includes a warning guide. Static/whitespace checks passed; unrelated music
catalogue changes remain unstaged. No live Telegram, deployment, production
changes or PR merge.

## Help feature separation: administrator tools, mentions and approvals

Three further feature guides move commands out of broad group lists while
retaining one category home per command and contextual detail links.
Administrator tools distinguishes limited promotion from owner-confirmed full
delegation, temporary promotion recovery requirements, title limits and live
permission snapshots. Mentions documents clickable first names versus emoji
labels, optional custom text, no enrollment, 20/message with five-second pacing,
the 2000-returned-entry cap and incomplete-roster/in-flight-stop limitations.
Approvals explains Manage chat requirements, personal targeting and automatic
anti-spam exemptions without claiming Telegram admin access or exemption from
manual moderation. Examples remain filtered to registered commands.

Three regressions failed before implementation and now cover all three feature
guides, explicit mention limits, and direct approval detail safety notes.
Existing exhaustive tests continue to check unique category ownership, message
limits, read-only callbacks and live-filtered navigation. Focused suites: **68
passed** before the last copy/preview update. Final exact selective patch:
**2,631 passed** in 31.85 seconds; full working tree: **2,713 passed** in 32.12
seconds, no skips, both with disposable real database storage. Offline preview
includes Mentions and Approvals. Static and staged whitespace checks passed;
unrelated music catalogue changes remain unstaged. No live Telegram, deployment,
production changes or PR merge.

## Mobile Help polish: bounded category overview and contextual return

As feature guides expanded, the controller overview became a long keyboard.
It now shows at most eight visible categories per page, in two-column button
rows with matching native-table rows, total category count and page number.
Previous/Next category controls use finite read-only screen routes. Each screen
rebuilds the filtered category list from current registration, so stale page
links clamp safely when the catalogue shrinks. Existing direct section/command
links and legacy All sections controls remain valid.

Later feature sections provide a contextual Back to categories control for their
current live overview page, reducing unnecessary taps through earlier pages.
Worker Help still uses its separate overview and controller-only page routes
remain blocked by the existing worker callback guard. No command execution,
authorization changes, live availability claims or provider calls are added.

Three regressions failed before implementation. They now cover every category
page's table/button agreement and callback bounds, stale-page clamping and
contextual return. Focused UI suites: **71 passed**. Final exact selective patch:
**2,634 passed** in 30.28 seconds; full working tree: **2,716 passed** in 28.38
seconds, no skips, both with disposable real database storage. The offline
preview was regenerated; it is not a Telegram screenshot. Static and staged
whitespace checks passed; unrelated music catalogue work remains unstaged.
No live Telegram, deployment, production changes or PR merge.

## Corrected Help hierarchy: modules first, group features inside

Following the user's clarification, top-level controller Help now lists broad
modules rather than every group subfeature. Group management aggregates the
registered commands of its child features for visibility/counting, so the hub
still appears when only Blacklist, Welcome or Federations is registered. Opening
it shows only live group-feature buttons, including a separate Group settings
command list. Each child guide returns to Group management. Existing direct
command Help, section links and paginated raw command lists remain available.

The Music entry now opens read-only task buttons for registered playback, queue,
playlist, repeat, volume and player-health commands, plus an all-commands link.
Opening a task displays command Help; it never starts/stops playback or mutates
the queue. Both module hubs have explicit all-modules/menu return paths. Live
registration is not activation/authorization evidence. Worker-owned navigation
and its controller-route guard remain unchanged.

Two new regressions failed before implementation and now cover root-versus-child
visibility and Music's filtered read-only task buttons. Existing tests were
updated to the user-corrected hierarchy rather than flat categories. Focused UI
suites: **73 passed**. Final exact selective patch: **2,636 passed** in 32.74
seconds; full working tree: **2,718 passed** in 29.98 seconds, no skips, both
with disposable real database storage. Offline preview includes Group management
and Music hubs. Static/whitespace checks passed; unrelated music catalogue work
remains unstaged. No live Telegram, deployment, production changes or PR merge.

### Verification diagnostic redaction

Removed raw exception bodies and tracebacks from verification join-watcher errors
and post-verification prompt-edit failures. Diagnostics retain operation, exception
type and #Errors without provider bodies. Membership checks, permissions, pending
sessions and timeout behavior are unchanged; an edit failure does not undo an
acknowledged verification. Two regressions failed before the fix and now prove
both paths omit the injected secret and traceback while preserving outcomes.

Focused verification: **27 passed**. Exact selective patch: **2,638 passed** in
34.83 seconds; full working tree: **2,720 passed** in 32.62 seconds. Both full runs
used disposable real storage, with no skips. Changed-file static checks and
whitespace checks passed. New Telegram failures are mocked, not live proof.
Wider diagnostic hardening remains incremental. No production calls, deployment
or PR merge. Unrelated working-tree work remains untouched.

The user cancelled appearance customization. All uncommitted typography, owner
appearance controls, custom taglines and associated tests/preview/docs were removed
before this phase; none was committed or pushed. Existing module-first Help and
plain native cards remain intact.

### New-group and lockdown diagnostic redaction

New-group event-sink failures and lockdown permission-change failures now log only
operation/type and #Errors, without provider exception bodies or tracebacks.
Lockdown state transitions, authority checks, saved recovery permissions and
failure replies remain unchanged. Three new cases failed before the fix; they
cover event-sink failures and both locking/unlocking failures, preserving recovery
state without reporting success.

Focused suites: **83 passed**. Exact selective patch: **2,641 passed** in 33.20
seconds; full working tree: **2,723 passed** in 28.72 seconds. Both full suites
used disposable real storage, no skips. Changed-file static and whitespace checks
passed. Telegram errors are mocked; no live provider calls, deployment, production
changes or PR merge. Unrelated music/premium/language work remains unstaged.

### Transfer-progress and player diagnostic redaction

Removed raw exception bodies/tracebacks from transfer progress edits, player-card
redraws and empty-queue leave failures (command and button). Type/operation-only
#Errors diagnostics retain existing best-effort progress/redraw behavior and
unconfirmed-leave replies. This does not change playback, queue mutation, transfer
admission, native media restrictions, permissions or retries. Wider music and
transfer changes in the working tree are not part of this patch.

New regression coverage injects secret-bearing provider errors in all four paths:
transfer still uploads and cleans its temporary files after a failed progress
edit; acknowledged pause survives card-redraw failure; command/button leave
failures remain unconfirmed. Initial two regression tests failed before fixes.
Focused suites: **106 passed**. Exact selective patch: **2,643 passed** in 35.17
seconds; full working tree: **2,725 passed** in 30.94 seconds. Full suites used
disposable real storage, no skips. Changed-file static and whitespace checks
passed. New Telegram/native failures are mocked, not live transport/visual proof.
No production calls, deployment or PR merge. Appearance remains removed.

### Transfer cleanup preserves the original outcome

Temporary-file unlink failures no longer replace a transfer's original failure or
cancellation, or turn a completed upload into a failed job. File and empty-directory
cleanup are attempted independently; an already missing directory is acceptable.
Only the transfer's owned path and its directory are touched, with no recursive
removal. Cleanup failures append a stable “Temporary cleanup unconfirmed” job
detail and trigger a bounded best-effort notice without leaking paths/provider
errors. Notice failure does not replace the original outcome. No automatic
resend, cleanup retry service or durable cleanup recovery is claimed; a failed
cleanup may leave temporary data for operator attention.

Six cases failed before implementation. Final twelve cases cover unlink/rmdir
failure across successful delivery, failure and cancellation, with delivered or
failed cleanup notices; original exception identity and unrelated files are
preserved. Focused transfer suites: **36 passed**. Exact selective patch:
**2,655 passed** in 36.05 seconds; full working tree: **2,737 passed** in 31.81
seconds, both with disposable real storage and no skips. Static and whitespace
checks passed. Filesystem/Telegram failures are injected fixtures, not live
provider proof. Unrelated work remains unstaged; no production calls, deployment
or PR merge. Appearance remains removed.

### Leech upload acknowledgement and ambiguous delivery

Leech now requires a positive, non-boolean integer message ID from Telegram's
upload result before marking delivery acknowledged. Missing/false/malformed
results fail the job instead of reporting success. Job details distinguish
unconfirmed upload from acknowledged delivery. Upload errors and cancellation
keep delivery unconfirmed, advise checking the chat before retrying, and never
automatically resend. Temporary cleanup and its independent warning remain intact.
An acknowledgement is not proof the recipient downloaded/read the file; ambiguous
uploads may already have posted. Mirror storage semantics are unchanged.

Six acknowledgement cases failed before the fix. Nine new cases cover malformed
and valid results, provider errors and upload cancellation, with one upload
attempt, cleanup and secret-safe user feedback. Older successful-upload fixtures
now return explicit message acknowledgements instead of empty mocks. Focused
transfer suites: **45 passed**. Exact selective patch: **2,664 passed** in 29.55
seconds; full working tree: **2,746 passed** in 29.05 seconds. Both full runs used
disposable real storage with no skips. Static and whitespace checks passed.
Telegram uploads remain mocked; no live provider calls, production changes,
deployment or PR merge. Unrelated work preserved; appearance remains removed.

### Markdown reconciliation and bounded job admission

Scanned all 49 tracked Markdown files for pending/completion markers and local
inline file links, preserving historical/reference provenance. Recorded scope
and unresolved areas in CODEBASE_AUDIT; corrected current Music command counts,
seek/voicehealth status and resolver-versus-native-admission wording in MUSIC_PARITY.
Zero missing local file-link targets; external links/anchors were not validated.

JobQueue now defaults to 100 live admitted tasks per instance (`max_active` accepts
positive integers). Running work, semaphore waiters and tasks still doing cancellation
cleanup all consume capacity. Rejection happens before task/history/ID allocation;
completed tasks release capacity even before their done callback runs. Existing
concurrency/history pruning, shutdown and outcome behavior remain unchanged.
Per-owner/group fairness, cross-instance budgeting, durable job recovery and
bounds on other in-memory services remain open. Callers must handle capacity
rejection; no per-command progress-card redesign is claimed.

Two admission scenarios failed before implementation; final regressions also
validate invalid budgets. Exact selective patch: **2,667 passed** in 32.59 seconds;
full working tree: **2,749 passed** in 29.04 seconds, no skips, disposable real
storage enabled. Static/whitespace checks passed. No live Telegram/provider or
production calls, deployment or PR merge. Unrelated dirty work remains unstaged.

### Transfer admission before allowance/progress

Leech/Mirror now catch typed local queue-admission refusals before consuming
transfer allowance or emitting progress. Queue preflight, synchronous allowance
take and submit have no intervening await; submit still independently enforces
the limit. Actual progress starts inside the admitted runner. Full/shutting-down
queues give a clear no-job-admitted response, without download/upload, fake job
success, allowance consumption or automatic retry. URL validation still precedes
admission. This is same-event-loop safety, not a durable quota reservation or
cross-instance fairness policy; other modules need their own admission UX review.

Four refusal cases failed before the fix; final cases cover Leech/Mirror with
full/closed queues plus concurrent requests admitting and charging only one job.
Focused transfer/job/source suites before the final concurrency case: **66 passed**.
Exact selective patch: **2,672 passed** in 32.13 seconds; full working tree:
**2,754 passed** in 30.29 seconds. Both full runs used disposable real storage,
no skips. Static/whitespace checks passed. New transfer effects are mocked; no
live provider calls, production changes, deployment or PR merge. Appearance stays
removed and unrelated work remains unstaged.

### Encoder capacity refusals

Encoder conversion commands (`encode`, `compress`, `sample`, `toaudio`, `screens`)
now check local job capacity before download/progress and catch typed admission
refusal at submit if another request fills the queue while download is awaited.
Refusal gives an explicit no-job-admitted/no-conversion-started reply. Downloaded
source paths are not blindly removed: their ownership is not guaranteed. This
phase does not introduce source cleanup ownership or a download reservation;
concurrent downloads can still occur while capacity is available. Info-only
`mediainfo` remains outside the conversion queue, and invalid-option/missing-media
usage paths are preserved. These handlers do not charge transfer allowance.

Fifteen regressions failed before the fix, covering all five queued commands
against full/closed queues and a queue filled during download; no conversion is
run and source bytes survive refusal. Focused Encoder suites **140 passed**.
Exact selective patch **2,687 passed** in 34.44 seconds; full working tree
**2,769 passed** in 30.30 seconds. Full runs used disposable real storage, no
skips. Static/whitespace checks passed. New Telegram downloads are mocked, not
live provider proof. No production calls, deployment or PR merge; appearance
remains removed and unrelated working-tree changes remain unstaged.

### Group mention worker admission

Group mention commands now check the shared queue before roster retrieval and
again before durable run creation. Launch/Resume recheck capacity immediately
before submission. Full/closed queues return an explicit no-mention-job-admitted
response instead of a generic uncertain failure. If capacity fills during the
awaited durable start, the saved paused snapshot/cursor is left unchanged; no
worker or batch is started and `/tagabort` remains available under saturation.
This is local queue admission, not a durable capacity reservation or automatic
restart mechanism. Existing personal-admin checks, plain first-name/emoji labels,
optional custom message, 20/message and 5-second pacing are unchanged.

Two early-refusal regressions failed before the fix. Final focused mention suite:
**17 passed**, including a disposable real-storage scenario for post-save capacity
loss, refused Resume, unchanged paused cursor, no send and successful abort.
Exact selective patch: **2,690 passed** in 35.57 seconds; full working tree:
**2,772 passed** in 39.70 seconds. Full suites used disposable real storage,
no skips. Static/whitespace checks passed. Telegram roster/sends are mocked; no
live Telegram/provider calls, production changes, deployment or PR merge.
Appearance remains removed; unrelated working-tree changes remain unstaged.

### Cancellation fence after queued eligibility checks

JobQueue now rechecks logical cancellation and shutdown after the awaited group
eligibility read and immediately before invoking the runner. A provider wrapper
which absorbs CancelledError can no longer cause cancelled work to start after
that read returns. Cancelled state/finished timestamp remain intact; started_at
and result stay unset. This is a local pre-run fence, not a transactional link
between permission reads and later Telegram effects or forced interruption of
already-running work.

Initial cancellation regression failed because the runner was awaited once.
Final cancellation and shutdown cases both assert no runner invocation after a
cancellation-suppressing eligibility check. Focused job-history suite: **7 passed**.
Exact selective patch: **2,692 passed** in 38.33 seconds; full working tree:
**2,774 passed** in 30.56 seconds, disposable real storage enabled, no skips.
Static/whitespace checks passed. No live provider/production calls, deployment
or PR merge; appearance remains removed and unrelated changes remain unstaged.

### Retain and await cancelled-job cleanup

Job-history trimming now requires actual task completion, not only a terminal
logical state, before evicting a record. The history target may temporarily be
exceeded while bounded live tasks finish cleanup. Completion callbacks still
prune finished history. Group cancellation includes matching already-cancelled
but unfinished tasks, waiting for their cleanup without injecting cancellation
a second time. Other group/module tasks remain untouched. This does not add
cleanup deadlines, durable jobs or permission to delete unrelated resources.

Two regressions failed before implementation (early history eviction and early
group-cancellation return). Final third regression verifies group/module isolation.
Exact selective patch: **2,695 passed** in 37.76 seconds; full working tree:
**2,777 passed** in 33.07 seconds. Both suites used disposable real storage, no
skips. Changed-file static/whitespace checks passed. New cleanup boundaries use
local task fixtures; no live Telegram/provider or production calls, deployment
or PR merge. Appearance remains removed; unrelated changes remain unstaged.

### Shutdown and cancellation outcome preservation

JobQueue shutdown no longer injects a second cancellation into tasks already
handling cancellation; it awaits them, including concurrent shutdown callers.
Tasks not yet cancelling are still cancelled. An ordinary runner error raised
after logical cancellation now preserves the cancelled state, original finish
timestamp and empty result/error fields, while adding a stable generic detail
and type-only #Errors diagnostic. Ordinary non-cancelled runner failures retain
the existing failed/runner_failed behavior. Cancellation cleanup may still fail;
this is not a guarantee of resource removal or durable cleanup recovery. Outer
shutdown deadlines/forced process termination remain separate limits.

Three regressions failed before implementation: single/concurrent shutdown
interrupting cleanup and a cleanup error replacing requested cancellation.
Focused job/platform suites: **35 passed, one storage-dependent skip** without a
storage URL. Final full exact selective patch: **2,698 passed** in 35.22 seconds;
full working tree: **2,780 passed** in 32.02 seconds, both with disposable real
storage and no skips. Static/whitespace checks passed. No live provider calls,
production changes, deployment or PR merge. Appearance stays removed and
unrelated working-tree work remains unstaged.

### Honest cancellation command status

`/cancel` now acknowledges a cancellation request rather than claiming the job
has already stopped. Repeated selected/all cancellation while owned cleanup is
still running reports that cancellation was already requested, without injecting
another cancellation or claiming completion. Private `/jobs` displays `cancelling`
for logically cancelled jobs with unfinished tasks and `cancelled` after the task
finishes. Existing job ownership, private job-list scope, clone-draft cancellation
precedence and finished/unknown-job behavior remain intact. No cleanup-success or
remote-effect rollback guarantee is implied.

New end-to-end regression failed on old success wording, then verified initial
request, repeated selected/all commands, live private status, and finished status
using a blocked cleanup fixture. Existing assertions updated to truthful request
semantics. Core suite: **20 passed**. Exact selective patch: **2,699 passed** in
30.54 seconds; full working tree: **2,781 passed** in 30.93 seconds, both with
disposable real storage and no skips. Static/whitespace checks passed. No live
Telegram/provider or production calls, deployment or PR merge. Appearance stays
removed; unrelated working-tree changes remain unstaged.

### Personal job controls and resilient progress display

`/cancel` now rejects missing/malformed, boolean, out-of-range and bot identities,
and channel/anonymous sender context, before queue access. `/jobs` applies the
same personal-account boundary in addition to its existing matching private chat
and ownership filters. No new Owner bypass or cross-user history access.

Job-list progress now accepts only finite built-in integer/float telemetry,
clamping valid ratios to 0–100%. Unknown/non-finite/boolean/object values display
`unavailable` without conversion, repr, secret echo or fabricated measured zero.
This hardens the private display, not every producer or serialized job endpoint.

Two initial regressions failed on identity admission and NaN display conversion.
Final three tests cover personal-account rejection before queue/history access,
unknown/private/non-finite progress and valid bounded values. Focused Core/job
suites before final private-list identity case: **35 passed**. Exact selective
patch: **2,702 passed** in 29.82 seconds; full working tree: **2,784 passed** in
28.01 seconds, both with disposable real storage and no skips. Static/whitespace
checks passed. No live provider/production calls, deployment or PR merge.
Appearance stays removed; unrelated working-tree changes remain unstaged.

### Explicit queued group-job approval

Queued group jobs now start only when their eligibility callback returns exactly
True. Truthy numbers, text and arbitrary objects are not authority; false, missing
and malformed results leave the job cancelled before runner invocation. Unknown
objects are neither truth-tested nor rendered. Existing exception denial,
cancellation fence, queue-capacity release and non-group behavior are unchanged.
This is the queued-job boundary, not a claim every dispatcher/provider contract
has been hardened or that eligibility reads and remote actions are atomic.

Four of nine new cases failed before the fix, including an unsafe boolean
coercion that left a job without a proper terminal outcome. Final tests cover
explicit approval/denial, malformed results, no object coercion/secret echo and
subsequent queue usability. Focused job/platform suites: **44 passed, one storage
skip** without a URL. Full exact selective patch: **2,711 passed** in 32.34 seconds;
full working tree: **2,793 passed** in 29.66 seconds. Both full runs used disposable
real storage, no skips. Static/whitespace checks passed. No live provider calls,
production changes, deployment or PR merge; unrelated work stays unstaged and
appearance remains removed.

### Explicit optional-plugin execution approval

Optional plugin command/callback/silent-listener entry points now normalize group
eligibility to an exact boolean approval. Runtime authorization likewise requires
explicit not-disabled=False and enabled=True flag values; malformed/unknown flags
fail closed for private and group optional invocations. The same normalization
feeds queued-job eligibility and reconciliation, so a truthy string is not cached
as approval and malformed approval triggers existing scoped cleanup. Protected
moderation/core paths remain exempt from optional-slot/approval checks. Private
optional tools still do not query group slots. No new permission, global Owner
bypass or cross-group cleanup behavior is introduced.

Eighteen of 21 new cases failed before implementation. Cases cover all three
entry surfaces, malformed reconciliation approval, private/group runtime flags,
protected-plugin continuity and execution-context cleanup. Focused suites:
**62 passed, two storage skips** without a storage URL. Full exact selective
patch: **2,732 passed** in 31.69 seconds; full working tree: **2,814 passed** in
28.27 seconds, disposable real storage enabled, no skips. Static/whitespace checks
passed. No live provider/production calls, deployment or PR merge. Appearance
remains removed; unrelated working-tree changes remain unstaged.

### Plugin child-cleanup and reconciliation diagnostics

Overlapping plugin cleanup requests now await an already-cancelling owned child
without cancelling it a second time. The shared dispatcher task stays intact.
Cleanup-hook failure retains the seen group/plugin scope for reconciliation retry,
while cleanup and watcher failures now emit #Errors operation/type diagnostics
without raw exception bodies or tracebacks. Watch retry behavior and optional
plugin approval/slot checks are unchanged.

This is not a single-flight protocol for resource hooks: concurrent hook calls,
durable retry/dead-letter recovery and cleanup time budgets still need separate
work. Hooks must remain idempotent. Forced cancellation/host termination can still
interrupt cleanup; no guaranteed remote-resource deletion claim is made.

Three regressions failed before implementation, then cover child-cleanup
completion, failure/success retry retention and watcher recovery with injected
private provider values. Focused suites: **65 passed, two storage skips** without
a storage URL. Full exact selective patch: **2,735 passed** in 40.07 seconds;
full working tree: **2,817 passed** in 40.91 seconds, both with disposable real
storage and no skips. Static/whitespace checks passed. No live provider calls,
production changes, deployment or PR merge. Appearance remains removed and
unrelated working-tree changes remain unstaged.

### Channel-invite Linkshare replacement: storage foundation

Reviewed the user-selected reference at revision recorded in REFERENCE_ADOPTION.
Added an isolated channel-share configuration table/API, manual-approval default,
per-channel opt-in automatic preference, explicit boolean validation, awaited
transactional field patches and tenant-serialized 20-channel admission quota.
No command wiring, invite generation, auto-approval listener, source copy or
legacy-link deletion is included. This phase is infrastructure, not usable
replacement parity; old commands remain until their replacements are verified.

Three tests failed before implementation. Disposable real-storage tests cover
concurrent edits, restart reads, tenant isolation and competing final quota slots;
validation/storage-unavailable refusals are also covered. Exact selective patch:
**2,738 passed** in 40.72 seconds; full working tree: **2,820 passed** in 33.80
seconds, no skips. Static/whitespace checks passed. No production schema/network
calls, deployment or PR merge; unrelated work preserved and appearance stays
removed. Telegram authority/invite/approval behavior remains the next phase.

### Native channel-invite Linkshare: first usable handler slice

Added verified Owner-private channel management through existing `/genlink` route,
using scoped durable settings. Owner identity and actor/bot channel invite rights
are checked; configuration writes and each invite creation recheck authority.
List/add/mode/disable and single-channel normal/request invite creation are usable
in code. See REFERENCE_ADOPTION for transition syntax and incomplete migration
boundaries. Both invites expire in 15 minutes, normal uses capped at one.

Two initial handler tests failed before implementation. Nine new cases cover
partial invite success, live rights, denied identities, disabled/unmanaged channels,
rights loss, false acknowledgements, provider failures, rejected URL hosts and
routing through the existing command owner. Exact selective patch: **2,747 passed**
in 31.40 seconds; full working tree: **2,829 passed** in 35.11 seconds, with
disposable real storage and no skips. Static/whitespace checks passed. Telegram
invite operations are mocked; no live invite creation/approval or production calls,
deployment or PR merge. Automatic approval worker, reference-style bot deep links,
shared settings/batch command routing and legacy command removal remain unfinished.
Appearance stays removed; unrelated work remains unstaged.
