"""Language preference storage and authorized paginated picker."""
import os
import uuid
from types import SimpleNamespace as NS
from unittest.mock import AsyncMock
import pytest
from test_mute_target_parity import setup
from agent.modules import core
from agent.platform.actions import ActionRouter
from pyrogram.enums import ChatType


@pytest.mark.asyncio
async def test_language_list_and_private_selection(tmp_path):
    from agent.platform.languages import LANGUAGES,preference
    assert len(LANGUAGES)==100 and len(dict(LANGUAGES))==100
    ctx,client,message=setup(tmp_path,'/lang')
    ctx.actions=ActionRouter()
    message.chat=NS(id=message.from_user.id,type=ChatType.PRIVATE)
    message.reply=AsyncMock(return_value=NS(id=10))
    commands=core.build(ctx)[1]
    await commands['lang'](client,message)
    keyboard=message.reply.call_args.kwargs['reply_markup']
    assert 1<len(keyboard.inline_keyboard)<=9
    query=NS(from_user=message.from_user,message=message,data=f'lang:{message.from_user.id}:{message.chat.id}:set:ml',answer=AsyncMock())
    message.edit_text=AsyncMock()
    assert await ctx.actions.dispatch(client,query)
    assert await preference(ctx,message.chat.id)=='ml'
    assert 'മലയാളം' in str(message.edit_text.call_args)
    query.from_user=NS(id=999)
    query.data=f'lang:{message.from_user.id}:{message.chat.id}:set:ta'
    await ctx.actions.dispatch(client,query)
    assert await preference(ctx,message.chat.id)=='ml'


@pytest.mark.asyncio
async def test_group_language_requires_current_manage_chat_and_valid_payload(tmp_path):
    import test_moderation as fixtures
    from agent.platform.languages import preference
    ctx,client,message=setup(tmp_path,'/lang')
    ctx.actions=ActionRouter()
    core.build(ctx)
    query=NS(from_user=message.from_user,message=message,data=f'lang:11:{message.chat.id}:set:hi',answer=AsyncMock())
    message.edit_text=AsyncMock()
    client.get_chat_member=AsyncMock(side_effect=[fixtures.member(fixtures.ADMIN),fixtures.member(fixtures.MEMBER)])
    await ctx.actions.dispatch(client,query)
    assert await preference(ctx,message.chat.id)=='en'
    client.get_chat_member=AsyncMock(return_value=fixtures.member(fixtures.ADMIN))
    for rest in [f'11:{message.chat.id}:set:fake',f'11:{message.chat.id}:page:999','11:-999:set:hi']:
        query.data='lang:'+rest
        await ctx.actions.dispatch(client,query)
    assert await preference(ctx,message.chat.id)=='en'


@pytest.mark.asyncio
async def test_pg_language_preferences_restart_isolation_and_no_fallback(tmp_path):
    from agent.platform.languages import preference,LanguageError
    from agent.platform.db import Database
    url=os.environ.get('AGENT_TEST_DATABASE_URL')
    if not url:
        pytest.skip('PostgreSQL required')
    scope='language:'+uuid.uuid4().hex
    db=Database(url,scope=scope,required=True)
    assert await db.connect()
    ctx=NS(db=db)
    try:
        assert await preference(ctx,11)=='en'
        await preference(ctx,11,code='ta',actor=11)
        await preference(ctx,-100,code='ml',actor=11)
        second=Database(url,scope=scope,required=True)
        assert await second.connect()
        try:
            assert await preference(NS(db=second),11)=='ta'
            assert await preference(NS(db=second),-100)=='ml'
            assert await preference(NS(db=second),-200)=='en'
        finally:
            await second.close()
        other=Database(url,scope=scope+':other',required=True)
        assert await other.connect()
        try:
            assert await preference(NS(db=other),11)=='en'
        finally:
            await other.close()
        with pytest.raises(LanguageError):
            await preference(ctx,11,code='hi',actor=22)
    finally:
        await db.close()
    with pytest.raises(LanguageError):
        await preference(ctx,11)


@pytest.mark.asyncio
async def test_all_100_language_buttons_are_reachable_and_fallback_is_explicit(tmp_path):
    from agent.platform.languages import LANGUAGES,preference
    ctx,client,message=setup(tmp_path,'/lang')
    ctx.actions=ActionRouter()
    message.chat=NS(id=11,type=ChatType.PRIVATE)
    message.edit_text=AsyncMock()
    core.build(ctx)
    seen=set()
    query=NS(from_user=message.from_user,message=message,answer=AsyncMock())
    for page in range(9):
        query.data=f'lang:11:11:page:{page}'
        await ctx.actions.dispatch(client,query)
        keyboard=message.edit_text.call_args.kwargs['reply_markup']
        for row in keyboard.inline_keyboard:
            for button in row:
                if ':set:' in button.callback_data:
                    seen.add(button.callback_data.rsplit(':',1)[1])
                assert len(button.callback_data.encode())<=64
    assert seen=={code for code,_ in LANGUAGES}
    query.data='lang:11:11:set:fr'
    await ctx.actions.dispatch(client,query)
    assert await preference(ctx,11)=='fr'
    assert 'English fallback' in str(message.edit_text.call_args)
