"""Shared command syntax. Aliases never change scope or authorization.

Telegram's published command menu remains slash-based; punctuation aliases
are recognized by the same runtime filters, including bot-username targeting.
"""

import re
from pyrogram import filters

COMMAND_PREFIXES = ("/", "!", ".", "#", "$", "%", "&", "?")
_COMMAND = re.compile(
    r"^[/!.#$%&?]([a-z][a-z0-9_]*)(?:@[a-z0-9_]+)?(?:\s|$)", re.I | re.ASCII
)


_AT_MENTION = re.compile(r"^@(all|eall)(?=\s|$)", re.I | re.ASCII)


def command_filter(commands):
    """Use the client's native parser for mentions, quoting and command args."""
    native=filters.command(commands, prefixes=list(COMMAND_PREFIXES))
    names={commands.lower()} if isinstance(commands,str) else {name.lower() for name in commands}
    aliases=names & {'all','eall'}
    if not aliases:
        return native

    async def literal_alias(_,client,message):
        text=getattr(message,'text',None)
        match=_AT_MENTION.match(text) if isinstance(text,str) else None
        if match is None or match.group(1).lower() not in aliases:
            return False
        message.command=[match.group(1).lower(),*text[match.end():].split()]
        return True

    return native | filters.create(literal_alias,'OptInMentionAlias')


def command_name(text):
    """Lexical guard for watchers/wizards, not dispatch or authorization.

    A different bot's mention is deliberately still command-shaped: passive
    features must not consume commands addressed to other bots either.
    """
    match = (_COMMAND.match(text) or _AT_MENTION.match(text)) if isinstance(text, str) else None
    return match.group(1).lower() if match else None


class ReplyTargetError(ValueError):
    """Safe reply-resolution failure; never substitute another target."""


async def replied_message(client,message):
    """Load a missing replied message once, validating the exact same-chat reply."""
    import asyncio
    source=getattr(message,'reply_to_message',None)
    chat_id=getattr(getattr(message,'chat',None),'id',None)
    reply_id=getattr(message,'reply_to_message_id',None)
    if source is not None and not getattr(source,'empty',False):
        if getattr(getattr(source,'chat',None),'id',chat_id)!=chat_id:
            raise ReplyTargetError('Reply to a message in this chat, not an external message.')
        return source
    if reply_id is None:
        if source is not None:
            raise ReplyTargetError('The replied message is unavailable. Reply to the member again.')
        return None
    message_id=getattr(message,'id',None)
    if (type(reply_id) is not int or reply_id<=0 or type(message_id) is not int or message_id<=0
            or type(chat_id) is not int):
        raise ReplyTargetError('The replied message reference is invalid. Reply to the member again.')
    if getattr(message,'topic_message',False) and reply_id==getattr(message,'message_thread_id',None):
        raise ReplyTargetError('Reply to a member message, not the forum topic header.')
    try:
        source=await asyncio.wait_for(client.get_messages(chat_id,reply_to_message_ids=message_id,replies=0),5)
    except Exception:
        raise ReplyTargetError('Could not load the replied message. Reply again or use an explicit member ID.') from None
    if (source is None or getattr(source,'empty',False) or getattr(source,'id',None)!=reply_id
            or getattr(getattr(source,'chat',None),'id',None)!=chat_id):
        raise ReplyTargetError('The replied message is missing or belongs to another chat. No target selected.')
    message.reply_to_message=source
    return source
