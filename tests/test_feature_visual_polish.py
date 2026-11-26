import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

from pyrogram.enums import ButtonStyle
from agent.ui.theme import Theme


def test_leech_navigation_has_native_accents(tmp_path):
    from test_plugins import make_ctx
    from agent.modules.leech.home import screen
    ctx = make_ctx(tmp_path)
    for view in ('home', 'help', 'uploads', 'backends'):
        body, keyboard = screen(ctx, view, user_id=8)
        assert '<h2>' in body
        for row in keyboard.inline_keyboard:
            for button in row:
                assert button.icon_custom_emoji_id
                assert button.style is not None
        assert keyboard.inline_keyboard[0][0].callback_data == 'leech:help'


def test_group_disable_button_is_danger_and_cancel_is_safe(monkeypatch):
    from test_group_plugin_panel import setup, query
    from agent.modules.group import plugin_panel
    async def scenario():
        editor = AsyncMock()
        monkeypatch.setattr(plugin_panel, 'edit', editor)
        ctx, service, _ = setup()
        await ctx.actions.dispatch(None, query('gplug:ask:music:0'))
        buttons = [b for row in editor.await_args.kwargs['reply_markup'].inline_keyboard for b in row]
        assert buttons[0].style == ButtonStyle.DANGER
        assert buttons[1].style != ButtonStyle.DANGER
        assert all(b.icon_custom_emoji_id for b in buttons)
        service.deactivate.assert_not_awaited()
    asyncio.run(scenario())


def test_theme_button_supports_copy_without_changing_action():
    button = Theme().button('Copy link', icon='link', copy_text='https://t.me/example?start=opaque', style=ButtonStyle.SUCCESS)
    assert button.copy_text.text == 'https://t.me/example?start=opaque'
    assert button.callback_data is None
    assert button.icon_custom_emoji_id


def test_feature_rich_reply_retries_rejected_button_only():
    from agent.utils.rich import reply
    from pyrogram.types import InlineKeyboardMarkup
    button = Theme().button('Help', icon='question', callback_data='leech:help')
    keyboard = InlineKeyboardMarkup([[button]])
    calls = []
    async def respond(*args, **kwargs):
        calls.append(kwargs)
        if kwargs['reply_markup'].inline_keyboard[0][0].icon_custom_emoji_id:
            raise RuntimeError('CUSTOM_EMOJI_INVALID')
        return 'delivered'
    message = SimpleNamespace(reply=respond)
    assert asyncio.run(reply(message, 'Help', reply_markup=keyboard)) == 'delivered'
    assert len(calls) == 2
    assert button.icon_custom_emoji_id
    assert calls[-1]['reply_markup'].inline_keyboard[0][0].callback_data == 'leech:help'


def test_legacy_revoke_card_keeps_copy_revoke_and_home_actions(tmp_path, monkeypatch):
    from test_plugins import make_ctx
    from agent.modules import linkshare
    from agent.platform.actions import ActionRouter
    async def scenario():
        ctx = make_ctx(tmp_path)
        ctx.actions = ActionRouter()
        stored = ctx.storage.save_bytes(8, 'example.txt', b'test')
        record = ctx.links.create(stored.id, 8)
        capture = AsyncMock()
        monkeypatch.setattr(linkshare.rich_ui, 'edit', capture)
        linkshare.build(ctx)
        query = SimpleNamespace(data=f'link:revoke:{record.token}', from_user=SimpleNamespace(id=8), answer=AsyncMock())
        client = SimpleNamespace(me=SimpleNamespace(username='example_bot'))
        await ctx.actions.dispatch(client, query)
        keyboard = capture.await_args.kwargs['reply_markup']
        buttons = [b for row in keyboard.inline_keyboard for b in row]
        assert all(b.icon_custom_emoji_id for b in buttons)
        assert buttons[0].copy_text.text.startswith('https://t.me/example_bot?start=link_')
        assert buttons[1].style == ButtonStyle.DANGER
        assert ':revoke:' in buttons[1].callback_data
        assert buttons[2].callback_data == 'menu:home'
        assert ctx.links.get(record.token).revoked
    asyncio.run(scenario())


def test_feature_transport_timeout_never_retries():
    from agent.utils.rich import reply
    from pyrogram.types import InlineKeyboardMarkup
    keyboard = InlineKeyboardMarkup([[Theme().button('Help', icon='question', callback_data='leech:help')]])
    responder = AsyncMock(side_effect=TimeoutError('unconfirmed'))
    import pytest
    with pytest.raises(TimeoutError):
        asyncio.run(reply(SimpleNamespace(reply=responder), 'Help', reply_markup=keyboard))
    assert responder.await_count == 1
