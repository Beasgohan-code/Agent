# Agent command comparison across supplied references

Read-only static evidence at the 29 revisions in `references/README.md`.
No reference source was executed. Agent manifests are declarations, not live availability.
Literal candidates come from command-like calls, not proven reachable handlers.
Text hits include regex/dynamic/non-Python clues and can be unrelated identifiers.
**Neither a name match nor absence establishes behavior parity or authorizes deletion.**

| Agent command | Module | Evidence | Example source files (maximum 3) |
| --- | --- | --- | --- |
| `/about` | core | literal candidate | `MediaVaultBot/telegram/plugins/commands.py`, `MediaVaultBot/telegram/plugins/url_download.py`, `Videl1/VidelBot/core/menus.py` |
| `/addpremium` | premium | literal candidate | `AnimeDL/cantarella/telegram/plugins/admin_cmds.py`, `Manhua-Bot/plugins/premium_cmd.py`, `Videl1/VidelBot/filestore/worker_bot/extras.py` |
| `/admins` | group | literal candidate | `AnimeDL/cantarella/telegram/plugins/admin_cmds.py`, `MediaVaultBot/telegram/plugins/commands.py`, `MediaVaultBot/telegram/plugins/url_download.py` |
| `/alive` | core | source-text clue only | `AnimeDL/anime_sources/animepahe.py`, `AnimeDL/anime_sources/base.py`, `AnimeDL/anime_sources/hianime.py` |
| `/antispam` | moderation | literal candidate | `Videl1/modules/commands/vanitas.py` |
| `/appeal` | reports | source-text clue only | `Videl0/scripts/build_webapp_commands.py`, `Videl0/videl/plugins/appeals.py`, `Videl0/webapp/src/lib/commands.ts` |
| `/ask` | ai_agent | source-text clue only | `AnimeDL/anime_sources/__init__.py`, `AnimeDL/leechbot/downloader/mega.py`, `AnimeDL/tests/test_e2e_binary.py` |
| `/autorename` | renamer | literal candidate | `AnimeDL/leechbot/commands/autorename.py`, `Videl1/VidelBot/renamer/handlers.py` |
| `/ban` | moderation | literal candidate | `AnimeDL/cantarella/telegram/plugins/admin_cmds.py`, `Manhua-Bot/plugins/admin.py`, `MediaVaultBot/telegram/plugins/commands.py` |
| `/batch` | filestore | literal candidate | `MediaVaultBot/telegram/plugins/batch.py`, `Son-Goku-FileStoreBot/worker_bot/link_gen.py`, `Videl1/VidelBot/VideoEncoder/plugins/encode.py` |
| `/cancel` | core | literal candidate | `AnimeDL/leechbot/commands/admin.py`, `AnimeDL/leechbot/handlers.py`, `Videl1/VidelBot/core/menus.py` |
| `/check` | filestore | literal candidate | `AnimeDL/mangarepo/plugins/check/cmd.py`, `Manhua-Bot/plugins/check/cmd.py`, `Son-Goku-FileStoreBot/main_bot/plugins/create_bot.py` |
| `/clean` | renamer | literal candidate | `MediaVaultBot/telegram/plugins/extras.py`, `MediaVaultBot/telegram/plugins/url_download.py`, `Videl1/VidelBot/VideoEncoder/plugins/start.py` |
| `/clear` | music | literal candidate | `Videl/videl/modules/stop.py`, `Videl1/VidelBot/VideoEncoder/plugins/queue.py` |
| `/clearqueue` | music | literal candidate | `Manhua-Bot/plugins/queue_cmd.py` |
| `/clone` | clone | literal candidate | `Videl1/VidelBot/core/menus.py`, `Videl1/modules/commands/clone.py` |
| `/clonestats` | clone | literal candidate | `Videl1/VidelBot/filestore/main_bot/plugins/owner_cmds.py`, `Videl1/modules/commands/clone.py` |
| `/compress` | encoder | literal candidate | `MediaVaultBot/telegram/plugins/media_tools.py`, `Videl1/VidelBot/VideoEncoder/plugins/compress.py` |
| `/db` | ops | source-text clue only | `AnimeDL/cantarella/core/database.py`, `AnimeDL/cantarella/telegram/decorators.py`, `AnimeDL/cantarella/telegram/download.py` |
| `/del` | filestore | literal candidate | `AnimeDL/mangarepo/plugins/list.py`, `Manhua-Bot/plugins/list.py`, `Videl1/modules/commands/admin.py` |
| `/delcaption` | renamer | no static match | Manual review needed before removal |
| `/delclone` | clone | source-text clue only | `Videl1/modules/commands/clone.py`, `file-store-bot/bot/commands.py`, `file-store-bot/bot/handlers.py` |
| `/deleteplaylist` | music | literal candidate | `Videl/videl/modules/playlist.py`, `Videl0/videl/modules/playlist.py` |
| `/delpremium` | premium | literal candidate | `AnimeDL/cantarella/telegram/plugins/admin_cmds.py`, `Manhua-Bot/plugins/premium_cmd.py`, `Videl1/VidelBot/filestore/worker_bot/extras.py` |
| `/delthumb` | renamer | literal candidate | `MediaVaultBot/telegram/plugins/thumbnails.py`, `Videl1/VidelBot/saver/thumbnail.py` |
| `/enccancel` | encoder | no static match | Manual review needed before removal |
| `/encinfo` | encoder | no static match | Manual review needed before removal |
| `/encode` | encoder | source-text clue only | `AnimeDL/anime_sources/allanime.py`, `AnimeDL/anime_sources/aniskip.py`, `AnimeDL/anime_sources/gogo.py` |
| `/encpreset` | encoder | no static match | Manual review needed before removal |
| `/end` | music | literal candidate | `Videl/videl/modules/stop.py` |
| `/errors` | ops | source-text clue only | `AnimeDL/anime_sources/allanime.py`, `AnimeDL/anime_sources/aniworld.py`, `AnimeDL/anime_sources/gogo.py` |
| `/events` | ops | source-text clue only | `AnimeDL/cantarella/telegram/plugins/callbacks/fsub.py`, `AnimeDL/tests/test_e2e_binary.py`, `Obra-ai/services/db.py` |
| `/files` | filestore | source-text clue only | `AnimeDL/anime_sources/kaiwave.py`, `AnimeDL/anime_sources/streamdl.py`, `AnimeDL/anime_sources/tokyoinsider.py` |
| `/filter` | filters | source-text clue only | `AnimeDL/anime_sources/gogo.py`, `AnimeDL/anime_sources/kaiwave.py`, `AnimeDL/cantarella/scraper/megacloud.py` |
| `/filters` | filters | source-text clue only | `AnimeDL/anime_sources/animegg.py`, `AnimeDL/cantarella/telegram/plugins/admin_cmds.py`, `AnimeDL/cantarella/telegram/plugins/callbacks/admin.py` |
| `/fsave` | filestore | no static match | Manual review needed before removal |
| `/genlink` | linkshare | literal candidate | `Son-Goku-FileStoreBot/worker_bot/link_gen.py`, `Videl1/VidelBot/filestore/worker_bot/link_gen.py` |
| `/get` | filestore | source-text clue only | `AnimeDL/anime_sources/__init__.py`, `AnimeDL/anime_sources/allanime.py`, `AnimeDL/anime_sources/animegg.py` |
| `/goodbye` | welcome | source-text clue only | `AnimeDL/anime_sources/hianime.py`, `VYRON/vyron/core/chatcfg.py`, `VYRON/vyron/modules/moderation.py` |
| `/help` | builtin | literal candidate | `AnimeDL/cantarella/telegram/plugins/commands.py`, `AnimeDL/leechbot/handlers.py`, `Manhua-Bot/plugins/help_cmd.py` |
| `/history` | music | literal candidate | `AnimeDL/cantarella/telegram/plugins/commands.py` |
| `/id` | utilities | literal candidate | `MediaVaultBot/telegram/plugins/sites_admin.py`, `Son-Goku-FileStoreBot/worker_bot/engine.py`, `Videl/videl/modules/misc.py` |
| `/info` | utilities | literal candidate | `AnimeDL/mangarepo/plugins/check/cmd.py`, `Manhua-Bot/plugins/check/cmd.py`, `Videl1/VidelBot/core/tools.py` |
| `/jump` | music | source-text clue only | `Kairo/app/src/main/java/com/kairo/app/MainActivity.java`, `VYRON/frontend/src/lib/audio.tsx`, `VYRON/frontend/src/lib/queueops.ts` |
| `/kick` | moderation | literal candidate | `Videl/videl/modules/admin.py`, `Videl1/modules/commands/bans.py` |
| `/leave` | music | source-text clue only | `AnimeDL/leechbot/utility/rss_manager.py`, `Kairo/app/src/main/java/com/kairo/app/MainActivity.java`, `Kairo/app/src/main/java/com/kairo/app/core/ApiKeyStore.java` |
| `/leech` | leech | literal candidate | `Videl1/VidelBot/VideoEncoder/plugins/tools.py` |
| `/leechstats` | leech | no static match | Manual review needed before removal |
| `/links` | linkshare | literal candidate | `Videl1/VidelBot/filestore/worker_bot/extras.py` |
| `/lockdown` | group | source-text clue only | `Videl0/tests/test_group_admin.py`, `Videl0/videl/utils/group_view.py`, `Videl0/webapp/src/lib/group-admin.ts` |
| `/log` | ops | source-text clue only | `AnimeDL/anime_sources/streamdl.py`, `AnimeDL/cantarella/core/anilist.py`, `AnimeDL/cantarella/scraper/cantarellatv.py` |
| `/loop` | music | source-text clue only | `AnimeDL/cantarella/__main__.py`, `AnimeDL/cantarella/telegram/ongoing.py`, `AnimeDL/cantarella/telegram/plugins/callbacks/anime.py` |
| `/menu` | core | source-text clue only | `AnimeDL/anime_sources/__init__.py`, `AnimeDL/cantarella/telegram/plugins/callbacks/settings.py`, `AnimeDL/cantarella/telegram/plugins/commands.py` |
| `/mirror` | leech | literal candidate | `Videl1/VidelBot/VideoEncoder/plugins/tools.py` |
| `/modlog` | moderation | source-text clue only | `file-store-bot/bot/commands.py` |
| `/move` | music | source-text clue only | `JARVIS-Mark-XXXIX-Android/app/src/main/java/com/jarvis/mark39/service/OverlayBubbleService.kt`, `MediaVaultBot/telegram/plugins/rename.py`, `Py-dlp/pydlp/core/updater.py` |
| `/mute` | moderation | literal candidate | `Videl/videl/modules/admin.py` |
| `/mybots` | clone | literal candidate | `Videl1/VidelBot/core/menus.py`, `Videl1/modules/commands/clone.py` |
| `/myplan` | premium | literal candidate | `Videl1/VidelBot/saver/premium.py` |
| `/note` | moderation | source-text clue only | `AnimeDL/cantarella/telegram/plugins/admin_cmds.py`, `AnimeDL/cantarella/telegram/plugins/commands.py`, `AnimeDL/leechbot/commands/nyaa.py` |
| `/nowplaying` | music | source-text clue only | `VYRON/tests/test_poster.py`, `VYRON/tests/test_thumbnail.py`, `VYRON/tests/test_web.py` |
| `/owner` | core | source-text clue only | `AnimeDL/cantarella/telegram/mangabridge.py`, `AnimeDL/cantarella/telegram/plugins/admin_cmds.py`, `AnimeDL/config.py` |
| `/pause` | music | literal candidate | `Videl/videl/modules/pause.py` |
| `/pin` | group | literal candidate | `Videl/videl/modules/admin.py` |
| `/ping` | builtin | literal candidate | `AnimeDL/cantarella/telegram/plugins/admin_cmds.py`, `MediaVaultBot/telegram/plugins/commands.py`, `MediaVaultBot/telegram/plugins/url_download.py` |
| `/plans` | premium | literal candidate | `Videl1/VidelBot/core/plans.py` |
| `/play` | music | source-text clue only | `AnimeDL/anime_sources/animepahe.py`, `AnimeDL/anime_sources/hostextract.py`, `JARVIS-Mark-XXXIX-Android/app/src/main/java/com/jarvis/mark39/ai/VoiceCommandRouter.kt` |
| `/playlist` | music | literal candidate | `Videl/videl/modules/playlist.py`, `Videl0/videl/modules/playlist.py` |
| `/playlistinfo` | music | no static match | Manual review needed before removal |
| `/playlists` | music | literal candidate | `Videl/videl/modules/playlist.py`, `Videl0/videl/modules/playlist.py` |
| `/playnext` | music | source-text clue only | `VYRON/vyron/modules/smartqueue.py`, `Videl0/scripts/build_webapp_commands.py`, `Videl0/videl/modules/play.py` |
| `/plugin` | ops | source-text clue only | `AnimeDL/cantarella/telegram/mangabridge.py`, `Manhua-Bot/bot.py`, `Manhua-Bot/plugins/sources_cmd.py` |
| `/plugins` | ops | source-text clue only | `AnimeDL/cantarella/telegram/mangabridge.py`, `AnimeDL/cantarella/telegram/plugins/admin_cmds.py`, `AnimeDL/leechbot/commands/__init__.py` |
| `/post` | postmaker | source-text clue only | `AnimeDL/anime_sources/allanime.py`, `AnimeDL/anime_sources/animepahe.py`, `AnimeDL/cantarella/core/anilist.py` |
| `/postpreview` | postmaker | no static match | Manual review needed before removal |
| `/posttemplate` | postmaker | no static match | Manual review needed before removal |
| `/premium` | premium | literal candidate | `AnimeDL/cantarella/telegram/plugins/usettings.py`, `MediaVaultBot/telegram/plugins/premium.py`, `MediaVaultBot/telegram/plugins/url_download.py` |
| `/premiumusers` | premium | literal candidate | `Videl1/VidelBot/filestore/worker_bot/extras.py`, `Videl1/VidelBot/saver/premium.py` |
| `/purge` | moderation | literal candidate | `Videl/videl/modules/admin.py`, `Videl1/modules/commands/admin.py` |
| `/q` | music | literal candidate | `Manhua-Bot/plugins/queue_cmd.py`, `Videl/videl/modules/smartqueue.py`, `Videl1/modules/commands/quote.py` |
| `/queue` | music | literal candidate | `AnimeDL/leechbot/commands/status.py`, `AnimeDL/leechbot/handlers.py`, `Manhua-Bot/plugins/queue_cmd.py` |
| `/remove` | music | source-text clue only | `AnimeDL/cantarella/button.py`, `AnimeDL/cantarella/telegram/ongoing.py`, `AnimeDL/cantarella/telegram/plugins/callbacks/anime.py` |
| `/rename` | renamer | literal candidate | `MediaVaultBot/telegram/plugins/rename.py`, `Videl1/VidelBot/core/tools.py` |
| `/replay` | music | source-text clue only | `VYRON/frontend/src/lib/audio.tsx`, `VYRON/tests/test_commands.py`, `VYRON/tests/test_musicapi.py` |
| `/repo` | utilities | literal candidate | `Videl/videl/modules/misc.py`, `Videl1/VidelBot/core/tools.py` |
| `/report` | reports | literal candidate | `Videl1/VidelBot/core/botlog.py` |
| `/reports` | reports | source-text clue only | `AnimeDL/anime_sources/__init__.py`, `AnimeDL/anime_sources/streamdl.py`, `AnimeDL/leechbot/debug.py` |
| `/resetplayer` | music | source-text clue only | `Videl0/scripts/build_webapp_commands.py`, `Videl0/videl/app/connections.py`, `Videl0/videl/app/music.py` |
| `/resetwarns` | group | literal candidate | `Videl/videl/modules/admin.py` |
| `/restart` | ops | literal candidate | `AnimeDL/cantarella/telegram/plugins/admin_cmds.py`, `Videl0/videl/modules/voice_admin.py`, `Videl1/VidelBot/core/admin.py` |
| `/resume` | music | literal candidate | `Videl/videl/modules/resume.py` |
| `/revoke` | linkshare | source-text clue only | `VYRON/frontend/src/App.tsx`, `VYRON/frontend/src/lib/api.ts`, `VYRON/tests/test_callbacks.py` |
| `/rules` | group | source-text clue only | `JARVIS-Mark-XXXIX-Android/app/src/main/java/com/jarvis/mark39/ui/screens/SkillCreatorScreen.kt`, `Telegram-Hosting-Bot/utils/file_manager.py`, `VYRON/frontend/src/lib/lazy-three.ts` |
| `/sample` | encoder | literal candidate | `Videl1/VidelBot/VideoEncoder/plugins/encode.py` |
| `/saveplaylist` | music | literal candidate | `Videl/videl/modules/playlist.py`, `Videl0/videl/modules/playlist.py` |
| `/screens` | encoder | literal candidate | `Videl1/VidelBot/VideoEncoder/plugins/encode.py` |
| `/setcaption` | renamer | literal candidate | `MediaVaultBot/telegram/plugins/sites_admin.py` |
| `/setlog` | ops | source-text clue only | `ultimate-waifu-bot/waifu/plugins/sudo.py` |
| `/setrules` | group | source-text clue only | `VYRON/tests/test_groupadmin.py`, `VYRON/vyron/__main__.py`, `VYRON/vyron/modules/groupadmin.py` |
| `/setthumb` | renamer | source-text clue only | `Videl1/VidelBot/VideoEncoder/plugins/thumbnail.py` |
| `/settings` | group | literal candidate | `AnimeDL/leechbot/commands/settings.py`, `AnimeDL/leechbot/handlers.py`, `Manhua-Bot/plugins/settings/main.py` |
| `/setwelcome` | welcome | literal candidate | `Videl/videl/modules/admin.py` |
| `/share` | linkshare | source-text clue only | `AnimeDL/cantarella/telegram/plugins/callbacks/anime.py`, `AnimeDL/leechbot/commands/screenshot.py`, `AnimeDL/leechbot/downloader/gdrive.py` |
| `/shuffle` | music | source-text clue only | `AnimeDL/anime_sources/megacloud.py`, `VYRON/frontend/src/App.test.tsx`, `VYRON/frontend/src/lib/audio.tsx` |
| `/skip` | music | literal candidate | `Videl/videl/modules/skip.py` |
| `/start` | builtin | literal candidate | `AnimeDL/cantarella/telegram/plugins/commands.py`, `AnimeDL/leechbot/handlers.py`, `Manhua-Bot/plugins/start.py` |
| `/status` | core | literal candidate | `AnimeDL/leechbot/commands/status.py`, `Manhua-Bot/plugins/stats_cmd.py`, `MediaVaultBot/telegram/plugins/extras.py` |
| `/stop` | music | literal candidate | `AnimeDL/mangarepo/plugins/check/cmd.py`, `Manhua-Bot/plugins/check/cmd.py`, `Videl/videl/modules/stop.py` |
| `/stopfilter` | filters | source-text clue only | `Videl0/scripts/build_webapp_commands.py`, `Videl0/videl/app/connections.py`, `Videl0/videl/plugins/notes.py` |
| `/storequota` | filestore | no static match | Manual review needed before removal |
| `/storestats` | filestore | no static match | Manual review needed before removal |
| `/sudo` | ops | source-text clue only | `AnimeDL/leechbot/downloader/mega.py`, `AnimeDL/leechbot/downloader/torrent.py`, `Summon-bot/commands_admin.py` |
| `/taskbackend` | leech | no static match | Manual review needed before removal |
| `/tasklist` | leech | no static match | Manual review needed before removal |
| `/taskstatus` | leech | no static match | Manual review needed before removal |
| `/testrename` | renamer | literal candidate | `Videl1/VidelBot/renamer/handlers.py` |
| `/time` | utilities | source-text clue only | `AnimeDL/anime_sources/__init__.py`, `AnimeDL/anime_sources/allanime.py`, `AnimeDL/anime_sources/animepahe.py` |
| `/toaudio` | encoder | literal candidate | `Videl1/VidelBot/VideoEncoder/plugins/tools.py` |
| `/trust` | moderation | source-text clue only | `Manhua-Bot/services/search_util.py`, `Manhua-Bot/services/vengine.py`, `VYRON/tests/test_working_card.py` |
| `/unban` | moderation | literal candidate | `AnimeDL/cantarella/telegram/plugins/admin_cmds.py`, `Manhua-Bot/plugins/admin.py`, `MediaVaultBot/telegram/plugins/commands.py` |
| `/unmute` | moderation | literal candidate | `Videl/videl/modules/admin.py` |
| `/unpin` | group | literal candidate | `Videl/videl/modules/admin.py` |
| `/unsetlog` | ops | no static match | Manual review needed before removal |
| `/unwarn` | moderation | literal candidate | `Videl/videl/modules/admin.py` |
| `/uptime` | core | source-text clue only | `AnimeDL/Script.py`, `AnimeDL/cantarella/telegram/plugins/admin_cmds.py`, `AnimeDL/cantarella/telegram/plugins/callbacks/admin.py` |
| `/verify` | security | literal candidate | `Videl1/VidelBot/renamer/verify.py` |
| `/viewcaption` | renamer | literal candidate | `Videl1/VidelBot/saver/caption.py` |
| `/viewthumb` | renamer | literal candidate | `Videl1/VidelBot/saver/thumbnail.py` |
| `/voicehealth` | music | literal candidate | `Videl0/videl/modules/voice_admin.py` |
| `/volume` | music | source-text clue only | `JARVIS-Mark-XXXIX-Android/app/src/main/java/com/jarvis/mark39/ai/LlmRouter.kt`, `JARVIS-Mark-XXXIX-Android/app/src/main/java/com/jarvis/mark39/ai/SystemPrompts.kt`, `JARVIS-Mark-XXXIX-Android/app/src/main/java/com/jarvis/mark39/ai/ToolRegistry.kt` |
| `/volumedown` | music | source-text clue only | `Videl0/tests/test_music_lifecycle.py`, `Videl0/videl/app/music.py`, `Videl0/videl/app/music_callbacks.py` |
| `/volumeup` | music | source-text clue only | `Videl0/tests/test_music_lifecycle.py`, `Videl0/videl/app/music.py`, `Videl0/videl/app/music_callbacks.py` |
| `/warn` | moderation | literal candidate | `Videl/videl/modules/admin.py` |
| `/warnings` | moderation | source-text clue only | `AnimeDL/leechbot/__init__.py`, `Manhua-Bot/tools/audit.py`, `Manhua-Bot/tools/extract_test.py` |
| `/warnlimit` | group | source-text clue only | `VYRON/vyron/modules/moderation.py`, `Videl0/tests/test_settings_revision.py`, `Videl1/info/warn_info.py` |
| `/warns` | moderation | literal candidate | `Videl/videl/modules/admin.py` |
| `/watchdog` | ops | literal candidate | `Videl0/videl/modules/misc.py`, `Videl1/VidelBot/core/admin.py` |
| `/welcome` | welcome | literal candidate | `Videl/videl/modules/admin.py` |

## Coverage and limits

Commands compared: 138. Source files searched: 2559.
literal candidate: 73, source-text clue only: 50, no static match: 15.
Parse/size exceptions: 5.

Exact aliases, regex registration, menus and argument-based subcommands need manual review.
Non-source documentation and generated/binary assets are not command implementations.
Do not add arbitrary shell/eval behavior just because a reference contains it.
Existing branding, isolation, encryption and safety constraints remain in force.

### Scan exceptions

- Videl1/__main__.py: parse:SyntaxError line 33
- hosting-bot/ultimate_hosting_bot_fixed.py: parse:SyntaxError line 635
- ultimate-bot/handlers/executor.py: parse:SyntaxError line 212
- ultimate-music-bot/bot/handlers/misc.py: parse:SyntaxError line 31
- ultimate-music-bot/bot/utils/formatters.py: parse:SyntaxError line 298
