"""Warning cards and read-only buttons preserve current authorization and group scope."""
from types import SimpleNamespace as NS
from unittest.mock import AsyncMock
import pytest
from test_mute_target_parity import setup
from agent.modules import moderation
from agent.platform.actions import ActionRouter


@pytest.mark.asyncio
async def test_warn_username_card_and_view_button(tmp_path):
    ctx,client,message=setup(tmp_path,'/warn @target spam <ads>')
    ctx.actions=ActionRouter()
    message.reply=AsyncMock(return_value=NS(id=500))
    await moderation.build(ctx)[1]['warn'](client,message)
    client.get_users.assert_awaited_once_with('@target')
    call=message.reply.await_args
    assert 'Warning issued' in str(call.args[0]) and '&lt;ads&gt;' in str(call.args[0])
    data=call.kwargs['reply_markup'].inline_keyboard[0][0].callback_data
    query=NS(data=data,from_user=NS(id=11),message=NS(id=500,chat=message.chat,reply=AsyncMock(return_value=NS(id=501))),answer=AsyncMock())
    await ctx.actions.dispatch(client,query)
    assert 'Active warnings' in str(query.message.reply.await_args.args[0])
    assert await ctx.chats.aactive_warning_count(message.chat.id,22)==1


@pytest.mark.asyncio
async def test_warning_view_rejects_other_group_and_nonadmin(tmp_path):
    ctx,client,message=setup(tmp_path,'/warn 22 spam')
    ctx.actions=ActionRouter()
    await moderation.build(ctx)[1]['warn'](client,message)
    query=NS(data='warnview:'+str(message.chat.id)+':22',from_user=NS(id=33),message=NS(chat=NS(id=-200),reply=AsyncMock()),answer=AsyncMock())
    await ctx.actions.dispatch(client,query)
    query.message.reply.assert_not_awaited()
    query.message.chat=message.chat
    client.get_chat_member=AsyncMock(return_value=NS(status='member',privileges=None))
    await ctx.actions.dispatch(client,query)
    query.message.reply.assert_not_awaited()


@pytest.mark.asyncio
async def test_warn_current_bot_rights_denied_before_record(tmp_path):
    ctx,client,message=setup(tmp_path,'/warn 22 reason')
    old=client.get_chat_member.side_effect
    async def member(chat,uid):
        return NS(status='member',privileges=None) if uid==99 else await old(chat,uid)
    client.get_chat_member=AsyncMock(side_effect=member)
    await moderation.build(ctx)[1]['warn'](client,message)
    assert not await ctx.chats.awarnings_of(message.chat.id,22)


@pytest.mark.asyncio
async def test_warning_audit_failure_still_reports_recorded_warning(tmp_path):
    from unittest.mock import Mock
    ctx,client,message=setup(tmp_path,'/warn 22 spam')
    ctx.chats.log=Mock(side_effect=RuntimeError('PRIVATE_DB'))
    await moderation.build(ctx)[1]['warn'](client,message)
    assert await ctx.chats.aactive_warning_count(message.chat.id,22)==1
    text=str(message.replies[-1])
    assert 'Warning issued' in text and 'audit unconfirmed' in text
    assert 'PRIVATE_DB' not in text


@pytest.mark.asyncio
async def test_warning_final_permission_loss_prevents_recording(tmp_path):
    import test_moderation as fixtures
    ctx,client,message=setup(tmp_path,'/warn 22 spam')
    client.get_chat_member=AsyncMock(side_effect=[fixtures.member(fixtures.ADMIN),fixtures.member(fixtures.MEMBER),fixtures.member(fixtures.ADMIN),fixtures.member(fixtures.MEMBER)])
    await moderation.build(ctx)[1]['warn'](client,message)
    assert await ctx.chats.aactive_warning_count(message.chat.id,22)==0


@pytest.mark.asyncio
async def test_warning_false_escalation_ack_not_claimed_as_success(tmp_path):
    from agent.platform.warning_policy import operate
    ctx,client,message=setup(tmp_path,'/warn 22 spam')
    await operate(ctx.chats,message.chat.id,actor=11,changes={'limit':1})
    client.restrict_chat_member=AsyncMock(return_value=False)
    await moderation.build(ctx)[1]['warn'](client,message)
    assert await ctx.chats.aactive_warning_count(message.chat.id,22)==1
    assert 'Escalation unconfirmed' in str(message.replies[-1])
    assert 'Threshold reached: member muted' not in str(message.replies[-1])


@pytest.mark.asyncio
async def test_warning_view_rechecks_rights_after_loading(tmp_path):
    import test_moderation as fixtures
    ctx,client,message=setup(tmp_path,'/warn 22 reason')
    ctx.actions=ActionRouter()
    await moderation.build(ctx)[1]['warn'](client,message)
    client.get_chat_member=AsyncMock(side_effect=[fixtures.member(fixtures.ADMIN),fixtures.member(fixtures.MEMBER)])
    query=NS(data=f'warnview:{message.chat.id}:22',from_user=NS(id=11),message=NS(chat=message.chat,reply=AsyncMock()),answer=AsyncMock())
    await ctx.actions.dispatch(client,query)
    query.message.reply.assert_not_awaited()
    assert 'changed' in query.answer.await_args.args[0]
