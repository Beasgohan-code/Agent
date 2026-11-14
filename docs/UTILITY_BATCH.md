# Utility command batch

> Command availability changed after the reference-pruning request. See
> [current removals and replacement](COMMAND_SURFACE_CHANGES.md); older command
> instructions below are historical where they conflict.

- `/id`: themed identifiers panel, including explicit sender-chat identities.
  Anonymous/channel messages are not treated as proof of a human administrator.
- `/info`: themed member profile, honest unknown membership status and an explicit
  refusal to infer a hidden user from a replied sender-chat message. Warning
  counts/trust flags are now shown only to moderators/tenant Owner. That gate
  does not make the response private: it remains visible in the current chat.
- `/time [Area/City]`: native world-clock table using IANA timezone rules, UTC
  reference and current offset. Default UTC; no preference/location is stored.
  Named-zone data comes from the host timezone database. Unsupported zones get
  guidance rather than using server-local time as if it were the user's time.
- `/repo`: corrected URL table escaping and retained source action button.

No-argument commands reject unexpected arguments instead of ignoring them.
Known emoji/theme fallback and current permissions remain in use. Membership
lookup is not a credential/identity verification service. Live Telegram UI was
not exercised. This batch changes no persistence, secrets, plugin activation or
hosting configuration, and is not a full command-surface/parity completion.
