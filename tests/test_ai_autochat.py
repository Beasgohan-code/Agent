"""Opt-in AI triggers and execution authority; no live provider calls."""
import asyncio
from types import SimpleNamespace as NS
from unittest.mock import AsyncMock

import pytest
from pyrogram.enums import ChatType, ChatMemberStatus
from agent.modules import ai_agent
from agent.platform.chats import ChatStore
from agent.platform.execution import PluginGate
from agent.platform.jobs import JobQueue


def setup(tmp_path):
    ctx = NS(settings=NS(ai_api_key='test-key', ai_model='model'), chats=ChatStore(tmp_path), db=None)
    commands = ai_agent.build(ctx)[1]
    client = NS(me=NS(id=99, username='MeikoBot'), get_chat_member=AsyncMock(return_value=NS(status=ChatMemberStatus.ADMINISTRATOR)))
    return ctx, commands, client


def message(text, group=False, uid=22):
    return NS(text=text, chat=NS(id=-100 if group else uid, type=ChatType.SUPERGROUP if group else ChatType.PRIVATE),
              from_user=NS(id=uid, is_bot=False), reply=AsyncMock())


def test_private_auto_chat_requires_optin_and_reuses_secret_filter_and_cooldown(tmp_path, monkeypatch):
    async def scenario():
        provider = AsyncMock(return_value='answer')
        monkeypatch.setattr(ai_agent, 'complete', provider)
        ctx, commands, client = setup(tmp_path)
        await ctx.ai_autochat_handler(client, message('hello'))
        provider.assert_not_awaited()
        enable = message('/autochat on')
        await commands['autochat'](client, enable)
        assert 'external AI provider' in str(enable.reply.await_args.args[0])
        for text in ('/premium', '!help', '111111111:AAHfakeTokenValueForTests_aaaaaaaa'):
            await ctx.ai_autochat_handler(client, message(text))
        provider.assert_not_awaited()
        await ctx.ai_autochat_handler(client, message('hello'))
        provider.assert_awaited_once_with('test-key', 'model', 'hello')
        await ctx.ai_autochat_handler(client, message('again'))
        assert provider.await_count == 1
        await commands['autochat'](client, message('/autochat off'))
        await ctx.ai_autochat_handler(client, message('disabled'))
        assert provider.await_count == 1
    asyncio.run(scenario())


@pytest.mark.parametrize('trigger', ['mention', 'reply'])
def test_group_only_direct_triggers_send_current_message_not_history(tmp_path, monkeypatch, trigger):
    async def scenario():
        provider = AsyncMock(return_value='answer')
        monkeypatch.setattr(ai_agent, 'complete', provider)
        ctx, commands, client = setup(tmp_path)
        await commands['autochat'](client, message('/autochat on', group=True))
        for text in ('ordinary group chat', 'mail@MeikoBot.example', '@MeikoBotExtra hi'):
            await ctx.ai_autochat_handler(client, message(text, group=True))
        provider.assert_not_awaited()
        request = message('@MeikoBot hello' if trigger == 'mention' else 'hello', group=True)
        if trigger == 'reply':
            request.reply_to_message = NS(text='private previous context', from_user=NS(id=99))
        await ctx.ai_autochat_handler(client, request)
        provider.assert_awaited_once_with('test-key', 'model', 'hello')
    asyncio.run(scenario())


def test_nonadmin_and_unapproved_group_cannot_enable_or_execute(tmp_path, monkeypatch):
    async def scenario():
        provider = AsyncMock(return_value='answer')
        monkeypatch.setattr(ai_agent, 'complete', provider)
        ctx, commands, client = setup(tmp_path)
        client.get_chat_member.return_value.status = ChatMemberStatus.MEMBER
        await commands['autochat'](client, message('/autochat on', group=True))
        assert ctx.chats.get(-100, 'ai_autochat', False) is False
        ctx.chats.put(-100, 'ai_autochat', True)
        runtime = NS(wants_disabled=lambda slug: False, registry=NS(is_enabled=lambda slug: True))
        access = NS(eligible=AsyncMock(return_value=False))
        gate = PluginGate(access, runtime, JobQueue())
        callback = gate.wrap('ai_agent', ctx.ai_autochat_handler, silent=True)
        await callback(client, message('@MeikoBot hello', group=True))
        provider.assert_not_awaited()
        access.eligible.return_value = True
        await callback(client, message('@MeikoBot hello', group=True))
        provider.assert_awaited_once()
    asyncio.run(scenario())


@pytest.mark.parametrize('field,value', [('via_bot', NS(id=44)), ('forward_origin', NS()), ('service', True), ('sender_chat', NS(id=-444))])
def test_forwarded_bot_and_service_sources_are_not_auto_uploaded(tmp_path, monkeypatch, field, value):
    async def scenario():
        provider = AsyncMock(return_value='answer')
        monkeypatch.setattr(ai_agent, 'complete', provider)
        ctx, commands, client = setup(tmp_path)
        await commands['autochat'](client, message('/autochat on'))
        request = message('private source content')
        setattr(request, field, value)
        await ctx.ai_autochat_handler(client, request)
        request = message('another bot message')
        request.from_user.is_bot = True
        await ctx.ai_autochat_handler(client, request)
        provider.assert_not_awaited()
    asyncio.run(scenario())
