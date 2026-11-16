"""Warning-removal commands with shared target parsing and awaited storage."""
import logging
from pyrogram.enums import ChatType
from ...platform.warnings import WarningStoreError
from ...utils.rich import reply
from .restrictions import target_and_reason

COMMANDS = ('rmwarn', 'resetwarn')


def build(ctx):
    from . import is_moderator, target_is_protected

    def handler(command):
        async def call(client, message):
            user, chat = getattr(message, 'from_user', None), getattr(message, 'chat', None)
            if (getattr(chat, 'type', None) not in (ChatType.GROUP, ChatType.SUPERGROUP)
                    or type(getattr(user, 'id', None)) is not int or user.id <= 0
                    or getattr(message, 'sender_chat', None) is not None):
                await reply(message, 'Use your personal identity inside a group.')
                return
            if not await is_moderator(client, message, need='can_restrict_members'):
                await reply(message, 'You need Restrict members permission to clear warnings.')
                return
            try:
                replied = getattr(message, 'reply_to_message', None)
                reply_chat = getattr(getattr(replied, 'chat', None), 'id', chat.id)
                if reply_chat != chat.id:
                    raise ValueError('Reply to a message from this group.')
                target, extra = await target_and_reason(client, message)
                if type(target) is not int or not 0 < target < 2**63 or extra:
                    raise ValueError(f'Usage: /{command} @username or positive ID, or reply without arguments.')
                if await target_is_protected(client, chat.id, target):
                    raise ValueError('Cannot act on an administrator or unverified target.')
                # Recheck current authority after target lookup, immediately before mutation.
                if not await is_moderator(client, message, need='can_restrict_members'):
                    raise ValueError('Administrator permissions changed. No warnings cleared.')
                cleared = (await ctx.chats.aclear_warning(chat.id, target) if command == 'rmwarn'
                           else await ctx.chats.aclear_all_warnings(chat.id, target))
                ctx.chats.log(chat.id, command, actor_id=user.id, target_id=target, reason=f'{int(cleared)} cleared')
            except (ValueError, WarningStoreError) as error:
                await reply(message, str(error))
                return
            except Exception as error:
                logging.getLogger(__name__).warning('#Errors Warning removal unconfirmed (%s)', type(error).__name__)
                await reply(message, 'Warning removal unconfirmed. Check /warns before retrying.')
                return
            await reply(message, f'Warnings cleared: {int(cleared)} for member <code>{target}</code>. History retained. No Telegram ban or mute was changed.')
        return call
    return {command: handler(command) for command in COMMANDS}
