# Searchable, bounded best-effort logs

Owner log cards retain established hashtags (#Errors, #NewUser, #NewGroup,
#Restart etc.), UTC timestamps, incident IDs/types/occurrence counts, and now
explicit INFO/WARNING/ERROR severity. Error/watchdog/stop event categories set
severity; this is event classification, not an inferred provider diagnosis.
Unknown event kinds become ASCII alphanumeric hashtags capped at48 characters;
raw HTML/newline/secondary-hashtag injection is not allowed. Epoch-zero timestamp
renders correctly. No custom emoji entitlement is required to search logs.

## Minimize before retaining or emitting

Shared sanitizer handles secret-bearing field keys recursively, including token,
password/secret/credentials/auth, API key/hash, session string/private key,
database URL and raw payload/message-text/content/prompt/caption fields.
Exceptions become their type only; arbitrary objects are not str/repr'd. Common
Telegram token, credential-bearing URL, bearer credential and named credential
assignment patterns are scrubbed even in otherwise permitted strings. It is
best-effort defense in depth, **not a guarantee that arbitrary unlabeled secrets
can be identified**. Call sites must still avoid collecting credentials, message
bodies and raw provider exceptions. Do not use logs as a credential vault.

EventLog sanitizes before its ring buffer, console output and listeners. It
returns independent deep copies and isolates listeners from stored nested data;
reserved timestamp/kind metadata cannot be replaced through event fields.
recent(0) returns no entries. LogBook sanitizes direct posts, no-destination
console fallback and queued publish arguments before retaining tasks. SQL log
destination settings, tenant scope and owner-DM fallback semantics unchanged.

Values capped256 characters, keys64, fields24, nesting3/list8. Truncation/omission
is labelled. HTML escaped after sanitization, complete fields admitted up to3800
serialized characters plus bounded omission note (under4000 total). HTML tags
are never chopped. These are operational cards, not complete audit exports.

Delivery stays bounded by the existing200 pending posts and10s send deadline.
No retry after ambiguous send. Delivery/listener errors log #Errors plus type,
never raw provider text or traceback. This does not route every Python warning
through Telegram, replace incident aggregation, or change other modules' direct
logging. Existing incident IDs link repeated handler failures without collecting
locals or exception text. No global suppression of events or cross-bot state.

Nine new regressions first seven failed before implementation: nested credential
and content redaction, unlabelled common credentials/escaping, safe hashtags and
epoch0, escaped-size bounds, ring/listener/console safety, failed-send redaction
and no retry, deep-copy/reserved fields, error severity/incident preservation.
Full working PostgreSQL suite before final API-key/queued-argument hardening:
2,217 passed in22.10s, no skips. No live Telegram delivery/production writes.

## Missing startup-post diagnosis

`/log` now separates recorded events from process-local Telegram posts sent/failed,
pending/dropped queue entries and last result/error type. `/log test` (existing
Owner gate) awaits one diagnostic post to the hydrated saved destination, reports
actual send success/failure and never retries. No destination change/fallback to
an unrelated channel is attempted. Counters are process-local, not durable
receipts or proof a human read a post. The most recent concurrent post can replace
last-result diagnostics. A startup event is emitted only after required DB/log
settings/lease/Telegram startup succeed; startup failing earlier cannot send a
Telegram startup log. Use sanitized hosting `Startup failed` phase and
`Log delivery failed ... error_type=...` lines to diagnose actual deployed failure.
