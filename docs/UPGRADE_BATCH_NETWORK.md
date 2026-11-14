# Upgrade batch: shared URL validation and Leech transfers

## Runtime changes

- Shared URL parsing reports malformed IPv6/ports and control characters as
  actionable LinkError errors instead of leaking ValueError into handlers.
- Preflight refuses empty/malformed DNS answers and non-global addresses,
  including shared-address space that is neither private nor globally routable.
- Leech uses a custom aiohttp resolver returning the exact validated DNS answers
  to its connector, preventing a second unchecked DNS resolution at connection.
- Leech follows at most five redirects explicitly, checking each target for
  private IP literals, embedded credentials and unsupported schemes.
- Downloads request identity encoding and reject unexpected content encodings,
  malformed/negative sizes, oversized headers, over-limit chunks and truncated
  payloads. The total transfer deadline is one hour, alongside connect/read
  deadlines. Incomplete/cancelled files are removed.
- Generated destination names explicitly exclude dot/dot-dot components.

## Command and data impact

No commands added, removed or renamed. `/leech` and `/mirror` share these
transfer protections; Music's URL parsing benefits from shared validation.
No PostgreSQL schema/data/key/clone changes. No upstream code copied, client
fork installed, plugin slot policy changed, deployment or merge performed.

## Verification

967 tests passed against disposable PostgreSQL. New offline tests cover malformed
URLs, mixed/empty DNS answers, connection resolver output, successful redirected
transfer/progress, private redirect rejection, redirect exhaustion, bad size and
encoding responses, HTTP errors, truncated output, stream limit and cancellation.
Compileall, pyflakes and git diff --check passed. External network/Telegram/voice
playback has not been exercised.

## Remaining boundaries

Music's native engine fetches direct URLs independently: this change does not
pin DNS or validate redirects inside that engine. That needs a separately
reviewed downloader/local-source lifecycle and bounded queue cleanup. The
seven-source integration and new UI work remain incomplete. No full parity or
all-plugin upgrade is claimed by this batch. Transfer errors outside LinkError
still use the existing job error path; per-job directories are managed by the
existing job lifecycle. Arbitrary upstream shell execution is not adopted.
