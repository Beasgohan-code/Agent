"""Clone front doors do not advertise the controller or inherit its panels."""
import pytest

from agent.ui.screens import welcome_screen, help_screen, help_lookup_screen, info_screen
from agent.ui.theme import Theme
from agent.ui.workers import PROFILES, callback, plugin_screen


@pytest.mark.parametrize('slug', tuple(PROFILES))
def test_independent_worker_navigation_has_no_controller_credit(slug):
    from agent.ui.workers import commands
    from agent.modules import MODULES
    active = {c for m in MODULES for c in m.MANIFEST.commands}
    active = set(commands(slug, active)) | {'menu', 'about', 'help', 'start'}
    theme = Theme(worker_plugins=(slug,))
    screens = [welcome_screen(None, theme, active=active), help_screen(None, theme, active=active),
               plugin_screen(None, theme, slug, active=active), info_screen(None, theme, active=active),
               help_lookup_screen('plans', None, theme, active=active),
               help_lookup_screen('clones', None, theme, active=active)]
    for screen in screens:
        assert screen is not None
        text = screen.rich_text.lower()
        assert 'meiko' not in text
        assert 'about agent' not in text
        assert 'worker interface' not in text
        assert 'slot-free' not in text
        assert '/myplan' not in text
        assert '/clone' not in text
        assert '/plans' not in text
    about = callback('worker:about', None, theme, active=active)
    assert about is not None
    assert 'Meiko' not in about.rich_text
    keys = [b for row in screens[0].keyboard.inline_keyboard for b in row]
    assert any(b.callback_data == 'worker:about' for b in keys)
    for b in keys:
        assert not b.url  # No developer/support promotional links.


def test_worker_about_callback_does_not_resolve_on_controller():
    assert callback('worker:about', None, Theme(), active={'about'}) is None


def test_controller_branding_is_unchanged():
    assert 'Meiko' in welcome_screen(None, Theme()).rich_text


def test_worker_default_panels_and_ai_identity_are_task_local():
    import asyncio
    from agent.ui.identity import presentation
    from agent.ui.tables import panel
    from agent.modules.ai_agent import card

    async def render(worker):
        async def action():
            await asyncio.sleep(0)
            return str(panel('Settings')), str(card('Answer', 'Hello'))
        return await presentation(action, worker=worker)()

    async def scenario():
        clone, controller = await asyncio.gather(render(True), render(False))
        assert all('Meiko' not in text for text in clone)
        assert all('Meiko' in text for text in controller)
        assert 'Meiko' in str(panel('Settings'))
    asyncio.run(scenario())


def test_worker_rejects_real_controller_category_callbacks():
    import asyncio
    from types import SimpleNamespace
    from unittest.mock import AsyncMock
    from agent.handlers.callbacks import CallbackHandlers
    sender = SimpleNamespace(edit=AsyncMock(), send=AsyncMock())
    handler = CallbackHandlers(sender, Theme(worker_plugins=('encoder',)), active_commands=lambda: {'encode'})
    async def scenario():
        for data in ('help:clones', 'help:operations-owner', 'help:community-premium'):
            query = SimpleNamespace(data=data, from_user=None, message=object(), answer=AsyncMock())
            await handler.on_callback(None, query)
            assert query.answer.await_args.kwargs['show_alert'] is True
            sender.edit.assert_not_awaited()
    asyncio.run(scenario())


def test_actual_worker_about_and_module_reply_are_unbranded(tmp_path):
    import asyncio
    from types import SimpleNamespace
    from unittest.mock import AsyncMock
    from test_worker_command_scope import build_worker
    bot = build_worker(tmp_path, ('moderation',))
    bot.modules.sender.send = AsyncMock()
    message = SimpleNamespace(chat=SimpleNamespace(id=8), from_user=None)
    asyncio.run(bot.registry.handler_for('about')(None, message))
    screen = bot.modules.sender.send.await_args.args[1]
    assert 'About · Group Management' in screen.rich_text
    assert 'Meiko' not in screen.rich_text
    assert 'About Agent' not in screen.rich_text
