"""Obtain the current bot identity for its own group-add URL."""
import asyncio
import logging
import re


async def bot_username(client):
    name = getattr(getattr(client, 'me', None), 'username', None)
    if not isinstance(name, str):
        try:
            name = getattr(await asyncio.wait_for(client.get_me(), timeout=5), 'username', None)
        except Exception as error:
            logging.getLogger(__name__).warning('#Errors Welcome identity unavailable (%s)', type(error).__name__)
            return None
    return name if isinstance(name, str) and re.fullmatch(r'[A-Za-z0-9_]{5,32}', name) else None
