"""Rich mute cards expose real authorized one-use unmute controls."""
from types import SimpleNamespace as NS
from unittest.mock import AsyncMock
import pytest
from test_mute_target_parity import setup
from agent.modules import moderation
from agent.platform.actions import ActionRouter


@pytest.mark.asyncio
async def test_mute_card_has_working_unmute_button_and_replay_is_refused(tmp_path):
    ctx,client,message=setup(tmp_path,'/mute 22 2m spam')
    ctx.actions=ActionRouter()
    sent=NS(id=500)
    message.reply=AsyncMock(return_value=sent)
    client.get_chat=AsyncMock(return_value=NS(permissions=NS(can_send_messages=True)))
    await moderation.build(ctx)[1]['mute'](client,message)
    call=message.reply.await_args
    assert "Moderator" in str(call.args[0]) and "Telegram confirmed" in str(call.args[0])
    keyboard=call.kwargs['reply_markup']
    button=keyboard.inline_keyboard[0][0]
    assert 'Unmute' in button.text
    query=NS(data=button.callback_data,from_user=NS(id=11),message=NS(id=500,chat=message.chat,reply=AsyncMock(return_value=NS(id=501))),answer=AsyncMock())
    until=client.restrict_chat_member.await_args.kwargs['until_date']
    from pyrogram.enums import ChatMemberStatus
    old=client.get_chat_member.side_effect
    async def current(chat,uid):
        if uid==22:
            return NS(status=ChatMemberStatus.RESTRICTED,until_date=until)
        return await old(chat,uid)
    client.get_chat_member=AsyncMock(side_effect=current)
    assert await ctx.actions.dispatch(client,query)
    assert client.restrict_chat_member.await_count==2
    assert client.restrict_chat_member.await_args.args[2].can_send_messages is True
    await ctx.actions.dispatch(client,query)
    assert client.restrict_chat_member.await_count==2


@pytest.mark.asyncio
async def test_unmute_button_denies_member_and_wrong_chat_without_mutation(tmp_path):
    ctx,client,message=setup(tmp_path,'/mute 22 2m')
    ctx.actions=ActionRouter()
    message.reply=AsyncMock(return_value=NS(id=500))
    await moderation.build(ctx)[1]['mute'](client,message)
    data=message.reply.await_args.kwargs['reply_markup'].inline_keyboard[0][0].callback_data
    query=NS(data=data,from_user=NS(id=33),message=NS(id=500,chat=NS(id=-999,type=message.chat.type)),answer=AsyncMock())
    await ctx.actions.dispatch(client,query)
    assert client.restrict_chat_member.await_count==1
    query.message.chat=message.chat
    client.get_chat_member=AsyncMock(return_value=NS(status='member',privileges=None))
    await ctx.actions.dispatch(client,query)
    assert client.restrict_chat_member.await_count==1


def test_mute_permissions_encode_every_send_flag_as_denied():
    from agent.modules.moderation import MUTE_PERMISSIONS
    raw=MUTE_PERMISSIONS.write()
    assert raw.send_plain and raw.send_audios and raw.send_docs and raw.send_photos
    assert raw.send_videos and raw.send_roundvideos and raw.send_voices and raw.send_polls
    assert MUTE_PERMISSIONS.can_send_media_messages is None


@pytest.mark.asyncio
async def test_unmute_control_does_not_lift_newer_restriction(tmp_path):
    from pyrogram.enums import ChatMemberStatus
    from datetime import timedelta
    ctx,client,message=setup(tmp_path,'/mute 22 2m')
    ctx.actions=ActionRouter()
    message.reply=AsyncMock(return_value=NS(id=500))
    await moderation.build(ctx)[1]['mute'](client,message)
    until=client.restrict_chat_member.await_args.kwargs['until_date']
    data=message.reply.await_args.kwargs['reply_markup'].inline_keyboard[0][0].callback_data
    old=client.get_chat_member.side_effect
    async def changed(chat,uid):
        if uid==22:
            return NS(status=ChatMemberStatus.RESTRICTED,until_date=until+timedelta(hours=1))
        return await old(chat,uid)
    client.get_chat_member=AsyncMock(side_effect=changed)
    query=NS(data=data,from_user=NS(id=11),message=NS(id=500,chat=message.chat),answer=AsyncMock())
    await ctx.actions.dispatch(client,query)
    assert client.restrict_chat_member.await_count==1
    assert 'changed' in query.answer.await_args.args[0]


@pytest.mark.asyncio
async def test_unmute_command_username_rich_card_and_false_ack(tmp_path):
    ctx,client,message=setup(tmp_path,'/unmute @target')
    client.get_chat=AsyncMock(return_value=NS(permissions=NS(can_send_messages=True)))
    await moderation.build(ctx)[1]['unmute'](client,message)
    client.get_users.assert_awaited_once_with('@target')
    assert 'Member unmuted' in str(message.replies[-1])
    assert 'Telegram confirmed' in str(message.replies[-1])
    client.restrict_chat_member=AsyncMock(return_value=False)
    await moderation.build(ctx)[1]['unmute'](client,message)
    assert 'Unmute unconfirmed' in str(message.replies[-1])


@pytest.mark.asyncio
async def test_expired_unmute_button_cannot_mutate(tmp_path):
    ctx,client,message=setup(tmp_path,'/mute 22 2m')
    ctx.actions=ActionRouter()
    message.reply=AsyncMock(return_value=NS(id=500))
    await moderation.build(ctx)[1]['mute'](client,message)
    data=message.reply.await_args.kwargs['reply_markup'].inline_keyboard[0][0].callback_data
    for entry in ctx._mute_undo_entries.values():
        entry['expires']=0
    query=NS(data=data,from_user=NS(id=11),message=NS(id=500,chat=message.chat),answer=AsyncMock())
    await ctx.actions.dispatch(client,query)
    assert client.restrict_chat_member.await_count==1
    assert 'expired' in query.answer.await_args.args[0]


@pytest.mark.asyncio
@pytest.mark.parametrize('stage', ['answer', 'card'])
@pytest.mark.parametrize('failure', [RuntimeError, TimeoutError, 'cancel'])
async def test_confirmed_unmute_callback_does_not_claim_uncertainty_on_notification_failure(tmp_path, stage, failure, caplog):
    import asyncio
    from pyrogram.enums import ChatMemberStatus
    ctx, client, message = setup(tmp_path, '/mute 22 2m')
    ctx.actions = ActionRouter()
    message.reply = AsyncMock(return_value=NS(id=500))
    client.get_chat = AsyncMock(return_value=NS(permissions=NS(can_send_messages=True)))
    await moderation.build(ctx)[1]['mute'](client, message)
    until = client.restrict_chat_member.await_args.kwargs['until_date']
    data = message.reply.await_args.kwargs['reply_markup'].inline_keyboard[0][0].callback_data
    old = client.get_chat_member.side_effect
    async def current(chat, uid):
        if uid == 22:
            return NS(status=ChatMemberStatus.RESTRICTED, until_date=until)
        return await old(chat, uid)
    client.get_chat_member = AsyncMock(side_effect=current)
    error = asyncio.CancelledError() if failure == 'cancel' else failure('SECRET_NOTIFICATION_TEXT')
    query = NS(data=data, from_user=NS(id=11),
        message=NS(id=500, chat=message.chat, reply=AsyncMock()), answer=AsyncMock())
    target = query.answer if stage == 'answer' else query.message.reply
    target.side_effect = error
    if failure == 'cancel':
        with pytest.raises(asyncio.CancelledError):
            await ctx.actions.dispatch(client, query)
    else:
        await ctx.actions.dispatch(client, query)
    query.answer.assert_awaited_once_with('Unmute confirmed by Telegram.')
    assert query.message.reply.await_count == (1 if stage == 'card' else 0)
    assert client.restrict_chat_member.await_count == 2
    assert not ctx._mute_undo_entries
    assert ctx.chats.history(message.chat.id)[0]['action'] == 'unmute'
    assert 'SECRET_NOTIFICATION_TEXT' not in caplog.text
    query.answer.side_effect = None
    await ctx.actions.dispatch(client, query)
    assert client.restrict_chat_member.await_count == 2
