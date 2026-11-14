# Credits

Every plugin in this bot was written here. The projects below are the ones
that made it possible: their command surfaces, their defaults, their layouts.
That kind of debt is worth naming, and the licence column says what could
have been reused rather than what was merely read.

| Project | Author | Licence | What it gave |
| --- | --- | --- | --- |
| [Meikoagent](https://github.com/Beasgohan-code/Meikoagent) | Beasgohan-code | no licence file | the built-in plugin set: filestore, leech, music, reports, post maker, security |
| [Videl0](https://github.com/Beasgohan-code/Videl0) | Beasgohan-code | no licence file | queue and music command vocabulary |
| [Videl1](https://github.com/Beasgohan-code/Videl1) | Beasgohan-code | no licence file | keep-alive, graceful restart and plugin switching |
| [CBML](https://github.com/abhinai2244/CBML) | abhinai2244 | AGPL-3.0 | leech and mirror task commands |
| [WZML-X](https://github.com/SilentDemonSD/WZML-X) | SilentDemonSD | AGPL-3.0 | transfer status layout |
| [Multi-FileStoreBot](https://github.com/abhinai2244/Multi-FileStoreBot) | abhinai2244 | no licence file | file-store commands and quotas |
| [LINK-SHAREBOT](https://github.com/abhinai2244/LINK-SHAREBOT) | abhinai2244 | no licence file | link protection commands |
| [ENCODING-BOT](https://github.com/abhinai2244/ENCODING-BOT) | abhinai2244 | AGPL-3.0 | encoding command surface and presets |
| [save-restricted-content-bot](https://github.com/abhinai2244/save-restricted-content-bot) | LastPerson07 | MIT | saving protected media |
| [Playeon](https://github.com/playeon/Playeon) | Sushi | Attribution & personal use | music panel layout |
| [richgram](https://github.com/Badmunda05/richgram) | Badmunda05 | MIT | the rich layer this UI is built on (the repository now lives as nextgram) |
| [wzgram](https://github.com/rjriajul/wzgram) | rjriajul | LGPL-3.0 | the Telegram client |

*Written for this bot, not copied: these projects were read for command names, defaults and layout.*

## Which package came from where

| Package | Learned from |
| --- | --- |
| `agent/modules/filestore` | Meikoagent (file_store), Multi-FileStoreBot |
| `agent/modules/leech` | Meikoagent (leech), CBML, WZML-X |
| `agent/modules/music` | Videl0, Playeon |
| `agent/modules/reports` | Meikoagent (reports) |
| `agent/modules/postmaker` | Meikoagent (post_maker) |
| `agent/modules/security` | Meikoagent (security) |
| `agent/modules/premium` | Videl1 (premium tier) |
| `agent/modules/encoder` | ENCODING-BOT |
| `agent/modules/linkshare` | LINK-SHAREBOT |
| `agent/ui` | richgram |

## Checkouts on disk

Cloned locally for study, ignored by git, never imported by the bot:

```
refs/Meikoagent   refs/Videl1   refs/WZML-X   refs/richgram
music/Videl0      music/Playeon
saver/save-restricted-content-bot
Encoder/ENCODING-BOT   Filestore/Multi-FileStoreBot
Linkshare/LINK-SHAREBOT   leech/CBML
```

## Why the licences are listed

- **MIT** — reusable with attribution. `save-restricted-content-bot` and
  `richgram` are references that could legally be reused; they are still named
  because a reference you build on is not a licence to forget it.
- **AGPL-3.0** — network copyleft. `CBML`, `WZML-X` and `ENCODING-BOT` were
  read for command names and defaults only. Copying their code would put this
  whole bot under the AGPL, so none of it is here.
- **No licence file** — all rights reserved. `Meikoagent`, `Videl0`, `Videl1`,
  `Multi-FileStoreBot` and `LINK-SHAREBOT` published no licence, so the
  reference went one way: read, then re-implemented.
- **Attribution & personal use** — Playeon's own licence. Its music panel
  informed the layout; its code is not in this repository.

## Runtime dependencies

| Package | Licence | Role |
| --- | --- | --- |
| [wzgram](https://github.com/rjriajul/wzgram) | LGPL-3.0 | Telegram client |
| [richgram](https://github.com/Badmunda05/richgram) | MIT | rich messages, tables, HTML normaliser |
| [py-tgcalls](https://github.com/pytgcalls/pytgcalls) | LGPL-3.0 | voice-chat streaming, optional |
| [telethon](https://github.com/LonamiWebs/Telethon) | MIT | the user session py-tgcalls drives |
