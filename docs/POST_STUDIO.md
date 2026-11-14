# Post Studio: current behavior and limits

`/posttemplate` displays the full escaped administrator-authored template outside
clipped table cells. `/posttemplate reset` restores the default layout for this
group; literal `reset` is now reserved for that operation. Template changes use
the older ChatStore background-flushed document path: the UI does not claim an
awaited SQL confirmation. PostgreSQL-only runtime does not make every document
write individually durable. Dedicated confirmed template writes remain pending.

`/postpreview Title | body` and `/post Title | body` now share one normalised
HTML payload and explicit HTML parse mode. Replies can supply text or media
captions. Both operations require moderator/tenant-Owner permission. Preview
sends an explanatory notice, then the payload **in the same group**; it is not
private or a draft stored for later. It does not add a publication audit entry.
Publication sends the payload and records a metadata-only post audit entry; it
does not store the title as audit reason or log the title on success.

The broken publication import was fixed. Substitution is single-pass, so a
literal `{body}` supplied in the title is not replaced again. User values remain
HTML-escaped. Templates themselves are trusted administrator HTML; Telegram is
still the authority on whether formatting is supported/valid. This is not an
HTML validator or a channel scheduling/publishing system.

Limits: 600 template characters, 200 title characters, 3000 body characters and
4000 UTF-16 units of escaped rendered markup. The final conservative limit may
reject text that Telegram could accept after entity parsing. Nothing is silently
sliced mid-tag/entity: oversized compositions are rejected before sending.
A send error is ambiguous, not proof that nothing reached Telegram; inspect the
chat before retrying. Audit failure after acknowledged delivery explicitly says
not to republish. No automatic retry, background posting or live Telegram call
is part of this increment. The UI uses existing premium theme icons with plain
Unicode fallback through the standard rich sender.
