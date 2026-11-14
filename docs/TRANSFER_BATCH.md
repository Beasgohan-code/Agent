# Transfer command batch

> Command availability changed after the reference-pruning request. See
> [current removals and replacement](COMMAND_SURFACE_CHANGES.md); older command
> instructions below are historical where they conflict.

The six Leech commands now require personal user identity. `/leech` and `/mirror`
require exactly one URL; `/taskbackend` and `/leechstats` refuse unsupported
arguments; `/taskstatus` requires exactly one ID. `/tasklist [page]` validates
pages and browses ten retained owned jobs per page, newest first. It still reads
the shared job queue (not just transfer jobs), with explicit module labels.

New transfer labels and enqueue logs omit URLs, including path/query secrets.
Task lists omit arbitrary labels; task details withhold arbitrary job detail and
raw error strings, which could expose private paths, signed links or provider
messages from any shared module. This trades debugging detail for safer public
chat output. IDs/state/progress/module remain visible to the owner. Task status
is owner-scoped; responses can still be seen by everyone in the current chat.
Statistics show only the caller's active count, not global workload counts.
URL-refusal messages are generic, rather than reflecting arbitrary error text.

Existing public-address/DNS/download validation is unchanged. No URL admission
policy is bypassed and no provider extractor or backend integration is added.
This does not remove URLs from all other historical logs/JobQueue internals or
all core job commands. Jobs remain process-local and retained history is bounded
by existing queue policy. Atomic daily quotas, restart recovery, durable task
storage, exhaustive SSRF/redirect auditing and download cleanup are pending.
