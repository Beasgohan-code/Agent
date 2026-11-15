"""Live group panel: authority is the presser, not the bot message author."""
import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

from agent.modules.group.plugin_panel import build
from agent.platform.actions import ActionRouter
from agent.platform.plugin_access import AccessError


def setup():
    service = SimpleNamespace(
        _admin=AsyncMock(return_value=(-100, 22)), _slug=lambda slug: None,
        status=AsyncMock(return_value=[{'slug': 'music', 'approved': True, 'active': False}]),
        activate=AsyncMock(), deactivate=AsyncMock(),
    )
    ctx = SimpleNamespace(plugin_access=service, actions=ActionRouter(),
                          runtime=SimpleNamespace(state=lambda: [{
                              'slug': 'music', 'enabled': True, 'commands': ['play'], 'scope': 'group'}]))
    show = build(ctx)
    return ctx, service, show


def query(data):
    return SimpleNamespace(data=data, from_user=SimpleNamespace(id=22), answer=AsyncMock(),
                           message=SimpleNamespace(chat=SimpleNamespace(id=-100),
                                                   from_user=SimpleNamespace(id=999)))


def test_callback_refuses_unauthorized_presser_before_reading_state():
    async def scenario():
        ctx, service, _ = setup()
        service._admin.side_effect = AccessError('permission required')
        press = query('gplug:on:music:0')
        await ctx.actions.dispatch(None, press)
        service.activate.assert_not_awaited()
        service.status.assert_not_awaited()
        assert press.answer.await_args.kwargs['show_alert']
    asyncio.run(scenario())


def test_activation_passes_presser_not_bot_author(monkeypatch):
    async def scenario():
        monkeypatch.setattr('agent.modules.group.plugin_panel.edit', AsyncMock())
        ctx, service, _ = setup()
        press = query('gplug:on:music:0')
        await ctx.actions.dispatch(None, press)
        request = service.activate.await_args.args[1]
        assert request.from_user.id == 22
        assert request.chat.id == -100
    asyncio.run(scenario())


def test_disable_requires_confirmation_screen_before_mutation(monkeypatch):
    async def scenario():
        editor = AsyncMock()
        monkeypatch.setattr('agent.modules.group.plugin_panel.edit', editor)
        ctx, service, _ = setup()
        await ctx.actions.dispatch(None, query('gplug:ask:music:0'))
        service.deactivate.assert_not_awaited()
        keyboard = editor.await_args.kwargs['reply_markup']
        assert keyboard.inline_keyboard[0][0].callback_data == 'gplug:off:music:0'
    asyncio.run(scenario())


def test_group_panel_displays_real_available_slots(monkeypatch):
    async def scenario():
        sender = AsyncMock()
        monkeypatch.setattr('agent.modules.group.plugin_panel.reply', sender)
        ctx, service, show = setup()
        await show(None, SimpleNamespace())
        assert '3 / 3 slots available' in str(sender.await_args.args[1])
        keyboard = sender.await_args.kwargs['reply_markup']
        assert keyboard.inline_keyboard[0][0].callback_data == 'gplug:on:music:0'
    asyncio.run(scenario())


def test_private_only_plugin_not_offered_for_group_activation(monkeypatch):
    async def scenario():
        sender = AsyncMock()
        monkeypatch.setattr('agent.modules.group.plugin_panel.reply', sender)
        ctx, service, show = setup()
        ctx.runtime.state = lambda: [{'slug': 'music', 'enabled': True, 'commands': ['play'], 'scope': 'private'}]
        await show(None, SimpleNamespace())
        markup = sender.await_args.kwargs['reply_markup']
        assert all('gplug:on' not in b.callback_data for row in markup.inline_keyboard for b in row)
    asyncio.run(scenario())


def test_unapproved_inactive_tools_do_not_clutter_panel(monkeypatch):
    async def scenario():
        sender = AsyncMock()
        monkeypatch.setattr('agent.modules.group.plugin_panel.reply', sender)
        ctx, service, show = setup()
        service.status.return_value = [{'slug': 'music', 'approved': False, 'active': False}]
        await show(None, SimpleNamespace())
        body = str(sender.await_args.args[1])
        assert 'Group Management' in body
        assert 'No optional plugins approved yet' in body
        keyboard = sender.await_args.kwargs['reply_markup']
        assert not any('music' in (b.callback_data or '') for row in keyboard.inline_keyboard for b in row)
    asyncio.run(scenario())
