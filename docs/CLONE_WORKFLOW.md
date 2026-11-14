# Clone Studio workflow increment

`/clone` now resumes an active private setup rather than discarding a validated
bot token and restarting silently. Nonces and the original ten-minute deadline
remain unchanged. Resume shows the current stage and time left, and restores
feature-selection, assistant-consent or final-create buttons as appropriate.
There is no back button that could silently carry credentials into a different
plugin. To restart intentionally, `/cancel` first and then `/clone`.

Final review shows bot identity, authenticated sender Owner, selected plugin and
log/archive destinations in a native themed table. No token, assistant session,
API key or provider account data is shown. Credentials remain memory-only during
the draft and encrypted by the existing persistence path on creation. Telegram
credential-message deletion is best-effort, not proof of erasure.

Once manager startup begins, lazy draft expiry and another `/clone` cannot
scrub or replace the draft underneath startup. `/cancel` directs the user to
`/mybots` instead. Existing startup failure/completion cleanup still clears the
draft. This is not a new startup timeout or crash-recovery mechanism: hanging
startup, durable rollback ambiguity and leftover-resource recovery need further
work. Pre-start expiry still discards abandoned drafts. Restarting the process
loses drafts, not confirmed clone records.

Create retains identity/channel/eligibility/capacity revalidation. `getMe` proves
bot identity, not human BotFather ownership. This increment does not enable
plugins in production, inherit parent assistant credentials, deploy clones or
prove live streaming. No PR merge is authorized by “continue”.
