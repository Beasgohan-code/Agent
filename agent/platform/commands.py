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
