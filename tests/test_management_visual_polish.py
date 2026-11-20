import asyncio
from unittest.mock import AsyncMock

from pyrogram.enums import ButtonStyle
from agent.modules.group.controls import keyboard


def test_management_overview_buttons_are_accented(tmp_path):
    from test_group_controls import context
    ctx = context(tmp_path)
    for row in keyboard(ctx).inline_keyboard:
        assert len(row) <= 2
        for button in row:
            assert button.icon_custom_emoji_id
            assert button.style is not None
    ctx.theme.disable_custom_emoji()
    assert all(b.icon_custom_emoji_id is None for row in keyboard(ctx).inline_keyboard for b in row)


def test_runtime_confirmation_is_danger_and_does_not_mutate(tmp_path):
    from test_plugin_panel import make_bot, FakeQuery, buttons
    async def scenario():
        bot = make_bot(tmp_path)
        before = bot.registry.is_enabled('leech')
        query = FakeQuery('plugin:ask:leech')
        await bot.actions.dispatch(None, query)
        controls = buttons(query.edits[-1][1])
        assert controls[0].callback_data == 'plugin:off:leech'
        assert controls[0].style == ButtonStyle.DANGER
        assert controls[1].style != ButtonStyle.DANGER
        assert all(b.icon_custom_emoji_id for b in controls)
        assert bot.registry.is_enabled('leech') == before
    asyncio.run(scenario())


def test_group_protection_switches_show_direction_without_claiming_success(tmp_path, monkeypatch):
    from test_group_controls import context, query, fixtures
    from agent.modules import group
    async def scenario():
        ctx = context(tmp_path)
        editor = AsyncMock()
        monkeypatch.setattr('agent.modules.group.controls.edit', editor)
        group.build(ctx)
        await ctx.actions.dispatch(fixtures.FakeClient(), query('gmanage:protection:show'))
        controls = [b for row in editor.await_args.kwargs['reply_markup'].inline_keyboard for b in row]
        for button in controls:
            assert button.icon_custom_emoji_id
            if button.callback_data.endswith(':off'):
                assert button.style == ButtonStyle.DANGER
            elif button.callback_data.endswith(':on'):
                assert button.style == ButtonStyle.PRIMARY
    asyncio.run(scenario())


def test_all_management_subpanels_keep_styled_navigation(tmp_path, monkeypatch):
    from test_group_controls import context, query, fixtures
    from agent.modules import group
    async def scenario():
        ctx = context(tmp_path)
        editor = AsyncMock()
        monkeypatch.setattr('agent.modules.group.controls.edit', editor)
        group.build(ctx)
        for section in ('home', 'rules', 'blocklist', 'welcome', 'goodbye', 'protection'):
            editor.reset_mock()
            await ctx.actions.dispatch(fixtures.FakeClient(), query(f'gmanage:{section}:show'))
            assert editor.await_count == 1
            keyboard = editor.await_args.kwargs['reply_markup']
            for row in keyboard.inline_keyboard:
                assert len(row) <= 2
                for button in row:
                    assert button.icon_custom_emoji_id
                    assert '<tg-emoji' not in button.text
                    assert len(button.callback_data.encode()) <= 64
    asyncio.run(scenario())


def test_runtime_locked_buttons_stay_disabled(tmp_path):
    from test_plugin_panel import make_bot, FakeMessage, buttons
    async def scenario():
        bot = make_bot(tmp_path)
        message = FakeMessage('/plugins')
        await bot.registry.handler_for('plugins')(None, message)
        locked = [b for b in buttons(message.markup) if b.callback_data == 'plugin:info:group']
        assert len(locked) == 1
        assert locked[0].disabled
        assert locked[0].icon_custom_emoji_id == bot.theme.emoji_id('lock')
    asyncio.run(scenario())
