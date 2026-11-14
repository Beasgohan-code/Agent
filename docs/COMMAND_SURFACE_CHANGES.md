# Reference-aligned command removals

The user explicitly approved removing the 15 names marked unmatched in the
29-repository comparison. This is a command-surface change, not a data purge.

Removed registrations, handler implementations, Help entries and menu metadata:
`delcaption`, `enccancel`, `encinfo`, `encpreset`, `fsave`, `leechstats`,
`playlistinfo`, `postpreview`, `posttemplate`, `storequota`, `storestats`,
`taskbackend`, `tasklist`, `taskstatus`, `unsetlog`.

One verified replacement: `/mediainfo`, found at
`refs/Videl1/VidelBot/core/tools.py` in the `filters.command("mediainfo")`
registration. Agent keeps its own original implementation: reply-based FFmpeg
inspection, not a claim of complete reference behavior parity.

Existing commands retained where useful: `/batch 1` saves one replied file;
`/cancel` cancels owned running jobs; `/files`, `/get`, `/mirror`, `/setlog` and
`/log` remain. These are not exact aliases for every removed workflow. In
particular there is no longer a Telegram template editor/preview, playlist-info
command, explicit log-clear command, or dedicated transfer task-history screen.
Existing templates, captions, vault files, playlists, log settings and database
schemas are preserved. No migrations delete data. Read-through templates and
internal storage helpers remain where needed by publication/compatibility.

Removed obsolete command-contract tests and updated mixed-path tests/counts;
kept rendering, PostgreSQL isolation/restart, media conversion and service tests.
Added explicit regressions that retired names cannot reappear in manifests,
handlers, menu descriptions, Help or scope metadata. Older feature documents
are historical descriptions; this file supersedes removed-command instructions.
Telegram command-list publishing refreshes known scopes when the upgraded bot
starts; no live Telegram command list was changed from the sandbox.

This does not establish full behavior parity for the remaining 124 declarations.
The comparison includes literal candidates and weak source clues that still need
manual review. No shell/eval command, unsafe credential workflow or wholesale
unlicensed source was imported. PR merge and deployment are not authorized.
