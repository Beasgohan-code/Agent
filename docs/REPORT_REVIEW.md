# Reports & Appeals review upgrade

Moderator review now supports `/reports [page]`, `/reports closed [page]` and
`/reports show number`, in addition to `/reports close number`. Lists show ten
records per page, oldest first, across all retained entries in the current chat
(up to the existing 100-report/appeal cap). Details put the escaped full retained
reason outside the table to avoid cell clipping. Closed entries can be inspected
until normal retention evicts them; this is not a permanent moderation case DB.

Close accepts exactly one bounded positive ASCII report number. Unknown
subcommands, oversized numbers and malformed pages are refused without changing
reports. The ChatStore limit=0 slice bug is fixed. All report/appeal commands
require a personal sender identity. Review remains moderator/tenant-Owner gated,
but responses are visible to the current chat: command gating is not private
message delivery. Group scoping and retention are unchanged.

Appeal owner notifications now escape member-supplied HTML, specify HTML parse
mode and identify the originating chat so equal report numbers in different
chats can be distinguished. Notification errors log a category, not raw provider
text. Existing appeal text is capped at 400 characters; original message text is
not copied by report filing. A successful DM is not proof of owner review.

Premium-themed review and close panels use the existing rich/Unicode fallback.
ChatStore persistence is still background-flushed, report IDs are not newly
cross-process transactional and there is no immutable audit, anti-abuse rate
limit or automatic resolution. Live Telegram delivery has not been tested.
