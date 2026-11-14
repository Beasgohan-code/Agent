"""Explicit saved metadata; loading only appends after fresh playback starts."""
import html

from ...platform.music_lists import MusicPlaylists, PlaylistError
from ...ui.tables import Table, panel
from ...utils.rich import reply
from ..moderation import is_moderator
from .queue import Track

COMMANDS = ('saveplaylist', 'playlist', 'playlists', 'deleteplaylist')


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
                    table=Table(headers=('Name', 'Tracks'), rows=tuple((row['name'], str(row['count'])) for row in records)),
                    note='Only your lists in this group and bot. /playlist name appends after fresh playback starts.'))
                return
            if len(args) != 1:
                raise PlaylistError(f'Use /{name} <name>. Names use lowercase letters, digits, _ or -.')
            key = args[0]
            if name == 'deleteplaylist':
                removed = await store.delete(chat_id, owner_id, key)
                await reply(message, 'Playlist deleted.' if removed else 'No playlist with that name belongs to you here.')
                return
            queue = queues.for_chat(chat_id)
            if name == 'saveplaylist':
                tracks = ([queue.current] if queue.current else []) + list(queue.waiting)
                count = await store.save(chat_id, owner_id, key,
                                         [{'title': track.title, 'source': track.source} for track in tracks])
                await reply(message, f'Saved {count} tracks as <b>{html.escape(key)}</b>. This replaces your same-named playlist here. Media URLs are stored as metadata; delete with /deleteplaylist.')
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
            await reply(message, f'Appended {len(added)} saved tracks. Current playback is unchanged. URLs were revalidated, not re-downloaded.')
        except PlaylistError as error:
            await reply(message, html.escape(str(error)))
        except Exception:
            await reply(message, 'Playlist result could not be confirmed. Check /queue and /playlists before retrying to avoid duplicate additions.')

    return {command: handle for command in COMMANDS}
