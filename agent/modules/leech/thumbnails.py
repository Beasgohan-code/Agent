"""Saver thumbnail workflow adapted to Meiko's existing attachment storage.

Source: abhinai2244/save-restricted-content-bot cantarella/thumbnail.py,
revision bf2e45a1ef187060e053e59c0336cb0e6a4a022b.
Copyright (c) 2026 LastPerson07; MIT notice: licenses/saver-MIT.txt.
"""
from ...platform.attachments import THUMB_KEY
from ...utils.rich import reply
from ..filestore.channel_links import private


def build(ctx):
    async def handle(client, message):
        if not private(message):
            await reply(message, 'Manage personal thumbnails in private chat with your personal Telegram account.')
            return
        chats, db = getattr(ctx, 'chats', None), getattr(ctx, 'db', None)
        if chats is None or (db is not None and not db.connected):
            await reply(message, 'Thumbnail storage is unavailable. No change confirmed.')
            return
        command = message.text.split()[0].split('@')[0].lstrip('/!.?').lower()
        uid = message.from_user.id
        current = chats.get(uid, THUMB_KEY)
        if command in ('view_thumb', 'see_thumb'):
            if not current:
                await reply(message, 'No personal thumbnail set. Reply to a photo with /set_thumb.')
                return
            try:
                await client.send_photo(uid, current, caption='Your personal upload thumbnail.')
            except Exception:
                await reply(message, 'Telegram could not display the saved thumbnail. Set a new photo with /set_thumb.')
            return
        if command == 'set_thumb':
            source = getattr(message, 'reply_to_message', None)
            photo = getattr(source, 'photo', None)
            value = getattr(photo, 'file_id', None)
            if not isinstance(value, str) or not value:
                await reply(message, 'Reply to a Telegram photo with /set_thumb.')
                return
        else:
            if not current:
                await reply(message, 'No personal thumbnail is set.')
                return
            value = None
        try:
            chats.put(uid, THUMB_KEY, value)
            if db is not None and await db.flush() <= 0:
                raise RuntimeError('Unconfirmed persistence')
        except Exception:
            await reply(message, 'Thumbnail persistence was not confirmed. The current view may be cached; retry when storage is available.')
            return
        await reply(message, 'Personal thumbnail saved for uploads in this private chat.' if value else 'Personal thumbnail removed.')

    return {name: handle for name in ('set_thumb', 'view_thumb', 'see_thumb', 'del_thumb', 'delete_thumb')}
