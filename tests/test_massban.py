"""Bulk bans remain bounded, owner-only and current-chat-only."""
from types import SimpleNamespace as NS
from unittest.mock import AsyncMock
import pytest
from pyrogram.enums import ChatType, ChatMemberStatus as Status
from agent.modules.ops.massban import massban


def setup(text='/massban 22 33', uid=11, chat=-100):
    value = NS(settings=NS(owner_id=11))
    message = NS(text=text, from_user=NS(id=uid), chat=NS(id=chat, type=ChatType.SUPERGROUP if chat < 0 else ChatType.PRIVATE), reply=AsyncMock())
    async def member(cid, target):
        return NS(status=Status.ADMINISTRATOR, privileges=NS(can_restrict_members=True)) if target in (11, 99) else NS(status=Status.MEMBER)
    bot = NS(get_me=AsyncMock(return_value=NS(id=99)), get_chat_member=AsyncMock(side_effect=member), ban_chat_member=AsyncMock(return_value=True))
    return value, bot, message


@pytest.mark.asyncio
async def test_bans_only_explicit_targets_in_current_group():
    value, bot, item = setup()
    await massban(value, bot, item)
    assert [c.args for c in bot.ban_chat_member.await_args_list] == [(-100, 22), (-100, 33)]
    assert '2 confirmed' in str(item.reply.await_args.args[0])


@pytest.mark.asyncio
@pytest.mark.parametrize('text,uid,chat', [('/massban 22',22,-100),('/massban 22',11,11),('/massban 22 22',11,-100),('/massban -100',11,-100),('/massban '+' '.join(str(n) for n in range(20,31)),11,-100)])
async def test_invalid_requests_have_no_network_effects(text, uid, chat):
    value, bot, item = setup(text,uid,chat)
    await massban(value, bot, item)
    bot.get_me.assert_not_awaited()
    bot.ban_chat_member.assert_not_awaited()


@pytest.mark.asyncio
async def test_ambiguous_ban_stops_without_retry_or_secret_leak():
    value, bot, item = setup()
    bot.ban_chat_member.side_effect = RuntimeError('SECRET')
    await massban(value, bot, item)
    assert bot.ban_chat_member.await_count == 1
    assert 'unconfirmed' in str(item.reply.await_args.args[0])
    assert 'SECRET' not in str(item.reply.await_args.args[0])


@pytest.mark.asyncio
async def test_admin_targets_and_owner_are_protected():
    value, bot, item = setup('/massban 11 99 22')
    async def member(cid, uid):
        return NS(status=Status.ADMINISTRATOR, privileges=NS(can_restrict_members=True))
    bot.get_chat_member.side_effect = member
    await massban(value, bot, item)
    bot.ban_chat_member.assert_not_awaited()
    assert '3 protected' in str(item.reply.await_args.args[0])


@pytest.mark.asyncio
async def test_rights_loss_stops_remaining_targets():
    value, bot, item = setup()
    original = bot.get_chat_member.side_effect
    async def member(cid, uid):
        if bot.ban_chat_member.await_count and uid == 99:
            return NS(status=Status.MEMBER)
        return await original(cid, uid)
    bot.get_chat_member.side_effect = member
    await massban(value, bot, item)
    assert bot.ban_chat_member.await_count == 1
    assert '1 confirmed' in str(item.reply.await_args.args[0])


@pytest.mark.asyncio
async def test_owner_change_before_effect_prevents_ban():
    value, bot, item = setup()
    original = bot.get_chat_member.side_effect
    async def changed(cid, uid):
        result = await original(cid, uid)
        if uid == 22:
            value.settings.owner_id = 44
        return result
    bot.get_chat_member.side_effect = changed
    await massban(value, bot, item)
    bot.ban_chat_member.assert_not_awaited()


def test_registered_handler_blocks_duplicate_update(tmp_path):
    import asyncio
    from test_ops import ctx as context_fixture
    from agent.modules import ops
    from unittest.mock import patch
    value = context_fixture.__wrapped__(tmp_path)
    handler = ops.build(value)[1]['massban']
    item = NS(id=77, text='/massban 22', from_user=NS(id=11), chat=NS(id=-100, type=ChatType.SUPERGROUP), reply=AsyncMock())
    async def scenario():
        with patch('agent.modules.ops.massban.massban', AsyncMock()) as execute:
            await handler(None, item)
            await handler(None, item)
            execute.assert_awaited_once()
    asyncio.run(scenario())
