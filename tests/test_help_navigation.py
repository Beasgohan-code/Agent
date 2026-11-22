"""Mobile pagination and confirmed-only navigation retries."""

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from agent.handlers.callbacks import CallbackHandlers
from agent.ui import tables
from agent.ui.screens import HELP_SECTIONS, HELP_PAGE_SIZE, SCREENS, help_section_screen
from agent.ui.theme import Theme
from agent.utils.sender import ScreenSender


def test_every_command_remains_reachable_once_across_pages():
    for _, title, commands in HELP_SECTIONS:
        pages = max(1, (len(commands) + HELP_PAGE_SIZE - 1) // HELP_PAGE_SIZE)
        seen = []
        for page in range(pages):
            screen = help_section_screen(title, None, Theme(), page=page)
            seen += [button.callback_data.removeprefix('help:command:')
                     for row in screen.keyboard.inline_keyboard for button in row
                     if button.callback_data.startswith('help:command:')]
            for row in screen.keyboard.inline_keyboard:
                for button in row:
                    assert button.callback_data in SCREENS
                    assert len(button.callback_data.encode()) <= 64
        assert seen == list(commands)


def test_stale_page_clamps_to_available_commands():
    screen = help_section_screen(
        "Music (voice chat)", None, Theme(), active={"play"}, page=999
    )
    assert "/play" in screen.rich_text
    assert "Page 1 of 1" in screen.rich_text


@pytest.mark.parametrize(
    "error",
    [
        TimeoutError(),
        RuntimeError("FLOOD_WAIT_10"),
        RuntimeError("CHAT_WRITE_FORBIDDEN"),
    ],
)
def test_navigation_does_not_resend_after_unconfirmed_edit(error):
    async def scenario():
        tables.set_rich(True)
        client = SimpleNamespace(
            send_rich_message=AsyncMock(), send_message=AsyncMock()
        )
        sender = ScreenSender(client, Theme())
        query = SimpleNamespace(
            data="menu:help",
            from_user=None,
            message=SimpleNamespace(chat=SimpleNamespace(id=1)),
            answer=AsyncMock(),
            edit_message_text=AsyncMock(side_effect=error),
            _client=client,
        )
        await CallbackHandlers(sender, Theme()).on_callback(client, query)
        client.send_message.assert_not_awaited()
        client.send_rich_message.assert_not_awaited()
        assert query.edit_message_text.await_count == 1

    asyncio.run(scenario())


def test_uneditable_message_can_send_replacement():
    async def scenario():
        tables.set_rich(True)
        client = SimpleNamespace(
            send_rich_message=AsyncMock(), send_message=AsyncMock()
        )
        query = SimpleNamespace(
            data="menu:help",
            from_user=None,
            message=SimpleNamespace(chat=SimpleNamespace(id=1)),
            answer=AsyncMock(),
            edit_message_text=AsyncMock(side_effect=RuntimeError("MESSAGE_ID_INVALID")),
            _client=client,
        )
        await CallbackHandlers(ScreenSender(client, Theme()), Theme()).on_callback(
            client, query
        )
        client.send_rich_message.assert_awaited_once()

    asyncio.run(scenario())


def test_ephemeral_replacement_keeps_recipient_and_rejects_foreign_press():
    async def scenario():
        client=SimpleNamespace()
        sender=SimpleNamespace(edit=AsyncMock(return_value=False),send=AsyncMock())
        message=SimpleNamespace(chat=SimpleNamespace(id=-100),receiver_user=SimpleNamespace(id=22),ephemeral_message_id=7)
        query=SimpleNamespace(data='menu:help',from_user=SimpleNamespace(id=22),message=message,answer=AsyncMock())
        handler=CallbackHandlers(sender,Theme())
        await handler.on_callback(client,query)
        assert sender.send.await_args.kwargs['receiver_user_id']==22
        sender.send.reset_mock()
        sender.edit.reset_mock()
        query.from_user.id=33
        await handler.on_callback(client,query)
        sender.edit.assert_not_awaited()
        sender.send.assert_not_awaited()
    asyncio.run(scenario())


def test_help_overview_is_paged_with_matching_tables_and_buttons():
    from agent.ui.screens import HELP_CATEGORY_PAGE_SIZE, help_screen, help_visible, section_slug
    from agent.utils.sender import to_safe_html, _visible_text
    visible = [(icon, title, commands) for icon, title, commands in HELP_SECTIONS if help_visible(commands, None)]
    seen = []
    for page in range((len(visible) + HELP_CATEGORY_PAGE_SIZE - 1) // HELP_CATEGORY_PAGE_SIZE):
        screen = help_screen(None, Theme(), page=page)
        titles = [title for _, title, _ in visible[page * HELP_CATEGORY_PAGE_SIZE:(page + 1) * HELP_CATEGORY_PAGE_SIZE]]
        routes = [button.callback_data for row in screen.keyboard.inline_keyboard for button in row]
        for title in titles:
            assert 'help:' + section_slug(title) in routes
        seen.extend(titles)
        assert len(titles) <= HELP_CATEGORY_PAGE_SIZE
        assert all(route in SCREENS for route in routes)
        assert all(len(row) <= 2 for row in screen.keyboard.inline_keyboard)
        assert len(_visible_text(to_safe_html(screen.rich_text))) < 4000
    assert seen == [title for _, title, _ in visible]


def test_stale_category_page_clamps_after_registry_changes():
    from agent.ui.screens import help_screen
    screen = help_screen(None, Theme(), active={'help'}, page=999)
    assert 'Page 1 of 1' in screen.rich_text
    assert 'Essentials' in screen.rich_text
    assert 'help:categories:1' not in str(screen.keyboard)


def test_later_feature_can_return_to_its_overview_page():
    screen = help_section_screen('Approvals', None, Theme())
    routes = [button.callback_data for row in screen.keyboard.inline_keyboard for button in row]
    assert any(route.startswith('help:categories:') for route in routes)
