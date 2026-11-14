# Post Studio: current behavior and limits

> Command availability changed after the reference-pruning request. See
> [current removals and replacement](COMMAND_SURFACE_CHANGES.md); older command
> instructions below are historical where they conflict.

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

## Confirmed template persistence (supersedes template-write notes above)

Normal runtime now stores explicitly saved/reset layouts in
`agent_post_templates`, keyed by tenant and chat. `/posttemplate` awaits the SQL
upsert before confirmation. Display, preview and publication read the table on
each command; database read failures refuse to send rather than use a stale
cached layout. Existing PostgreSQL document templates are used only when no
dedicated row exists, preserving older settings until the first explicit save.
No local JSON import is performed. Reset writes the default layout explicitly,
so an old document value cannot reappear after restart.

Standalone db=None helpers retain their test compatibility behavior, clearly
labelled in responses. There is no configured-database fallback. Writes are
last-committed-wins, not compare-and-swap editor sessions; a transport timeout
can leave the commit outcome ambiguous, so inspect `/posttemplate` before
retrying. Other ChatStore settings and post audit writes are not migrated by
this change. Existing old document keys remain but cannot override a dedicated
row. No live production schema/deployment was modified from the sandbox.
