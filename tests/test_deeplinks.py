"""``/start <payload>``: one payload, one owner, and nothing silently dropped."""

import asyncio
from types import SimpleNamespace

import pytest

from agent.platform.deeplinks import DeepLinkRouter, split


def run(coro):
    return asyncio.run(coro)


# --- the payload split -----------------------------------------------------


def test_a_prefixed_payload_is_split_on_the_first_separator():
    assert split("link_abc.def.ghi") == ("link", "abc.def.ghi")
    assert split("verify_42") == ("verify", "42")


def test_an_unprefixed_payload_belongs_to_nobody():
    assert split("just-text") == ("", "just-text")
    assert split("") == ("", "")
    assert split("   ") == ("", "")


def test_a_payload_may_carry_underscores_of_its_own():
    assert split("link_a_b_c") == ("link", "a_b_c")


# --- the router ------------------------------------------------------------


def test_registering_a_prefix_twice_is_an_error():
    router = DeepLinkRouter()
    router.register("link", lambda *_: None)

    with pytest.raises(ValueError):
        router.register("LINK", lambda *_: None)


def test_a_prefix_cannot_be_empty_or_contain_the_separator():
    router = DeepLinkRouter()

    with pytest.raises(ValueError):
        router.register("  ", lambda *_: None)
    with pytest.raises(ValueError):
        router.register("li_nk", lambda *_: None)


def test_handles_only_answers_for_registered_prefixes():
    router = DeepLinkRouter()
    router.register("link", lambda *_: None)

    assert router.handles("link_abc") is True
    assert router.handles("verify_abc") is False
    assert router.handles("") is False


def test_dispatch_passes_the_rest_to_the_owner():
    seen = []
    router = DeepLinkRouter()

    async def handler(client, message, rest):
        seen.append((client, message, rest))

    router.register("link", handler)
    done = run(router.dispatch("client", "message", "link_abc.def"))

    assert done is True
    assert seen == [("client", "message", "abc.def")]


def test_an_unknown_payload_is_not_claimed():
    router = DeepLinkRouter()

    assert run(router.dispatch(None, None, "nobody_owns_this")) is False


def test_a_raising_handler_is_contained():
    """A broken link must not take /start down with it."""
    router = DeepLinkRouter()

    async def handler(client, message, rest):
        raise RuntimeError("boom")

    router.register("link", handler)

    assert run(router.dispatch(None, None, "link_x")) is True


# --- /start parsing --------------------------------------------------------


def test_start_payload_ignores_the_command_itself():
    from agent.handlers.commands import start_payload

    assert start_payload("/start link_abc") == "link_abc"
    assert start_payload("/start@agent_bot link_abc") == "link_abc"
    assert start_payload("/start") == ""
    assert start_payload("/start   ") == ""
    assert start_payload("/help link_abc") == ""


def test_the_start_handler_routes_a_payload_instead_of_greeting():
    from agent.handlers.commands import CommandHandlers

    class Sender:
        def __init__(self):
            self.sent = []

        async def send(self, chat_id, screen):
            self.sent.append(screen)

        async def send_photo(self, chat_id, screen, photo):
            self.sent.append(screen)

    sender = Sender()
    router = DeepLinkRouter()
    seen = []

    async def handler(client, message, rest):
        seen.append(rest)

    router.register("link", handler)
    handlers = CommandHandlers(sender, None, deeplinks=router)
    message = SimpleNamespace(
        text="/start link_token",
        from_user=SimpleNamespace(id=7),
        chat=SimpleNamespace(id=7),
    )

    run(handlers.start(None, message))

    assert seen == ["token"]
    assert sender.sent == []          # the welcome screen is not sent as well
