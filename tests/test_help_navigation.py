"""Mobile pagination and confirmed-only navigation retries."""

import asyncio
import re
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
            seen += re.findall(r"<code>/([a-z_0-9]+)</code>", screen.rich_text)
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
