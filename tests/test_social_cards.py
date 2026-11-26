"""Social cards are validated links, not fabricated live profile lookups."""
from types import SimpleNamespace as NS
from unittest.mock import AsyncMock
import pytest
from pyrogram.enums import ButtonStyle
from agent.modules import utilities
from agent.ui.theme import Theme


@pytest.mark.asyncio
@pytest.mark.parametrize('command,name,url', [
    ('tiktok','@some.user','https://www.tiktok.com/@some.user'),
    ('x','some_user','https://x.com/some_user'),
    ('yt','@some-channel','https://www.youtube.com/@some-channel'),
    ('ig','some.user','https://www.instagram.com/some.user/'),
])
async def test_card_uses_real_platform_destination(command, name, url):
    value = NS(theme=Theme(custom_emoji={}))
    manifest, handlers = utilities.build(value)
    assert command in manifest.commands
    message = NS(text=f'#{command}@MeikoBot {name}', reply=AsyncMock())
    await handlers[command](None, message)
    text = str(message.reply.await_args.args[0])
    assert 'not verified' in text.lower() and 'live' in text.lower()
    button = message.reply.await_args.kwargs['reply_markup'].inline_keyboard[0][0]
    assert button.url == url and button.style == ButtonStyle.PRIMARY


@pytest.mark.asyncio
@pytest.mark.parametrize('text', ['/x', '/x https://evil.test', '/ig a/b', '/tiktok user?x=1', '/yt @bad<name>', '/x user other', '/ig '+ 'x'*31, '/yt @@example', '/x username.withdot'])
async def test_invalid_handle_never_builds_link(text):
    message = NS(text=text, reply=AsyncMock())
    handler = utilities.build(NS(theme=Theme(custom_emoji={})))[1][text.split()[0][1:]]
    await handler(None, message)
    assert 'Usage' in str(message.reply.await_args.args[0])
    assert 'reply_markup' not in message.reply.await_args.kwargs
