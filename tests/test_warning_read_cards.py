"""Warning readers paginate canonical records with self/admin boundaries."""
from types import SimpleNamespace as NS
from unittest.mock import AsyncMock
import pytest
from test_mute_target_parity import setup
from agent.modules import moderation
from agent.platform.actions import ActionRouter


@pytest.mark.asyncio
async def test_warns_username_pages_have_real_controls(tmp_path):
    ctx,client,message=setup(tmp_path,'/warns @target')
    ctx.actions=ActionRouter()
    for i in range(5):
        await ctx.chats.aadd_warning(message.chat.id,22,moderator_id=11,reason='reason'+str(i))
    message.reply=AsyncMock(return_value=NS(id=500))
    await moderation.build(ctx)[1]['warns'](client,message)
    call=message.reply.await_args
    text=str(call.args[0])
    assert 'Page 1 of 2' in text and 'reason4' in text and 'reason0' not in text
    button=call.kwargs['reply_markup'].inline_keyboard[0][0]
    query=NS(data=button.callback_data,from_user=NS(id=11),message=NS(chat=message.chat,reply=AsyncMock(return_value=NS(id=501))),answer=AsyncMock())
    await ctx.actions.dispatch(client,query)
    text=str(query.message.reply.await_args.args[0])
    assert 'Page 2 of 2' in text and 'reason0' in text


@pytest.mark.asyncio
async def test_member_cannot_inspect_other_member_or_note(tmp_path):
    import test_moderation as fixtures
    ctx,client,message=setup(tmp_path,'/warnings 22')
    await ctx.chats.aadd_warning(message.chat.id,22,moderator_id=11,reason='PRIVATE_REASON')
    client.get_chat_member=AsyncMock(return_value=fixtures.member(fixtures.MEMBER))
    await moderation.build(ctx)[1]['warnings'](client,message)
    assert 'PRIVATE_REASON' not in str(message.replies)
    assert 'permission' in str(message.replies[-1]).lower()


@pytest.mark.asyncio
async def test_self_default_view_hides_moderation_note(tmp_path):
    import test_moderation as fixtures
    ctx,client,message=setup(tmp_path,'/warns')
    await ctx.chats.aadd_warning(message.chat.id,11,moderator_id=33,reason='own reason')
    ctx.chats.set_note(message.chat.id,11,'PRIVATE_NOTE')
    client.get_chat_member=AsyncMock(return_value=fixtures.member(fixtures.MEMBER))
    await moderation.build(ctx)[1]['warns'](client,message)
    assert 'own reason' in str(message.replies[-1])
    assert 'PRIVATE_NOTE' not in str(message.replies)


@pytest.mark.asyncio
async def test_reader_rechecks_rights_after_store_reads(tmp_path):
    import test_moderation as fixtures
    ctx,client,message=setup(tmp_path,'/warnings 22')
    await ctx.chats.aadd_warning(message.chat.id,22,moderator_id=11,reason='PRIVATE_REASON')
    client.get_chat_member=AsyncMock(side_effect=[fixtures.member(fixtures.ADMIN),fixtures.member(fixtures.MEMBER)])
    await moderation.build(ctx)[1]['warnings'](client,message)
    assert 'PRIVATE_REASON' not in str(message.replies)
    assert 'permission' in str(message.replies[-1]).lower()


@pytest.mark.asyncio
async def test_page_controls_reject_cross_group_without_read(tmp_path):
    ctx,client,message=setup(tmp_path,'/warns 22')
    ctx.actions=ActionRouter()
    moderation.build(ctx)
    query=NS(data=f'warnpage:{message.chat.id}:22:1',from_user=NS(id=11),message=NS(chat=NS(id=-200,type=message.chat.type),reply=AsyncMock()),answer=AsyncMock())
    ctx.chats.awarnings_of=AsyncMock()
    await ctx.actions.dispatch(client,query)
    ctx.chats.awarnings_of.assert_not_awaited()
    query.message.reply.assert_not_awaited()


@pytest.mark.asyncio
async def test_out_of_range_page_and_provider_failure_are_safe(tmp_path):
    ctx,client,message=setup(tmp_path,'/warns @target 999')
    await moderation.build(ctx)[1]['warns'](client,message)
    assert 'Page unavailable' in str(message.replies[-1])
    client.get_users=AsyncMock(side_effect=ValueError('PRIVATE_TOKEN'))
    message.text='/warns @target'
    await moderation.build(ctx)[1]['warns'](client,message)
    assert 'PRIVATE_TOKEN' not in str(message.replies)
