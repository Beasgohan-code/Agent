"""Delete/silent warning variants with durable intent admission and no replay."""
import logging
from pyrogram.enums import ChatType, ChatMemberStatus
from ...platform.restriction_cases import begin, finish, CaseError
from ...platform.warnings import WarningStoreError
from ...utils.rich import reply
from .restrictions import target_and_reason

COMMANDS = ('dwarn', 'swarn')


class WarningInputError(ValueError):
    """Safe validation text; upstream API errors are never echoed."""



def build(ctx):
    from . import is_moderator, target_is_protected, warn_policy, escalate_warning

    def handler(command):
        async def call(client, message):
            identity = None
            try:
                user, chat = getattr(message, 'from_user', None), getattr(message, 'chat', None)
                if (getattr(chat, 'type', None) not in (ChatType.GROUP, ChatType.SUPERGROUP)
                        or type(getattr(user, 'id', None)) is not int or user.id <= 0
                        or getattr(message, 'sender_chat', None) is not None):
                    raise WarningInputError('Use your personal administrator identity in a group.')
                if not await is_moderator(client, message, need='can_restrict_members'):
                    raise WarningInputError('You need Restrict members permission.')
                replied = getattr(message, 'reply_to_message', None)
                if command == 'dwarn' and (replied is None or getattr(replied, 'from_user', None) is None):
                    raise WarningInputError('Reply to a member message with /dwarn [reason].')
                if replied is not None and getattr(getattr(replied, 'chat', None), 'id', chat.id) != chat.id:
                    raise WarningInputError('Reply to a message from this group.')
                target, reason = await target_and_reason(client, message)
                if type(target) is not int or not 0 < target < 2**63 or target == user.id:
                    raise WarningInputError('Choose another personal member identity.')
                if len(reason) > 1000:
                    raise WarningInputError('Reasons must be at most 1000 characters.')
                if await target_is_protected(client, chat.id, target):
                    raise WarningInputError('Cannot warn an administrator or an unverified target.')
                me = await client.get_me()
                if target == me.id:
                    raise WarningInputError('I cannot warn myself.')
                bot = await client.get_chat_member(chat.id, me.id)
                rights = getattr(bot, 'privileges', None)
                if bot.status not in (ChatMemberStatus.OWNER, ChatMemberStatus.ADMINISTRATOR) or not getattr(rights, 'can_restrict_members', False):
                    raise WarningInputError('I need Restrict members permission for warning escalation.')
                delete_id = getattr(replied, 'id', None) if command == 'dwarn' else None
                if command == 'dwarn':
                    if type(delete_id) is not int or delete_id <= 0:
                        raise WarningInputError('The replied message has no usable identity.')
                    if not getattr(rights, 'can_delete_messages', False) or not await is_moderator(client, message, need='can_delete_messages'):
                        raise WarningInputError('Both you and this bot need Delete messages permission.')
                if not await is_moderator(client, message, need='can_restrict_members'):
                    raise WarningInputError('Your administrator permissions changed.')
                identity = await begin(ctx, chat.id, message.id, user.id, target, command, 0, reason)
                count = await ctx.chats.aadd_warning(chat.id, target, moderator_id=user.id, reason=reason or 'no reason given')
                ctx.chats.log(chat.id, command, actor_id=user.id, target_id=target, reason=reason)
                limit, action = warn_policy(ctx.chats, chat.id)
                escalation = await escalate_warning(client, ctx, message, target, action, confirm=True) if limit and count >= limit else ''
                # Escalation reports failure in text rather than raising; never hide it.
                partial = bool(escalation and not escalation.startswith('Threshold reached:'))
                if command == 'dwarn':
                    if await client.delete_messages(chat.id, delete_id) is not True:
                        partial = True
                await finish(ctx, identity, 'partial' if partial else 'applied')
                if command == 'dwarn' or partial:
                    await reply(message, f'Warning recorded for <code>{target}</code>. Active warnings: {count}. '
                                + ('Cleanup or escalation unconfirmed. Check current state before retrying. ' if partial else '')
                                + escalation)
            except (WarningInputError, CaseError, WarningStoreError) as error:
                await reply(message, str(error))
            except Exception as error:
                logging.getLogger(__name__).warning('#Errors Warning variant unconfirmed (%s)', type(error).__name__)
                if identity is not None:
                    try:
                        await finish(ctx, identity, 'unconfirmed')
                    except CaseError:
                        logging.getLogger(__name__).warning('#Errors Warning variant audit outcome unconfirmed')
                await reply(message, 'Warning, cleanup or audit outcome unconfirmed. Inspect /warns and Telegram before retrying; no automatic retry.')
        return call
    return {name: handler(name) for name in COMMANDS}
