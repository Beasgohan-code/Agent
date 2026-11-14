# Explicit feature-source catalog

Static source evidence only. No reference code, installers or startup scripts executed.
The folders are ignored review checkouts, not runtime plugin imports.
Command candidates may be unreachable, duplicated within one source or dynamically incomplete.

| Feature | Checkout | Revision | Tracked files | Commands | License review |
| --- | --- | --- | ---: | ---: | --- |
| Music | [music/Videl0](https://github.com/Beasgohan-code/Videl0) | `6430b1e5e60e0776a7ab519e05cb98c2ca1a2ebf` | 721 | 70 | No root license found; nested terms need review before code reuse. |
| Music | [music/Playeon](https://github.com/playeon/Playeon) | `6ec6097bc7f5db19583618c226a5e4c410b90cee` | 280 | 71 | Custom attribution/personal-use/non-commercial license. Do not copy into a monetized or rebranded service without permission and required notices. |
| Saver | [saver](https://github.com/abhinai2244/save-restricted-content-bot) | `bf2e45a1ef187060e053e59c0336cb0e6a4a022b` | 23 | 36 | Root MIT; preserve required notices if copying; nested dependencies still require review. |
| Encoder | [Encoder](https://github.com/abhinai2244/ENCODING-BOT) | `84d4e256e2f2047c653691b5b59bfdea2a262fae` | 51 | 29 | Root AGPL-3.0; review source-distribution/network obligations and nested terms before reuse. |
| FileStore | [Filestore](https://github.com/abhinai2244/Multi-FileStoreBot) | `010172404c2121862deea99f0fe25766d130e392` | 42 | 13 | No root license found; public availability is not blanket reuse permission. |
| Linkshare | [Linkshare](https://github.com/abhinai2244/LINK-SHAREBOT) | `265f2acbe720571e7c514cd32eea600292656fe2` | 17 | 5 | No root license found; public availability is not blanket reuse permission. |
| Leech | [leech](https://github.com/abhinai2244/CBML) | `4d13aa14a9d44af426f740db5905c3a22001ad38` | 258 | 111 | Root AGPL-3.0; review source-distribution/network obligations and nested terms before reuse. |

## Candidate command ownership and collisions

A collision means the same literal name appears in more than one requested checkout.
It does not mean implementations are interchangeable. Resolve by shared core, explicit
context or a reviewed namespace only when actually integrating the feature.

| Command | Source checkouts | Evidence (maximum 4 files) |
| --- | --- | --- |
| `/a` | leech | `leech/bot/helper/telegram_helper/bot_commands.py` |
| `/ab` | leech | `leech/bot/helper/telegram_helper/bot_commands.py` |
| `/active` | music/Videl0 | `music/Videl0/videl/modules/owner_utils.py` |
| `/add_premium` | saver | `saver/cantarella/premium.py` |
| `/add_unsubscribe` | saver | `saver/cantarella/admin.py` |
| `/addblacklist` | music/Videl0 | `music/Videl0/videl/modules/blocklist.py` |
| `/addblsticker` | music/Videl0 | `music/Videl0/videl/modules/blocklist.py` |
| `/addbot` | leech | `leech/bot/helper/telegram_helper/bot_commands.py` |
| `/addchat` | Encoder | `Encoder/VideoEncoder/plugins/auth.py` |
| `/addimage` | leech | `leech/bot/helper/telegram_helper/bot_commands.py` |
| `/addsu` | music/Playeon | `music/Playeon/playeon-bot/src/commands/dev/addsuperuser.ts` |
| `/addsudo` | Encoder, leech | `Encoder/VideoEncoder/plugins/auth.py`, `leech/bot/helper/telegram_helper/bot_commands.py` |
| `/addsuperuser` | music/Playeon | `music/Playeon/playeon-bot/src/commands/dev/addsuperuser.ts` |
| `/adminsummary` | music/Videl0 | `music/Videl0/videl/modules/group_manager.py` |
| `/aexec` | leech | `leech/bot/helper/telegram_helper/bot_commands.py` |
| `/af` | Encoder | `Encoder/VideoEncoder/plugins/encode.py` |
| `/ai` | leech | `leech/bot/helper/telegram_helper/bot_commands.py` |
| `/aikeys` | music/Playeon | `music/Playeon/playeon-bot/src/commands/dev/aikeys.ts` |
| `/analytics` | music/Playeon | `music/Playeon/playeon-bot/src/commands/dev/analytics.ts` |
| `/ap` | music/Playeon | `music/Playeon/playeon-bot/src/commands/playback/autoplay.ts` |
| `/api` | leech | `leech/bot/helper/telegram_helper/bot_commands.py` |
| `/apiinfo` | music/Videl0 | `music/Videl0/videl/modules/api_tools.py` |
| `/approval` | music/Videl0 | `music/Videl0/videl/modules/approve.py` |
| `/approve` | music/Videl0 | `music/Videl0/videl/modules/approve.py` |
| `/approved` | music/Videl0 | `music/Videl0/videl/modules/approve.py` |
| `/as` | leech | `leech/bot/helper/telegram_helper/bot_commands.py` |
| `/auth` | music/Playeon | `music/Playeon/playeon-bot/src/commands/playback/auth.ts` |
| `/authlist` | music/Playeon | `music/Playeon/playeon-bot/src/commands/playback/authusers.ts` |
| `/authorize` | leech | `leech/bot/helper/telegram_helper/bot_commands.py` |
| `/authusers` | music/Playeon | `music/Playeon/playeon-bot/src/commands/playback/authusers.ts` |
| `/autoplay` | music/Playeon | `music/Playeon/playeon-bot/src/commands/playback/autoplay.ts` |
| `/ban` | Filestore, saver | `saver/cantarella/admin.py`, `Filestore/main_bot/plugins/bans.py`, `Filestore/main_bot/plugins/create_bot.py`, `Filestore/worker_bot/engine.py` |
| `/batch` | Encoder, Filestore, Linkshare | `Encoder/VideoEncoder/plugins/encode.py`, `Filestore/worker_bot/link_gen.py`, `Linkshare/plugins/settings.py` |
| `/bc` | leech, music/Playeon | `music/Playeon/playeon-bot/src/commands/dev/broadcast.ts`, `leech/bot/helper/telegram_helper/bot_commands.py` |
| `/bl` | leech | `leech/bot/helper/telegram_helper/bot_commands.py` |
| `/blacklist` | leech, music/Videl0 | `music/Videl0/videl/modules/blocklist.py`, `leech/bot/helper/telegram_helper/bot_commands.py` |
| `/blacklistmode` | music/Videl0 | `music/Videl0/videl/modules/blocklist.py` |
| `/blocklist` | music/Videl0 | `music/Videl0/videl/modules/block.py` |
| `/blstickers` | music/Videl0 | `music/Videl0/videl/modules/blocklist.py` |
| `/broadcast` | Filestore, Linkshare, leech, music/Playeon, music/Videl0, saver | `music/Videl0/videl/modules/broadcast.py`, `music/Playeon/playeon-bot/src/commands/dev/broadcast.ts`, `saver/cantarella/broadcast.py`, `Filestore/main_bot/plugins/broadcast.py` |
| `/bs` | leech | `leech/bot/helper/telegram_helper/bot_commands.py` |
| `/bsetting` | leech | `leech/bot/helper/telegram_helper/bot_commands.py` |
| `/bw` | music/Playeon | `music/Playeon/playeon-bot/src/commands/playback/bw.ts` |
| `/c` | leech | `leech/bot/helper/telegram_helper/bot_commands.py` |
| `/call` | leech | `leech/bot/helper/telegram_helper/bot_commands.py` |
| `/cancel` | leech, saver | `saver/cantarella/session.py`, `saver/cantarella/start.py`, `leech/bot/helper/telegram_helper/bot_commands.py` |
| `/cancel_rl` | leech | `leech/bot/helper/telegram_helper/bot_commands.py` |
| `/cancelall` | leech | `leech/bot/helper/telegram_helper/bot_commands.py` |
| `/cancellogin` | saver | `saver/cantarella/session.py` |
| `/cancelrange` | leech | `leech/bot/helper/telegram_helper/bot_commands.py` |
| `/cancelrangelink` | leech | `leech/bot/helper/telegram_helper/bot_commands.py` |
| `/cancelrl` | leech | `leech/bot/helper/telegram_helper/bot_commands.py` |
| `/category` | leech | `leech/bot/helper/telegram_helper/bot_commands.py` |
| `/channelplay` | music/Videl0 | `music/Videl0/videl/modules/cplay.py` |
| `/chatfed` | music/Videl0 | `music/Videl0/videl/modules/federation.py` |
| `/check` | Filestore | `Filestore/main_bot/plugins/create_bot.py` |
| `/cl` | leech | `leech/bot/helper/telegram_helper/bot_commands.py` |
| `/clean` | Encoder | `Encoder/VideoEncoder/plugins/start.py` |
| `/clear` | Encoder | `Encoder/VideoEncoder/plugins/queue.py` |
| `/clearlocals` | leech | `leech/bot/helper/telegram_helper/bot_commands.py` |
| `/clone` | leech | `leech/bot/helper/telegram_helper/bot_commands.py` |
| `/cmd` | saver | `saver/bot.py` |
| `/commandpreset` | music/Videl0 | `music/Videl0/videl/modules/group_manager.py` |
| `/commands` | saver | `saver/cantarella/settings.py` |
| `/cookies` | leech | `leech/bot/helper/telegram_helper/bot_commands.py` |
| `/cookiesettings` | leech | `leech/bot/helper/telegram_helper/bot_commands.py` |
| `/copy` | music/Videl0 | `music/Videl0/videl/modules/api_tools.py` |
| `/count` | leech | `leech/bot/helper/telegram_helper/bot_commands.py` |
| `/ctsel` | leech | `leech/bot/helper/telegram_helper/bot_commands.py` |
| `/custom_batch` | Filestore | `Filestore/worker_bot/link_gen.py` |
| `/dbcleanup` | music/Videl0 | `music/Videl0/videl/modules/misc.py` |
| `/dblink` | saver | `saver/cantarella/admin.py` |
| `/ddl` | Encoder | `Encoder/VideoEncoder/plugins/encode.py` |
| `/del` | leech | `leech/bot/helper/telegram_helper/bot_commands.py` |
| `/del_caption` | saver | `saver/cantarella/caption.py` |
| `/del_thumb` | saver | `saver/cantarella/thumbnail.py` |
| `/del_unsubscribe` | saver | `saver/cantarella/admin.py` |
| `/delblacklist` | music/Videl0 | `music/Videl0/videl/modules/blocklist.py` |
| `/delblsticker` | music/Videl0 | `music/Videl0/videl/modules/blocklist.py` |
| `/delete_thumb` | saver | `saver/cantarella/thumbnail.py` |
| `/deleteplaylist` | music/Videl0 | `music/Videl0/videl/modules/playlist.py` |
| `/delfed` | music/Videl0 | `music/Videl0/videl/modules/federation.py` |
| `/delsu` | music/Playeon | `music/Playeon/playeon-bot/src/commands/dev/delsuperuser.ts` |
| `/delsuperuser` | music/Playeon | `music/Playeon/playeon-bot/src/commands/dev/delsuperuser.ts` |
| `/demo` | music/Playeon | `music/Playeon/playeon-bot/src/commands/dev/demo.ts` |
| `/devplay` | music/Playeon | `music/Playeon/playeon-bot/src/commands/dev/testplay.ts` |
| `/dl` | Encoder | `Encoder/VideoEncoder/plugins/encode.py` |
| `/download` | music/Videl0 | `music/Videl0/videl/modules/downloader.py` |
| `/dupload` | Encoder | `Encoder/VideoEncoder/plugins/upload.py` |
| `/e` | music/Playeon | `music/Playeon/playeon-bot/src/commands/misc/e.ts` |
| `/emojiinfo` | music/Videl0 | `music/Videl0/videl/modules/api_tools.py` |
| `/end` | music/Playeon | `music/Playeon/playeon-bot/src/commands/playback/end.ts` |
| `/eval` | music/Playeon | `music/Playeon/playeon-bot/src/commands/dev/eval.ts` |
| `/exec` | Encoder, leech | `Encoder/VideoEncoder/plugins/pyexec.py`, `leech/bot/helper/telegram_helper/bot_commands.py` |
| `/faddadmin` | music/Videl0 | `music/Videl0/videl/modules/federation.py` |
| `/fban` | music/Videl0 | `music/Videl0/videl/modules/federation.py` |
| `/fdemote` | music/Videl0 | `music/Videl0/videl/modules/federation.py` |
| `/fedbanlist` | music/Videl0 | `music/Videl0/videl/modules/federation.py` |
| `/fedchats` | music/Videl0 | `music/Videl0/videl/modules/federation.py` |
| `/fedinfo` | music/Videl0 | `music/Videl0/videl/modules/federation.py` |
| `/fedstat` | music/Videl0 | `music/Videl0/videl/modules/federation.py` |
| `/flink` | Filestore | `Filestore/worker_bot/link_gen.py` |
| `/forcestart` | leech | `leech/bot/helper/telegram_helper/bot_commands.py` |
| `/fpromote` | music/Videl0 | `music/Videl0/videl/modules/federation.py` |
| `/fremadmin` | music/Videl0 | `music/Videl0/videl/modules/federation.py` |
| `/fs` | leech | `leech/bot/helper/telegram_helper/bot_commands.py` |
| `/fw` | music/Playeon | `music/Playeon/playeon-bot/src/commands/playback/fw.ts` |
| `/gblock` | music/Videl0 | `music/Videl0/videl/modules/block.py` |
| `/gcast` | music/Videl0 | `music/Videl0/videl/modules/broadcast.py` |
| `/gdc` | leech | `leech/bot/helper/telegram_helper/bot_commands.py` |
| `/gdclean` | leech | `leech/bot/helper/telegram_helper/bot_commands.py` |
| `/genlink` | Filestore, Linkshare | `Filestore/worker_bot/link_gen.py`, `Linkshare/plugins/settings.py` |
| `/globals` | music/Playeon | `music/Playeon/playeon-bot/src/commands/general/globals.ts` |
| `/group` | music/Videl0 | `music/Videl0/videl/modules/group_manager.py` |
| `/groups` | music/Playeon | `music/Playeon/playeon-bot/src/commands/dev/groupslist.ts` |
| `/groupslist` | music/Playeon | `music/Playeon/playeon-bot/src/commands/dev/groupslist.ts` |
| `/gtop` | music/Playeon | `music/Playeon/playeon-bot/src/commands/general/globals.ts` |
| `/gunblock` | music/Videl0 | `music/Videl0/videl/modules/block.py` |
| `/gupload` | Encoder | `Encoder/VideoEncoder/plugins/upload.py` |
| `/h` | leech | `leech/bot/helper/telegram_helper/bot_commands.py` |
| `/hello` | music/Playeon | `music/Playeon/playeon-bot/src/commands/general/ping.ts` |
| `/help` | Encoder, leech, saver | `saver/cantarella/start.py`, `Encoder/VideoEncoder/plugins/start.py`, `leech/bot/helper/telegram_helper/bot_commands.py` |
| `/images` | leech | `leech/bot/helper/telegram_helper/bot_commands.py` |
| `/img` | leech | `leech/bot/helper/telegram_helper/bot_commands.py` |
| `/info` | music/Playeon | `music/Playeon/playeon-bot/src/commands/general/info.ts` |
| `/invite` | music/Playeon | `music/Playeon/playeon-bot/src/commands/general/invite.ts` |
| `/jdleech` | leech | `leech/bot/helper/telegram_helper/bot_commands.py` |
| `/jdmirror` | leech | `leech/bot/helper/telegram_helper/bot_commands.py` |
| `/jl` | leech | `leech/bot/helper/telegram_helper/bot_commands.py` |
| `/jm` | leech | `leech/bot/helper/telegram_helper/bot_commands.py` |
| `/joinfed` | music/Videl0 | `music/Videl0/videl/modules/federation.py` |
| `/l` | leech | `leech/bot/helper/telegram_helper/bot_commands.py` |
| `/lb` | music/Playeon | `music/Playeon/playeon-bot/src/commands/general/leaderboard.ts` |
| `/leaderboard` | music/Playeon | `music/Playeon/playeon-bot/src/commands/general/leaderboard.ts` |
| `/leavefed` | music/Videl0 | `music/Videl0/videl/modules/federation.py` |
| `/leech` | leech | `leech/bot/helper/telegram_helper/bot_commands.py` |
| `/lh` | leech | `leech/bot/helper/telegram_helper/bot_commands.py` |
| `/list` | leech | `leech/bot/helper/telegram_helper/bot_commands.py` |
| `/log` | leech | `leech/bot/helper/telegram_helper/bot_commands.py` |
| `/login` | leech, saver | `saver/cantarella/session.py`, `leech/bot/helper/telegram_helper/bot_commands.py` |
| `/logout` | saver | `saver/cantarella/session.py` |
| `/logs` | Encoder, music/Playeon | `music/Playeon/playeon-bot/src/commands/dev/logs.ts`, `Encoder/VideoEncoder/plugins/upload.py` |
| `/loop` | music/Playeon | `music/Playeon/playeon-bot/src/commands/playback/loop.ts` |
| `/lyrics` | music/Videl0 | `music/Videl0/videl/modules/lyrics.py` |
| `/m` | leech | `leech/bot/helper/telegram_helper/bot_commands.py` |
| `/maintenance` | music/Videl0 | `music/Videl0/videl/modules/group_manager.py` |
| `/me` | music/Playeon | `music/Playeon/playeon-bot/src/commands/general/rank.ts` |
| `/mem` | leech | `leech/bot/helper/telegram_helper/bot_commands.py` |
| `/memory` | leech | `leech/bot/helper/telegram_helper/bot_commands.py` |
| `/mirror` | leech | `leech/bot/helper/telegram_helper/bot_commands.py` |
| `/mock` | music/Playeon | `music/Playeon/playeon-bot/src/commands/dev/mock.ts` |
| `/mocktest` | music/Playeon | `music/Playeon/playeon-bot/src/commands/dev/mock.ts` |
| `/modqueue` | music/Videl0 | `music/Videl0/videl/modules/group_manager.py` |
| `/my` | music/Playeon | `music/Playeon/playeon-bot/src/commands/general/rank.ts` |
| `/myfeds` | music/Videl0 | `music/Videl0/videl/modules/federation.py` |
| `/myplan` | saver | `saver/cantarella/premium.py`, `saver/cantarella/start.py` |
| `/newfed` | music/Videl0 | `music/Videl0/videl/modules/federation.py` |
| `/nl` | leech | `leech/bot/helper/telegram_helper/bot_commands.py` |
| `/nm` | leech | `leech/bot/helper/telegram_helper/bot_commands.py` |
| `/nowplaying` | music/Playeon | `music/Playeon/playeon-bot/src/commands/playback/playing.ts` |
| `/nzbleech` | leech | `leech/bot/helper/telegram_helper/bot_commands.py` |
| `/nzbmirror` | leech | `leech/bot/helper/telegram_helper/bot_commands.py` |
| `/pause` | music/Playeon | `music/Playeon/playeon-bot/src/commands/playback/pause.ts` |
| `/permissions` | music/Videl0 | `music/Videl0/videl/modules/group_manager.py` |
| `/ping` | Filestore, leech, music/Playeon, music/Videl0 | `music/Videl0/tests/test_command_prefixes.py`, `music/Videl0/videl/__main__.py`, `music/Videl0/videl/utils/db.py`, `music/Playeon/playeon-bot/src/commands/general/ping.ts` |
| `/plan` | saver | `saver/cantarella/start.py` |
| `/play` | music/Playeon | `music/Playeon/playeon-bot/src/commands/playback/play.ts` |
| `/playing` | music/Playeon | `music/Playeon/playeon-bot/src/commands/playback/playing.ts` |
| `/playlist` | music/Videl0 | `music/Videl0/videl/modules/playlist.py` |
| `/playlists` | music/Videl0 | `music/Videl0/videl/modules/playlist.py` |
| `/plugins` | leech | `leech/bot/helper/telegram_helper/bot_commands.py` |
| `/pollstop` | music/Videl0 | `music/Videl0/videl/modules/api_tools.py` |
| `/prefix` | music/Playeon | `music/Playeon/playeon-bot/src/commands/misc/prefix.ts` |
| `/premium` | saver | `saver/cantarella/premium.py`, `saver/cantarella/start.py` |
| `/privacy` | music/Playeon | `music/Playeon/playeon-bot/src/commands/general/privacy.ts` |
| `/purgeranks` | music/Playeon | `music/Playeon/playeon-bot/src/commands/dev/resetrank.ts` |
| `/qbleech` | leech | `leech/bot/helper/telegram_helper/bot_commands.py` |
| `/qbmirror` | leech | `leech/bot/helper/telegram_helper/bot_commands.py` |
| `/ql` | leech | `leech/bot/helper/telegram_helper/bot_commands.py` |
| `/qm` | leech | `leech/bot/helper/telegram_helper/bot_commands.py` |
| `/queue` | Encoder, music/Playeon | `music/Playeon/playeon-bot/src/commands/playback/queue.ts`, `Encoder/VideoEncoder/plugins/queue.py` |
| `/r` | leech | `leech/bot/helper/telegram_helper/bot_commands.py` |
| `/radiomode` | music/Playeon | `music/Playeon/playeon-bot/src/commands/playback/autoplay.ts` |
| `/rank` | music/Playeon | `music/Playeon/playeon-bot/src/commands/general/rank.ts` |
| `/rbl` | leech | `leech/bot/helper/telegram_helper/bot_commands.py` |
| `/react` | music/Videl0 | `music/Videl0/videl/modules/api_tools.py` |
| `/reboot` | music/Playeon | `music/Playeon/playeon-bot/src/commands/misc/reboot.ts` |
| `/refresh` | music/Playeon | `music/Playeon/playeon-bot/src/commands/misc/refresh.ts` |
| `/rem_del_word` | saver | `saver/cantarella/words.py` |
| `/rem_repl_word` | saver | `saver/cantarella/words.py` |
| `/remove_premium` | saver | `saver/cantarella/premium.py` |
| `/removesu` | music/Playeon | `music/Playeon/playeon-bot/src/commands/dev/delsuperuser.ts` |
| `/removesuperuser` | music/Playeon | `music/Playeon/playeon-bot/src/commands/dev/delsuperuser.ts` |
| `/reqff` | leech | `leech/bot/helper/telegram_helper/bot_commands.py` |
| `/requestff` | leech | `leech/bot/helper/telegram_helper/bot_commands.py` |
| `/reset` | Encoder | `Encoder/VideoEncoder/plugins/settings.py` |
| `/resetlevels` | music/Playeon | `music/Playeon/playeon-bot/src/commands/dev/resetrank.ts` |
| `/resetrank` | music/Playeon | `music/Playeon/playeon-bot/src/commands/dev/resetrank.ts` |
| `/restart` | Encoder, leech, music/Videl0 | `music/Videl0/videl/modules/voice_admin.py`, `Encoder/VideoEncoder/plugins/start.py`, `leech/bot/helper/telegram_helper/bot_commands.py` |
| `/restartall` | leech | `leech/bot/helper/telegram_helper/bot_commands.py` |
| `/restartses` | leech | `leech/bot/helper/telegram_helper/bot_commands.py` |
| `/resume` | music/Playeon | `music/Playeon/playeon-bot/src/commands/playback/resume.ts` |
| `/reviewer` | music/Videl0 | `music/Videl0/videl/modules/group_manager.py` |
| `/rmblacklist` | leech, music/Videl0 | `music/Videl0/videl/modules/blocklist.py`, `leech/bot/helper/telegram_helper/bot_commands.py` |
| `/rmchat` | Encoder | `Encoder/VideoEncoder/plugins/auth.py` |
| `/rmsudo` | Encoder, leech | `Encoder/VideoEncoder/plugins/auth.py`, `leech/bot/helper/telegram_helper/bot_commands.py` |
| `/room` | music/Playeon | `music/Playeon/playeon-bot/src/commands/playback/room.ts` |
| `/rooms` | music/Playeon | `music/Playeon/playeon-bot/src/commands/dev/rooms.ts` |
| `/rs` | leech | `leech/bot/helper/telegram_helper/bot_commands.py` |
| `/rses` | leech | `leech/bot/helper/telegram_helper/bot_commands.py` |
| `/rss` | leech | `leech/bot/helper/telegram_helper/bot_commands.py` |
| `/s` | leech | `leech/bot/helper/telegram_helper/bot_commands.py` |
| `/saveplaylist` | music/Videl0 | `music/Videl0/videl/modules/playlist.py` |
| `/sdl` | leech | `leech/bot/helper/telegram_helper/bot_commands.py` |
| `/sdt` | leech | `leech/bot/helper/telegram_helper/bot_commands.py` |
| `/search` | leech | `leech/bot/helper/telegram_helper/bot_commands.py` |
| `/see_caption` | saver | `saver/cantarella/caption.py` |
| `/see_thumb` | saver | `saver/cantarella/thumbnail.py` |
| `/seedrlink` | leech | `leech/bot/helper/telegram_helper/bot_commands.py` |
| `/seek` | music/Playeon | `music/Playeon/playeon-bot/src/commands/playback/seek.ts` |
| `/sel` | leech | `leech/bot/helper/telegram_helper/bot_commands.py` |
| `/select` | leech | `leech/bot/helper/telegram_helper/bot_commands.py` |
| `/set_caption` | saver | `saver/cantarella/caption.py` |
| `/set_del_word` | saver | `saver/cantarella/words.py` |
| `/set_dump` | saver | `saver/cantarella/admin.py` |
| `/set_repl_word` | saver | `saver/cantarella/words.py` |
| `/set_thumb` | saver | `saver/cantarella/thumbnail.py` |
| `/setbanner` | music/Playeon | `music/Playeon/playeon-bot/src/commands/dev/setbanner.ts` |
| `/setbotdescription` | music/Videl0 | `music/Videl0/videl/modules/api_tools.py` |
| `/setbotname` | music/Videl0 | `music/Videl0/videl/modules/api_tools.py` |
| `/setbotphoto` | music/Videl0 | `music/Videl0/videl/modules/api_tools.py` |
| `/setbotshortdescription` | music/Videl0 | `music/Videl0/videl/modules/api_tools.py` |
| `/setchat` | saver | `saver/cantarella/settings.py` |
| `/setlogchat` | music/Playeon | `music/Playeon/playeon-bot/src/commands/dev/setlogchat.ts` |
| `/settings` | Encoder, Linkshare, saver | `saver/cantarella/settings.py`, `Encoder/VideoEncoder/plugins/settings.py`, `Linkshare/plugins/settings.py` |
| `/sh` | Encoder | `Encoder/VideoEncoder/plugins/pyexec.py` |
| `/shell` | leech | `leech/bot/helper/telegram_helper/bot_commands.py` |
| `/skip` | music/Playeon | `music/Playeon/playeon-bot/src/commands/playback/skip.ts` |
| `/sl` | leech | `leech/bot/helper/telegram_helper/bot_commands.py` |
| `/slink` | leech | `leech/bot/helper/telegram_helper/bot_commands.py` |
| `/socialdl` | leech | `leech/bot/helper/telegram_helper/bot_commands.py` |
| `/song` | music/Videl0 | `music/Videl0/videl/modules/downloader.py` |
| `/source` | Encoder | `Encoder/VideoEncoder/utils/__init__.py` |
| `/speedtest` | Encoder | `Encoder/VideoEncoder/plugins/speed_test.py` |
| `/srlink` | leech | `leech/bot/helper/telegram_helper/bot_commands.py` |
| `/st` | leech | `leech/bot/helper/telegram_helper/bot_commands.py` |
| `/start` | Encoder, Filestore, Linkshare, leech, music/Playeon, music/Videl0, saver | `music/Videl0/vendor/richgram/bot.py`, `music/Playeon/playeon-bot/src/commands/general/start.ts`, `saver/cantarella/start.py`, `Encoder/VideoEncoder/plugins/start.py` |
| `/stats` | Encoder, leech, music/Playeon | `music/Playeon/playeon-bot/src/commands/dev/stats.ts`, `Encoder/VideoEncoder/plugins/start.py`, `leech/bot/helper/telegram_helper/bot_commands.py` |
| `/status` | Encoder, leech | `Encoder/VideoEncoder/plugins/status.py`, `leech/bot/helper/telegram_helper/bot_commands.py` |
| `/statusall` | leech | `leech/bot/helper/telegram_helper/bot_commands.py` |
| `/stream` | leech, music/Playeon | `music/Playeon/playeon-bot/src/commands/playback/vplay.ts`, `leech/bot/helper/telegram_helper/bot_commands.py` |
| `/style` | music/Playeon | `music/Playeon/playeon-bot/src/commands/playback/style.ts` |
| `/sysinfo` | music/Videl0 | `music/Videl0/videl/modules/owner_utils.py` |
| `/sysstats` | Filestore | `Filestore/main_bot/plugins/create_bot.py` |
| `/systats` | Filestore | `Filestore/main_bot/plugins/create_bot.py` |
| `/taskm` | leech | `leech/bot/helper/telegram_helper/bot_commands.py` |
| `/taskuser` | leech | `leech/bot/helper/telegram_helper/bot_commands.py` |
| `/testmock` | music/Playeon | `music/Playeon/playeon-bot/src/commands/dev/mock.ts` |
| `/testplay` | music/Playeon | `music/Playeon/playeon-bot/src/commands/dev/testplay.ts` |
| `/thumb` | Encoder | `Encoder/VideoEncoder/plugins/thumbnail.py` |
| `/thumb_mode` | saver | `saver/cantarella/thumbnail.py` |
| `/tm` | leech | `leech/bot/helper/telegram_helper/bot_commands.py` |
| `/tplay` | music/Playeon | `music/Playeon/playeon-bot/src/commands/dev/testplay.ts` |
| `/tu` | leech | `leech/bot/helper/telegram_helper/bot_commands.py` |
| `/tvplay` | music/Playeon | `music/Playeon/playeon-bot/src/commands/dev/testplay.ts` |
| `/ua` | leech | `leech/bot/helper/telegram_helper/bot_commands.py` |
| `/ublock` | music/Videl0 | `music/Videl0/videl/modules/block.py` |
| `/unapprove` | music/Videl0 | `music/Videl0/videl/modules/approve.py` |
| `/unauth` | music/Playeon | `music/Playeon/playeon-bot/src/commands/playback/unauth.ts` |
| `/unauthorize` | leech | `leech/bot/helper/telegram_helper/bot_commands.py` |
| `/unban` | Filestore, saver | `saver/cantarella/admin.py`, `Filestore/main_bot/plugins/bans.py`, `Filestore/main_bot/plugins/create_bot.py`, `Filestore/worker_bot/engine.py` |
| `/unfban` | music/Videl0 | `music/Videl0/videl/modules/federation.py` |
| `/up` | leech | `leech/bot/helper/telegram_helper/bot_commands.py` |
| `/update` | Encoder | `Encoder/VideoEncoder/plugins/start.py` |
| `/uphoster` | leech | `leech/bot/helper/telegram_helper/bot_commands.py` |
| `/us` | leech | `leech/bot/helper/telegram_helper/bot_commands.py` |
| `/users` | Filestore, leech, music/Playeon, saver | `music/Playeon/playeon-bot/src/commands/dev/userslist.ts`, `saver/cantarella/broadcast.py`, `Filestore/main_bot/plugins/create_bot.py`, `leech/bot/helper/telegram_helper/bot_commands.py` |
| `/userslist` | music/Playeon | `music/Playeon/playeon-bot/src/commands/dev/userslist.ts` |
| `/usetting` | leech | `leech/bot/helper/telegram_helper/bot_commands.py` |
| `/uunblock` | music/Videl0 | `music/Videl0/videl/modules/block.py` |
| `/view_thumb` | saver | `saver/cantarella/thumbnail.py` |
| `/voicehealth` | music/Videl0 | `music/Videl0/videl/modules/voice_admin.py` |
| `/voicequality` | music/Videl0 | `music/Videl0/videl/modules/voice_admin.py` |
| `/voteskip` | music/Videl0 | `music/Videl0/videl/modules/smartqueue.py` |
| `/vplay` | music/Playeon | `music/Playeon/playeon-bot/src/commands/playback/vplay.ts` |
| `/vset` | Encoder | `Encoder/VideoEncoder/plugins/settings.py` |
| `/vsong` | music/Videl0 | `music/Videl0/videl/modules/downloader.py` |
| `/vupload` | Encoder | `Encoder/VideoEncoder/plugins/upload.py` |
| `/watchdog` | music/Videl0 | `music/Videl0/videl/modules/misc.py` |
| `/y` | leech | `leech/bot/helper/telegram_helper/bot_commands.py` |
| `/yl` | leech | `leech/bot/helper/telegram_helper/bot_commands.py` |
| `/ytdl` | leech | `leech/bot/helper/telegram_helper/bot_commands.py` |
| `/ytdlleech` | leech | `leech/bot/helper/telegram_helper/bot_commands.py` |

Unique candidates: **293**. Cross-checkout name collisions: **24**.

## Parse/size exceptions

- leech/config.py: parse:SyntaxError line 4
- leech/plugins/mediainfo/mediainfo.py: parse:SyntaxError line 79
