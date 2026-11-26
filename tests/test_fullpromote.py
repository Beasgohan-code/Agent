"""Full promotion is explicit group-owner delegation, never global-owner bypass."""
from types import SimpleNamespace as NS
from unittest.mock import AsyncMock
import pytest
import test_group as fixtures
from agent.modules import group


def setup(tmp_path,text='/fullpromote 22 confirm'):
    ctx=fixtures.ctx.__wrapped__(tmp_path)
    client=fixtures.FakeClient()
    client.get_me=AsyncMock(return_value=NS(id=99))
    client.get_users=AsyncMock(return_value=NS(id=22))
    owner=fixtures.member(fixtures.OWNER)
    bot=fixtures.member(fixtures.ADMIN)
    bot.privileges.can_promote_members=True
    client.get_chat_member=AsyncMock(side_effect=[owner,bot,fixtures.member(fixtures.MEMBER),owner])
    client.promote_chat_member=AsyncMock(return_value=True)
    return ctx,client,fixtures.FakeMessage(text)


@pytest.mark.asyncio
async def test_fullpromote_owner_grants_bot_ceiling_after_confirmation(tmp_path):
    ctx,client,message=setup(tmp_path)
    await group.build(ctx)[1]['fullpromote'](client,message)
    privileges=client.promote_chat_member.await_args.kwargs['privileges']
    assert privileges.can_promote_members is True
    assert privileges.can_delete_messages is True
    assert privileges.is_anonymous is False
    assert privileges.can_post_messages is False
    assert ctx.chats.history(message.chat.id)[0]['action']=='fullpromote'
    assert 'confirmed' in str(message.replies[-1]).lower()


@pytest.mark.asyncio
async def test_fullpromote_admin_including_global_owner_denied(tmp_path):
    ctx,client,message=setup(tmp_path)
    client.get_chat_member=AsyncMock(return_value=fixtures.member(fixtures.ADMIN))
    await group.build(ctx)[1]['fullpromote'](client,message)
    client.promote_chat_member.assert_not_awaited()
    assert 'group owner' in str(message.replies[-1]).lower()


@pytest.mark.asyncio
@pytest.mark.parametrize('text',['/fullpromote 22','/fullpromote 22 yes','/fullpromote 22 confirm extra'])
async def test_fullpromote_needs_exact_confirmation(tmp_path,text):
    ctx,client,message=setup(tmp_path,text)
    await group.build(ctx)[1]['fullpromote'](client,message)
    client.promote_chat_member.assert_not_awaited()
    assert 'confirm' in str(message.replies[-1])


@pytest.mark.asyncio
async def test_fullpromote_does_not_retry_unconfirmed_mutation(tmp_path):
    ctx,client,message=setup(tmp_path)
    client.promote_chat_member=AsyncMock(side_effect=TimeoutError('SECRET'))
    await group.build(ctx)[1]['fullpromote'](client,message)
    assert client.promote_chat_member.await_count==1
    assert 'unconfirmed' in str(message.replies[-1]).lower()
    assert 'SECRET' not in str(message.replies[-1])


@pytest.mark.asyncio
async def test_fullpromote_bot_ceiling_and_final_ownership_recheck(tmp_path):
    ctx,client,message=setup(tmp_path)
    owner=fixtures.member(fixtures.OWNER)
    bot=fixtures.member(fixtures.ADMIN,can_delete_messages=False)
    bot.privileges.can_promote_members=True
    client.get_chat_member=AsyncMock(side_effect=[owner,bot,fixtures.member(fixtures.MEMBER),owner])
    await group.build(ctx)[1]['fullpromote'](client,message)
    assert client.promote_chat_member.await_args.kwargs['privileges'].can_delete_messages is False
    ctx,client,message=setup(tmp_path)
    client.get_chat_member=AsyncMock(side_effect=[owner,bot,fixtures.member(fixtures.MEMBER),fixtures.member(fixtures.ADMIN)])
    await group.build(ctx)[1]['fullpromote'](client,message)
    client.promote_chat_member.assert_not_awaited()
    assert 'ownership changed' in str(message.replies[-1])


@pytest.mark.asyncio
async def test_fullpromote_existing_admin_not_overwritten(tmp_path):
    ctx,client,message=setup(tmp_path)
    owner=fixtures.member(fixtures.OWNER)
    bot=fixtures.member(fixtures.ADMIN)
    bot.privileges.can_promote_members=True
    client.get_chat_member=AsyncMock(side_effect=[owner,bot,fixtures.member(fixtures.ADMIN)])
    await group.build(ctx)[1]['fullpromote'](client,message)
    client.promote_chat_member.assert_not_awaited()


@pytest.mark.asyncio
async def test_fullpromote_false_ack_not_audited_as_success(tmp_path):
    ctx,client,message=setup(tmp_path)
    client.promote_chat_member=AsyncMock(return_value=False)
    await group.build(ctx)[1]['fullpromote'](client,message)
    assert not ctx.chats.history(message.chat.id)
    assert 'unconfirmed' in str(message.replies[-1])


@pytest.mark.asyncio
@pytest.mark.parametrize('hydrate',[False,True])
async def test_fullpromote_same_chat_reply_requires_confirm(tmp_path,hydrate):
    ctx,client,message=setup(tmp_path,'/fullpromote confirm')
    message.reply_to_message=NS(id=70,chat=NS(id=message.chat.id),from_user=NS(id=22))
    if hydrate:
        client.get_messages=AsyncMock(return_value=message.reply_to_message)
        message.reply_to_message=None
        message.reply_to_message_id=70
    await group.build(ctx)[1]['fullpromote'](client,message)
    client.get_users.assert_not_awaited()
    client.promote_chat_member.assert_awaited_once()


@pytest.mark.asyncio
async def test_fullpromote_hydrates_reply_and_bare_reply_offers_bound_confirmation(tmp_path):
    from agent.platform.actions import ActionRouter
    ctx,client,message=setup(tmp_path,'/fullpromote')
    ctx.actions=ActionRouter()
    message.reply_to_message_id=70
    client.get_messages=AsyncMock(return_value=NS(id=70,chat=message.chat,from_user=NS(id=22,first_name='Target'),sender_chat=None))
    sent=NS(id=901,chat=message.chat,reply=AsyncMock(return_value=NS(id=902)))
    message.reply=AsyncMock(return_value=sent)
    commands=group.build(ctx)[1]
    await commands['fullpromote'](client,message)
    client.promote_chat_member.assert_not_awaited()
    text=str(message.reply.call_args.args[0])
    assert '22' in text and 'confirm' in text.lower()
    keyboard=message.reply.call_args.kwargs['reply_markup']
    data=keyboard.inline_keyboard[0][0].callback_data
    # Preview consumes one owner check. Confirmation must recheck all authority.
    owner=fixtures.member(fixtures.OWNER)
    bot=fixtures.member(fixtures.ADMIN)
    bot.privileges.can_promote_members=True
    client.get_chat_member=AsyncMock(side_effect=[owner,bot,fixtures.member(fixtures.MEMBER),owner])
    query=NS(message=sent,from_user=message.from_user,data=data,answer=AsyncMock())
    await ctx.actions.dispatch(client,query)
    client.promote_chat_member.assert_awaited_once()
    await ctx.actions.dispatch(client,query)
    client.promote_chat_member.assert_awaited_once()


@pytest.mark.asyncio
@pytest.mark.parametrize('case',['actor','chat','copy','expired','cancel','ownership'])
async def test_fullpromote_confirmation_binding_and_rechecks(tmp_path,monkeypatch,case):
    import agent.modules.group.fullpromote as implementation
    from agent.platform.actions import ActionRouter
    ctx,client,message=setup(tmp_path,'/fullpromote')
    ctx.actions=ActionRouter()
    message.reply_to_message=NS(id=70,chat=message.chat,from_user=NS(id=22))
    sent=NS(id=901,chat=NS(id=message.chat.id,type=message.chat.type),reply=AsyncMock())
    message.reply=AsyncMock(return_value=sent)
    commands=group.build(ctx)[1]
    await commands['fullpromote'](client,message)
    data=message.reply.call_args.kwargs['reply_markup'].inline_keyboard[0][0].callback_data
    actor=message.from_user
    if case=='actor':actor=NS(id=33)
    if case=='chat':sent.chat.id=-999
    if case=='copy':sent.id=902
    if case=='expired':
        future=implementation.time.monotonic()+121
        monkeypatch.setattr(implementation,'time',NS(monotonic=lambda:future))
    if case=='cancel':data=data.rsplit(':',1)[0]+':cancel'
    client.get_chat_member=AsyncMock(return_value=fixtures.member(fixtures.ADMIN))
    query=NS(message=sent,from_user=actor,data=data,answer=AsyncMock())
    await ctx.actions.dispatch(client,query)
    client.promote_chat_member.assert_not_awaited()
    if case!='ownership':client.get_chat_member.assert_not_awaited()
    else:assert 'group owner' in str(sent.reply.call_args.args[0]).lower()
