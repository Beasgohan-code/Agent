"""Original adaptation of Saver's words workflow into existing media tools."""
import html

from ...platform.media_rules import DELETE_KEY, REPLACE_KEY, MAX_RULES, MAX_WORD
from ...ui.tables import kv_table, panel
from ...utils.rich import reply
from ..moderation import is_moderator

COMMANDS = ('set_del_word', 'rem_del_word', 'set_repl_word', 'rem_repl_word')


def build_rules(ctx):
    async def handle(client, message):
        user = getattr(getattr(message, 'from_user', None), 'id', None)
        if type(user) is not int or user <= 0:
            await reply(message, 'Use your personal Telegram user identity for media rules.')
            return
        chat_id = message.chat.id
        if chat_id < 0 and not await is_moderator(client, message, owner_id=ctx.settings.owner_id):
            await reply(message, 'Only group administrators can change shared media rules.')
            return
        chats = getattr(ctx, 'chats', None)
        db = getattr(ctx, 'db', None)
        if chats is None or (db is not None and not db.connected):
            await reply(message, 'Per-chat storage is unavailable. No media rules changed.')
            return
        parts = (getattr(message, 'text', '') or '').split()
        name, args = parts[0].split('@')[0].lstrip('/!.?').lower(), parts[1:]
        try:
            if not args or len(args) > MAX_RULES or any(len(arg) > MAX_WORD for arg in args):
                raise ValueError(f'Use /{name} with 1–{MAX_RULES} words, at most {MAX_WORD} characters each.')
            if name in ('set_del_word', 'rem_del_word'):
                current = chats.get(chat_id, DELETE_KEY, [])
                current = list(current) if isinstance(current, list) else []
                updated = list(dict.fromkeys(current + args)) if name == 'set_del_word' else [word for word in current if word not in args]
                if len(updated) > MAX_RULES:
                    raise ValueError(f'At most {MAX_RULES} delete words are allowed. Remove some first.')
                key = DELETE_KEY
            else:
                if len(args) != (2 if name == 'set_repl_word' else 1):
                    raise ValueError(f'Use /{name} target' + (' replacement.' if name == 'set_repl_word' else '.'))
                current = chats.get(chat_id, REPLACE_KEY, {})
                updated = dict(current) if isinstance(current, dict) else {}
                if name == 'set_repl_word':
                    updated[args[0]] = args[1]
                else:
                    updated.pop(args[0], None)
                if len(updated) > MAX_RULES:
                    raise ValueError(f'At most {MAX_RULES} replacements are allowed. Remove some first.')
                key = REPLACE_KEY
            try:
                chats.put(chat_id, key, updated)
                if db is not None and await db.flush() <= 0:
                    raise RuntimeError('Media rule persistence unconfirmed')
            except Exception:
                await reply(message, 'Media rule persistence was not confirmed. The current view may be cached; retry when storage is available.')
                return
            await reply(message, panel('Media rules updated', icon=ctx.theme.emoji('check'),
                table=kv_table([('Rule type', 'Delete words' if key == DELETE_KEY else 'Replacements'),
                                ('Active rules', str(len(updated))), ('Scope', 'This chat only')]),
                note='Literal, case-sensitive matches; no regex. Applies to rename output and caption filename fields. Stored originals are unchanged.',
                footer='/testrename · /viewcaption'))
        except ValueError as error:
            await reply(message, html.escape(str(error)))
    return {name: handle for name in COMMANDS}
