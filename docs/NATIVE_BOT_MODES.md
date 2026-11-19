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
