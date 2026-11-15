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


def test_empty_approval_panel_explains_runtime_vs_approval_with_next_steps(monkeypatch):
    async def scenario():
        sender = AsyncMock()
        monkeypatch.setattr('agent.modules.group.plugin_panel.reply', sender)
        ctx, service, show = setup()
        service.status.return_value = [{'slug':'music','approved':False,'active':False}]
        await show(None,SimpleNamespace())
        body = str(sender.await_args.args[1])
        assert 'Runtime on ≠ Owner approval ≠ group activation' in body
        assert '/plugin music approve' in body
        assert 'Activate' in body
        assert not any('gplug:on' in (b.callback_data or '') for row in sender.await_args.kwargs['reply_markup'].inline_keyboard for b in row)
    asyncio.run(scenario())


def test_active_plugin_does_not_claim_usable_when_runtime_off(monkeypatch):
    async def scenario():
        sender = AsyncMock()
        monkeypatch.setattr('agent.modules.group.plugin_panel.reply', sender)
        ctx, service, show = setup()
        service.status.return_value = [{'slug':'music','approved':True,'active':True}]
        ctx.runtime.state = lambda: [{'slug':'music','enabled':False,'commands':['play'],'scope':'group'}]
        await show(None,SimpleNamespace())
        body = str(sender.await_args.args[1])
        assert 'runtime unavailable' in body.lower()
        assert '2 / 3 slots available' in body
    asyncio.run(scenario())


def test_plugin_workspace_reads_live_state_without_mutation_and_refreshes_safely(monkeypatch):
    from pyrogram.errors import MessageNotModified
    async def scenario():
        editor = AsyncMock()
        monkeypatch.setattr('agent.modules.group.plugin_panel.edit', editor)
        ctx, service, _ = setup()
        press = query('gplug:info:music:0')
        await ctx.actions.dispatch(None, press)
        body = str(editor.await_args.args[1])
        assert 'Music · Plugin workspace' in body
        assert 'registered and enabled' in body and 'not activated' in body
        assert '/play' in body and 'not proof of live' in body
        data = [b.callback_data for row in editor.await_args.kwargs['reply_markup'].inline_keyboard for b in row]
        assert 'gplug:on:music:0' in data and 'gplug:page:0' in data
        service.activate.assert_not_awaited(); service.deactivate.assert_not_awaited()
        editor.side_effect = MessageNotModified()
        press.answer.reset_mock()
        await ctx.actions.dispatch(None, press)
        press.answer.assert_awaited_once_with()
        service.status.return_value = [{'slug':'music','approved':False,'active':False}]
        await ctx.actions.dispatch(None, press)
        assert 'not approved' in press.answer.await_args.args[0]
    asyncio.run(scenario())


def test_workspace_keeps_disable_available_when_runtime_down_and_blocks_activation(monkeypatch):
    async def scenario():
        editor = AsyncMock()
        monkeypatch.setattr('agent.modules.group.plugin_panel.edit', editor)
        ctx, service, _ = setup()
        service.status.return_value = [{'slug':'music','approved':False,'active':True}]
        ctx.runtime.state = lambda: [{'slug':'music','enabled':False,'commands':[],'scope':'group'}]
        await ctx.actions.dispatch(None, query('gplug:info:music:0'))
        body = str(editor.await_args.args[1])
        assert 'revoked' in body and 'unavailable or disabled' in body
        data = [b.callback_data for row in editor.await_args.kwargs['reply_markup'].inline_keyboard for b in row]
        assert 'gplug:ask:music:0' in data
        assert not any(':on:' in entry for entry in data)
    asyncio.run(scenario())
