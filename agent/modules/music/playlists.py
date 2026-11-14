"""Explicit saved metadata; loading only appends after fresh playback starts."""
import html

from ...platform.music_lists import MusicPlaylists, PlaylistError
from ...ui.tables import Table, kv_table, panel
from ...utils.rich import reply
from ..moderation import is_moderator
from .queue import Track

COMMANDS = ('saveplaylist', 'playlist', 'playlists', 'deleteplaylist', 'playlistinfo')


def build_playlists(ctx, queues):
    store = MusicPlaylists(ctx.db)
    engine = ctx.voice
    gate = getattr(ctx, 'plugin_gate', None)

    async def handle(client, message):
        if not await is_moderator(client, message, owner_id=ctx.settings.owner_id):
            await reply(message, 'Only group administrators can save or load music playlists.')
            return
        name = message.text.split()[0].split('@')[0].lstrip('/').lower()
        args = message.text.split()[1:]
        chat_id, owner_id = message.chat.id, message.from_user.id
        try:
            if name == 'playlists':
                if args:
                    raise PlaylistError('Use /playlists without arguments.')
                records = await store.list(chat_id, owner_id)
                await reply(message, panel('Your saved playlists', icon=ctx.theme.emoji('music'),
                    subtitle=f"{ctx.theme.emoji('diamond')} {len(records)}/10 saved lists · up to 20 tracks each",
                    table=Table(headers=('Name', 'Tracks'), rows=tuple((row['name'], str(row['count'])) for row in records)),
                    lines=[] if records else [f"{ctx.theme.emoji('sparkles')} Your library is empty here. Use /saveplaylist name during playback."],
                    note=f"{ctx.theme.emoji('lock')} Only your lists in this group and bot. /playlistinfo name previews; /playlist name appends after fresh playback starts.",
                    footer='Saved in PostgreSQL · current playback and queue are session-only'))
                return
            if len(args) != 1:
                raise PlaylistError(f'Use /{name} <name>. Names use lowercase letters, digits, _ or -.')
            key = args[0]
            if name == 'playlistinfo':
                info = await store.inspect(chat_id, owner_id, key)
                await reply(message, panel('Playlist preview', icon=ctx.theme.emoji('eyes'),
                    subtitle=f"{ctx.theme.emoji('music')} <b>{html.escape(key)}</b> · {len(info['titles'])} tracks",
                    table=Table(headers=('#', 'Track'), rows=tuple((str(i), title) for i, title in enumerate(info['titles'], 1))),
                    note=f"{ctx.theme.emoji('lock')} Only your saved list here. Titles may contain personal text; avoid sharing this preview. No media URLs are displayed.",
                    footer='Metadata preview only · no URL checks, downloads or playback changes'))
                return
            if name == 'deleteplaylist':
                removed = await store.delete(chat_id, owner_id, key)
                await reply(message, panel('Playlist deleted' if removed else 'Playlist not found',
                    icon=ctx.theme.emoji('check' if removed else 'info'),
                    lines=['Playlist deleted.' if removed else 'No playlist with that name belongs to you here.'],
                    note='Current playback and queued tracks are unchanged.', footer='/playlists · /saveplaylist name'))
                return
            queue = queues.for_chat(chat_id)
            if name == 'saveplaylist':
                tracks = ([queue.current] if queue.current else []) + list(queue.waiting)
                count = await store.save(chat_id, owner_id, key,
                                         [{'title': track.title, 'source': track.source} for track in tracks])
                await reply(message, panel('Playlist saved', icon=ctx.theme.emoji('check'),
                    table=kv_table([('Name', key), ('Tracks', str(count)), ('Persistence', 'PostgreSQL confirmed')]),
                    lines=[f'Saved {count} tracks as <b>{html.escape(key)}</b>. This replaces your same-named playlist here.'],
                    note=f"{ctx.theme.emoji('shield')} Media URLs are stored as metadata; delete with /deleteplaylist.",
                    footer=f'/playlistinfo {html.escape(key)} · /playlists'))
                return
            if queue.current is None or engine.playback(chat_id) is None:
                raise PlaylistError('Start a fresh track with /play first. Loading a saved playlist only appends upcoming tracks; it never starts or replaces current playback.')
            tracks = await store.load(chat_id, owner_id, key)
            if gate is not None and not await gate.allowed(chat_id, 'music'):
                raise PlaylistError('Music is no longer active here. No saved tracks were queued.')
            if queue.size + len(tracks) > 50:
                raise PlaylistError('The whole playlist must fit in the 50-track queue. No tracks were added.')
            added = [Track(item['title'], item['source'], requested_by=owner_id) for item in tracks]
            queue.waiting.extend(added)  # one non-awaiting mutation after every check
            await reply(message, panel('Playlist queued', icon=ctx.theme.emoji('check'),
                lines=[f'Appended {len(added)} saved tracks. Current playback is unchanged. URLs were revalidated, not re-downloaded.'],
                note=f"{ctx.theme.emoji('music')} Queue additions last for this process session only. Loading again adds duplicates.",
                footer='/queue · /nowplaying'))
        except PlaylistError as error:
            await reply(message, panel('Check playlist action', icon=ctx.theme.emoji('info'),
                lines=[html.escape(str(error))], footer='/playlists · /help playlist'))
        except Exception:
            await reply(message, panel('Playlist result unconfirmed', icon=ctx.theme.emoji('warn'),
                lines=['Playlist result could not be confirmed. Check /queue and /playlists before retrying to avoid duplicate additions.']))

    return {command: handle for command in COMMANDS}
