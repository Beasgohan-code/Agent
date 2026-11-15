"""Shared command syntax. Aliases never change scope or authorization.

Telegram's published command menu remains slash-based; punctuation aliases
are recognized by the same runtime filters, including bot-username targeting.
"""

import re
from pyrogram import filters

COMMAND_PREFIXES = ("/", "!", ".", "?")
_COMMAND = re.compile(
    r"^[/!.?]([a-z][a-z0-9_]*)(?:@[a-z0-9_]+)?(?:\s|$)", re.I | re.ASCII
)


def command_filter(commands):
    """Use the client's native parser for mentions, quoting and command args."""
    return filters.command(commands, prefixes=list(COMMAND_PREFIXES))


def command_name(text):
    """Lexical guard for watchers/wizards, not dispatch or authorization.

    A different bot's mention is deliberately still command-shaped: passive
    features must not consume commands addressed to other bots either.
    """
    match = _COMMAND.match(text) if isinstance(text, str) else None
    return match.group(1).lower() if match else None
