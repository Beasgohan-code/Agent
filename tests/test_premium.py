"""Agent — implementation detail."""

import asyncio
import time
from types import SimpleNamespace

import pytest

from agent.config import Settings
from agent.modules import leech, premium as premium_module
from agent.platform.chats import ChatStore
from agent.platform.context import ModuleContext
from agent.platform.jobs import JobQueue
from agent.platform.links import LinkStore
from agent.platform.premium import FREE, PREMIUM, PremiumBook
from agent.platform.storage import QuotaExceeded, Storage
from agent.ui.theme import Theme

OWNER = 11
USER = 99

ENV = {
    "BOT_TOKEN": "123456789:AAHfakeTokenValueForTests_1234567890abc",
    "API_ID": "1234567",
    "API_HASH": "0123456789abcdef0123456789abcdef",
    "OWNER_ID": str(OWNER),
}


def make_book(tmp_path):
    return PremiumBook(tmp_path / "data")


def make_ctx(tmp_path):
    settings = Settings.from_env({**ENV, "DATA_DIR": str(tmp_path / "data")})
    premium = PremiumBook(settings.data_dir)
    return ModuleContext(
        settings=settings,
        theme=Theme(),
        sender=None,
        jobs=JobQueue(),
        storage=Storage(tmp_path / "storage"),
        links=LinkStore(tmp_path / "links", "secret"),
        chats=ChatStore(tmp_path / "chats"),
        premium=premium,
    )


class FakeMessage:
    def __init__(self, text, *, uid=USER, reply_to=None):
        self.text = text
        self.reply_to_message = reply_to
        self.id = 10
        self.from_user = SimpleNamespace(id=uid, first_name="T", is_bot=False)
        self.chat = SimpleNamespace(id=-100)
        self.replies = []

    async def reply(self, text, **_kwargs):
        self.replies.append(text)


class FakeClient:
    def __init__(self):
        self.calls = []

    async def send_message(self, chat_id, text, **kwargs):
        self.calls.append(("send", int(chat_id), text))
        return SimpleNamespace(id=1)


def run(handler, message, client=None):
    asyncio.run(handler(client or FakeClient(), message))


# --- the book --------------------------------------------------------------


def test_free_by_default_and_premium_after_a_grant(tmp_path):
    book = make_book(tmp_path)

    assert book.is_premium(USER) is False
    assert book.tier(USER) is FREE

    book.grant(USER, 30, by=OWNER)

    assert book.is_premium(USER) is True
    assert book.tier(USER) is PREMIUM
    assert book.until(USER) > time.time()


def test_zero_days_means_lifetime(tmp_path):
    book = make_book(tmp_path)

    book.grant(USER, 0)

    assert book.until(USER) == 0.0
    assert book.is_premium(USER, now=time.time() + 10 * 365 * 86400) is True


def test_an_expired_grant_is_not_premium(tmp_path):
    book = make_book(tmp_path)
    book.grant(USER, 1, now=time.time() - 5 * 86400)

    assert book.is_premium(USER) is False
    assert book.tier(USER) is FREE


def test_granting_extends_rather_than_resets(tmp_path):
    book = make_book(tmp_path)
    first = book.grant(USER, 10)
    second = book.grant(USER, 10)

    assert second > first


def test_revoking_removes_and_reports(tmp_path):
    book = make_book(tmp_path)
    book.grant(USER, 30)

    assert book.revoke(USER) is True
    assert book.revoke(USER) is False
    assert book.count() == 0


def test_the_book_survives_a_restart(tmp_path):
    book = make_book(tmp_path)
    book.grant(USER, 5)

    reopened = make_book(tmp_path)

    assert reopened.is_premium(USER) is True


# --- daily allowances ------------------------------------------------------


def test_take_stops_at_the_free_allowance(tmp_path):
    book = make_book(tmp_path)

    for _ in range(FREE.transfers_per_day):
        assert book.take(USER, "leech") is True

    assert book.take(USER, "leech") is False
    assert book.remaining(USER, "leech") == 0


def test_premium_gets_a_bigger_allowance(tmp_path):
    book = make_book(tmp_path)
    book.grant(USER, 30)

    for _ in range(FREE.transfers_per_day):
        assert book.take(USER, "leech") is True

    assert book.remaining(USER, "leech") == PREMIUM.transfers_per_day - FREE.transfers_per_day


def test_counters_reset_on_a_new_day(tmp_path):
    book = make_book(tmp_path)
    for _ in range(FREE.transfers_per_day):
        book.take(USER, "leech")

    tomorrow = time.time() + 86400

    assert book.remaining(USER, "leech", now=tomorrow) == FREE.transfers_per_day


def test_an_unknown_allowance_is_a_programming_error(tmp_path):
    book = make_book(tmp_path)
    with pytest.raises(ValueError):
        book.take(USER, "teleport")


# --- enforcement -----------------------------------------------------------


def test_free_quota_is_smaller_and_enforced(tmp_path):
    storage = Storage(tmp_path / "storage")
    payload = b"x" * (FREE.quota_mb * 1024 * 1024 + 1)

    with pytest.raises(QuotaExceeded):
        storage.check_quota(USER, len(payload), quota_bytes=FREE.quota_bytes)
    # The same write fits the premium allowance.
    storage.check_quota(USER, len(payload), quota_bytes=PREMIUM.quota_bytes)


def test_leech_refuses_when_the_day_is_spent(tmp_path):
    ctx = make_ctx(tmp_path)
    for _ in range(FREE.transfers_per_day):
        ctx.premium.take(USER, "leech")
    _, commands = leech.build(ctx)
    message = FakeMessage("/leech https://example.com/a.bin")

    run(commands["leech"], message)

    assert "allowance" in message.replies[0].lower()
    assert "/premium" in message.replies[0]


# --- the commands ----------------------------------------------------------


def test_premium_panel_shows_the_tier_and_what_is_left(tmp_path):
    ctx = make_ctx(tmp_path)
    _, commands = premium_module.build(ctx)
    message = FakeMessage("/premium")

    run(commands["premium"], message)

    assert "Free" in message.replies[0]
    assert "not premium" in message.replies[0]
    assert "256 MB" in message.replies[0]


def test_only_the_owner_can_grant(tmp_path):
    ctx = make_ctx(tmp_path)
    _, commands = premium_module.build(ctx)
    message = FakeMessage(f"/addpremium {USER} 30", uid=USER)

    run(commands["addpremium"], message)

    assert "owner" in message.replies[0].lower()
    assert ctx.premium.is_premium(USER) is False


def test_the_owner_grants_and_the_user_is_told(tmp_path):
    ctx = make_ctx(tmp_path)
    _, commands = premium_module.build(ctx)
    client = FakeClient()
    message = FakeMessage(f"/addpremium {USER} 30", uid=OWNER)

    run(commands["addpremium"], message, client)

    assert ctx.premium.is_premium(USER) is True
    assert "granted" in message.replies[0].lower()
    assert client.calls[0][1] == USER


def test_the_owner_can_revoke(tmp_path):
    ctx = make_ctx(tmp_path)
    ctx.premium.grant(USER, 30)
    _, commands = premium_module.build(ctx)
    message = FakeMessage(f"/delpremium {USER}", uid=OWNER)

    run(commands["delpremium"], message)

    assert ctx.premium.is_premium(USER) is False
    assert "removed" in message.replies[0].lower()


def test_the_listing_shows_who_has_it(tmp_path):
    ctx = make_ctx(tmp_path)
    ctx.premium.grant(USER, 30)
    _, commands = premium_module.build(ctx)
    message = FakeMessage("/premiumusers", uid=OWNER)

    run(commands["premiumusers"], message)

    assert str(USER) in message.replies[0]
    assert "active" in message.replies[0]


def test_granting_by_reply_uses_the_replied_user(tmp_path):
    ctx = make_ctx(tmp_path)
    _, commands = premium_module.build(ctx)
    target = SimpleNamespace(from_user=SimpleNamespace(id=USER))
    message = FakeMessage("/addpremium", uid=OWNER, reply_to=target)

    run(commands["addpremium"], message)

    assert ctx.premium.is_premium(USER) is True


def test_lifetime_is_the_zero_day_spelling(tmp_path):
    ctx = make_ctx(tmp_path)
    _, commands = premium_module.build(ctx)
    message = FakeMessage(f"/addpremium {USER} 0", uid=OWNER)

    run(commands["addpremium"], message)

    assert ctx.premium.until(USER) == 0.0


@pytest.mark.parametrize('args', ['99 -1', '99 nope', '99 3651', '99 1 extra', '-99 1', '0 1', '99 ²', '9999999999999999999999999999 1'])
def test_invalid_grant_arguments_never_silently_grant_default_or_lifetime(tmp_path, args):
    ctx = make_ctx(tmp_path)
    _, commands = premium_module.build(ctx)
    message = FakeMessage('/addpremium ' + args, uid=OWNER)
    run(commands['addpremium'], message)
    assert not ctx.premium.is_premium(USER)
    assert 'Premium granted' not in str(message.replies)
