# FileStore command upgrade

`/files [page]` now exposes every entry in the authenticated user's bot-scoped
vault, ten per page, newest first. Commands in the previous/next hints are
revalidated on each request; concurrent saves/deletes can shift page membership.
Malformed/out-of-range pages do not mutate storage. Native rich tables retain
existing fallback behavior; the classic table can clip long names/IDs, so use
a rich-capable client for the full table or `/check id` for entry details.

`/storestats` now calls the tier helper correctly (fixing a runtime TypeError),
escapes filenames shown outside table cells and describes metadata accounting
rather than pretending to scan disk bytes. `/check id` distinguishes local bytes
from a recorded Telegram archive reference. A recorded reference is not a live
retrieval test and its underlying value is not displayed. Deletion uses a rich
panel and clarifies that previously delivered/archived copies are not remotely
erased. Save feedback no longer promises indefinite retrieval or private replies
when the command was issued in a group.

All vault commands now require a personal user identity. `/get`, `/check` and
`/del` require exactly one argument. `/batch [count]` explicitly accepts 1–50;
it no longer silently clamps zero/oversized values or ignores extra arguments.
Very large/non-ASCII numbers are refused before conversion/network access.
Save and batch-read failures return categories rather than raw exceptions that
could include paths, URLs or credentials; inspect `/files` before retrying an
unconfirmed save. Known friendly quota error mapping remains future work.

Persistence is unchanged: metadata uses the existing PostgreSQL document path
in normal runtime, and media bytes need local disk or Telegram archival. Older
document writes still background-flush; no per-command SQL durability upgrade,
automated archive guarantee, shared/public vault or live deployment change was
made by this UI/safety increment.
