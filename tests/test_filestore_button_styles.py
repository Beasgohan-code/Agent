"""FileStore uses actual styled inline keyboard actions, not text markup."""
from types import SimpleNamespace as NS
from unittest.mock import AsyncMock, patch
import pytest
from pyrogram.enums import ButtonStyle
from agent.modules.filestore.channel_links import build
from agent.ui.theme import Theme
from test_archive_links import context, request, client


@pytest.mark.asyncio
async def test_file_actions_have_native_styles_and_same_destination():
    value = context(NS(connected=True, _pool=object()))
    value.theme = Theme(custom_emoji={})
    item = request()
    with patch('agent.modules.filestore.channel_links.create', AsyncMock(return_value='safe_token')):
        await build(value)['custom_batch'](client(), item)
    buttons = [b for row in item.reply.await_args.kwargs['reply_markup'].inline_keyboard for b in row]
    assert [b.style for b in buttons] == [ButtonStyle.SUCCESS, ButtonStyle.PRIMARY, ButtonStyle.DEFAULT]
    assert buttons[0].url.endswith('?start=archive_safe_token')
    assert buttons[2].copy_text.text == buttons[0].url


def test_theme_url_button_preserves_native_url_and_icon_fallback():
    button = Theme(custom_emoji={}).button('Open file', icon='link', url='https://t.me/examplebot?start=x', style=ButtonStyle.SUCCESS)
    assert button.url == 'https://t.me/examplebot?start=x'
    assert button.callback_data is None and button.style == ButtonStyle.SUCCESS
    assert 'Open file' in button.text
