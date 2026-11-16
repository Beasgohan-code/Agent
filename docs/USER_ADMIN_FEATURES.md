# Users/stats, tagging and admin reference checklist

Source: user-provided command lists. Inventory is code-level, not proof of live Telegram permissions.

Implemented profile phase: `/myinfo` ignores replied target and renders caller; `/userinfo @username|ID` or replied user; `/info [@username|ID]` accepts explicit target in preference to reply, otherwise reply/caller. One shared existing profile renderer, no duplicated profile implementations. Five-second bounded explicit lookup, validates positive IDs/usernames and returned personal identity, raw errors redacted/type-only #Errors logs. Public Telegram fields only; no invented full/private account data. Existing moderator-only warning/approval visibility unchanged. Identity lookup can fail for inaccessible accounts.

Four tests first failed before handlers/lookup existed, now pass: myinfo self vs reply, info/userinfo explicit username and HTML safety, raw upstream ValueError redaction. Related profile/utilities/bot tests 30 passed; full disposable-PG working tree **2,125 passed in 23.69s**, no skips. No live identity lookup performed.

Existing commands from other lists include /id, /info, /promote, /demote, /pin, /unpin, /adminlist, /purge, /cancel. They are not necessarily identical to every pasted signature: e.g. custom promotion title and temporary scheduling require review.

Not implemented in this phase: AFK/mention watcher, /userstats, /recentactivity; mass tagging /all, /tagabort, /allsettings, /tagstats, /tagall, /etagall, @all/@eall; adminbox, tpromote, rights panel, admincount, silent purge, chat-photo/title/description commands and fullpromote. No fake registry/help entries. /cancel retains current job cancellation behavior, not a tagging alias. /gu remains explicitly visual demo, not evidence a tagging backend exists.

Tagging needs bounded opt-in recipient registry, no assumed complete member access or activity/presence telemetry, admin/bot exclusion, concurrent-run limits, scoped controls and rate-limit/stop/resume state. Timed promotion needs durable scheduled demotion and reconciliation, not an in-memory six-hour timer. Fullpromote cannot grant rights Telegram has not delegated to this bot. Prior source hiding and main/worker navigation requirements unchanged.
