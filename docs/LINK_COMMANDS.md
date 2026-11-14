# Linkshare command safety and UI

`/links [page]` shows ten owner-scoped records per page (live, revoked, expired
and exhausted), newest first, with previous/next command hints. It does not
print tokens. Filenames remain visible to the current chat, so use private chat
for sensitive metadata. Existing share cards intentionally contain bearer links
and copy controls: anyone holding one may redeem it. Signing is not encryption.

`/share id [hours] [uses]` and `/genlink [hours] [uses]` accept at most two ASCII
whole numbers: hours 1–720, uses 0–1000 (0 means unlimited). Omission retains the
existing default expiry. Invalid values are rejected, not clamped, before link
creation or genlink download. `/revoke token` requires exactly one argument;
creation/control commands reject anonymous sender identities.

Genlink save failures no longer echo raw exception text or paths. Check `/files`
before retrying an ambiguous save. Share cards no longer double-escape filenames.
Revoke success uses a premium-themed panel and explains that previously delivered
or in-flight files are not erased. Existing callback, rich sender and Unicode
fallback paths are preserved.

Not upgraded here: confirmed per-write SQL persistence, cross-process atomic
redemption accounting, refund of failed deliveries, unique-grant token design,
archive durability, private-only responses or live end-to-end delivery tests.
