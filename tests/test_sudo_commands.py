"""Command parsing and every delegation boundary are checked independently."""

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from agent.modules.ops.sudo_commands import build
from agent.platform.sudo_access import SudoError
from test_ops import FakeMessage

pytest_plugins = ["test_ops"]
from agent.modules import ops


@pytest.mark.parametrize(
    "command", ["sudo", "addsudo", "delsudo", "sudolist", "sudoperms"]
)
def test_every_sudo_command_requires_owner(command):
    service = SimpleNamespace(
        grant=AsyncMock(), revoke=AsyncMock(), listing=AsyncMock()
    )
    handler = build(service, AsyncMock(return_value=False))[command]
    asyncio.run(handler(None, FakeMessage("/" + command, uid=22)))
    service.grant.assert_not_awaited()
    service.revoke.assert_not_awaited()
    service.listing.assert_not_awaited()


@pytest.mark.parametrize(
    "text,method",
    [
        ("/addsudo 22 diagnostics.read -100 2 temporary support", "grant"),
        ("/delsudo 22 diagnostics.read -100 support ended", "revoke"),
        ("/sudolist", "listing"),
        ("/sudoperms 22", "listing"),
        ("/sudolist history", "history"),
        ("/sudo add 22", "grant"),
        ("/sudo remove 22", "revoke"),
        ("/sudo list", "listing"),
    ],
)
def test_command_routes_to_authoritative_service(text, method):
    service = SimpleNamespace(
        grant=AsyncMock(return_value=True),
        revoke=AsyncMock(return_value=True),
        listing=AsyncMock(return_value=[]),
        history=AsyncMock(return_value=[]),
    )
    name = text.split()[0][1:]
    message = FakeMessage(text)
    message.chat.id = 11
    asyncio.run(build(service, AsyncMock(return_value=True))[name](None, message))
    getattr(service, method).assert_awaited_once()
    assert message.replies


def test_failed_grant_never_reports_success():
    service = SimpleNamespace(grant=AsyncMock(side_effect=SudoError("not confirmed")))
    message = FakeMessage("/addsudo 22 diagnostics.read global 1 support")
    message.chat.id = 11
    asyncio.run(build(service, AsyncMock(return_value=True))["addsudo"](None, message))
    assert message.replies == ["not confirmed"]


def test_scoped_diagnostics_uses_backend_check_and_no_owner_data(ctx):
    async def scenario():
        _, handlers = ops.build(ctx)
        denied = FakeMessage("/db", uid=22)
        await handlers["db"](None, denied)
        assert "reserved" in denied.replies[0]
        sensitive = FakeMessage("/restart", uid=22)
        await handlers["restart"](None, sensitive)
        assert "reserved" in sensitive.replies[0]
        allowed = FakeMessage("/db", uid=22)
        allowed.chat.id = -100
        with patch(
            "agent.platform.sudo_access.SudoAccess.allowed",
            new=AsyncMock(return_value=True),
        ) as check:
            await handlers["db"](None, allowed)
            check.assert_awaited_once_with(22, "diagnostics.read", -100)
        assert "credentials or private metadata" in allowed.replies[0]
        assert "Host" not in allowed.replies[0]

    asyncio.run(scenario())
