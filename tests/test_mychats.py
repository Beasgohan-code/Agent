"""Owner chat discovery is bounded, live-checked and private."""
from types import SimpleNamespace as NS
from unittest.mock import AsyncMock
from pyrogram.enums import ChatMemberStatus, ChatType
from test_ops import ctx, FakeMessage, handlers, run


def test_mychats_checks_known_groups_and_escapes_titles(ctx):
    ctx.chats.set_note(-100, 1, 'known')
    ctx.chats.set_note(-200, 1, 'known')
    bot = NS(get_chat_member=AsyncMock(side_effect=[NS(status=ChatMemberStatus.ADMINISTRATOR), NS(status=ChatMemberStatus.MEMBER)]),
             get_chat=AsyncMock(return_value=NS(type=ChatType.SUPERGROUP, title='<unsafe>')))
    message = FakeMessage('/mychats'); message.chat.id = 11
    run(handlers(ctx)['mychats'], message, bot)
    text = str(message.replies[-1])
    assert '-100' in text and '-200' not in text
    assert '&lt;unsafe&gt;' in text and '<unsafe>' not in text
    assert bot.get_chat_member.await_count == 2


def test_mychats_rejects_before_network(ctx):
    bot = NS(get_chat_member=AsyncMock(), get_chat=AsyncMock())
    handler = handlers(ctx)['mychats']
    for uid, chat, text in ((22, 22, '/mychats'), (11, -100, '/mychats'), (11, 11, '/mychats 0'), (11, 11, '/mychats 1 extra')):
        item = FakeMessage(text, uid=uid); item.chat.id = chat
        run(handler, item, bot)
    bot.get_chat_member.assert_not_awaited()


def test_mychats_failed_check_not_claimed_as_admin(ctx):
    ctx.chats.set_note(-100, 1, 'known')
    bot = NS(get_chat_member=AsyncMock(side_effect=RuntimeError('SECRET')), get_chat=AsyncMock())
    item = FakeMessage('/mychats'); item.chat.id = 11
    run(handlers(ctx)['mychats'], item, bot)
    text = str(item.replies[-1])
    assert 'unconfirmed' in text.lower() and 'SECRET' not in text
    bot.get_chat.assert_not_awaited()


def test_known_chat_page_is_bounded_and_nonmutating(ctx):
    for cid in range(-1, -26, -1):
        ctx.chats.set_note(cid, 1, 'known')
    before = len(ctx.chats._chats)
    first, total = ctx.chats.known_group_page(1)
    second, _ = ctx.chats.known_group_page(2)
    assert len(first) == len(second) == 10 and total == 25
    assert not set(first) & set(second)
    assert len(ctx.chats._chats) == before


def test_mychats_configuration_change_hides_result(ctx):
    ctx.chats.set_note(-100, 1, 'known')
    async def changed(*args):
        object.__setattr__(ctx.settings, 'owner_id', 22)
        return NS(status=ChatMemberStatus.ADMINISTRATOR)
    bot = NS(get_chat_member=AsyncMock(side_effect=changed), get_chat=AsyncMock(return_value=NS(type=ChatType.GROUP, title='PRIVATE_CHAT')))
    item = FakeMessage('/mychats'); item.chat.id = 11
    run(handlers(ctx)['mychats'], item, bot)
    assert 'PRIVATE_CHAT' not in str(item.replies[-1])
    assert 'changed' in str(item.replies[-1])
