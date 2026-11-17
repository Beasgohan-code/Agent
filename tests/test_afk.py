"""AFK is self-owned, group/tenant-scoped and cooldown-bound in PostgreSQL."""
import os
import uuid
import asyncio
from types import SimpleNamespace as NS
from unittest.mock import AsyncMock
import pytest
from pyrogram.enums import ChatType
from agent.platform.db import Database


@pytest.mark.asyncio
async def test_pg_afk_toggle_replay_scope_and_notice_cooldown():
    from agent.platform.afk import toggle, clear, notice, AFKError
    if not os.environ.get('AGENT_TEST_DATABASE_URL'):
        pytest.skip('PostgreSQL required')
    db=Database(os.environ['AGENT_TEST_DATABASE_URL'],scope='afk:'+uuid.uuid4().hex,required=True)
    assert await db.connect()
    ctx=NS(db=db)
    try:
        assert await toggle(ctx,-100,22,1,'<away>')
        other=Database(os.environ['AGENT_TEST_DATABASE_URL'],scope=db.scope+':clone',required=True)
        assert await other.connect()
        try:
            otherctx=NS(db=other)
            assert await notice(otherctx,-100,22) is None
            assert await toggle(otherctx,-100,22,1,'other bot')
            assert await clear(otherctx,-100,22)
        finally:
            await other.close()
        with pytest.raises(AFKError):
            await toggle(ctx,-100,22,1,'replay')
        assert await notice(ctx,-200,22) is None
        results=await asyncio.gather(*(notice(ctx,-100,22) for _ in range(5)))
        assert sum(result is not None for result in results)==1
        assert next(result for result in results if result)['reason']=='<away>'
        assert await clear(ctx,-100,33) is False
        assert await clear(ctx,-100,22) is True
        assert await notice(ctx,-100,22) is None
        assert await toggle(ctx,-100,22,2,'again')
        assert not await toggle(ctx,-100,22,3,'toggle off')
    finally:
        await db.close()


@pytest.mark.asyncio
async def test_afk_bad_identity_refused_before_storage():
    from agent.modules.group.afk import build
    message=NS(text='/afk',chat=NS(id=-100,type=ChatType.SUPERGROUP),from_user=None,reply=AsyncMock())
    await build(NS())(None,message)
    assert 'personal' in str(message.reply.await_args.args[0]).lower()


@pytest.mark.asyncio
async def test_watcher_clears_self_and_notifies_replied_afk_user():
    from unittest.mock import patch
    from agent.modules.group.afk import watch
    from agent.ui.theme import Theme
    message=NS(text='hello',chat=NS(id=-100,type=ChatType.SUPERGROUP),from_user=NS(id=33,is_bot=False),reply_to_message=NS(from_user=NS(id=22)),entities=[],reply=AsyncMock())
    with patch('agent.modules.group.afk.clear',AsyncMock(return_value=False)) as clear,patch('agent.modules.group.afk.notice',AsyncMock(return_value={'reason':'<away>','seconds':125})) as notice:
        await watch(NS(theme=Theme({})))(None,message)
        clear.assert_awaited_once()
        assert notice.await_args.args[1:]==(-100,22)
        text=str(message.reply.await_args.args[0])
        assert '&lt;away&gt;' in text and '<away>' not in text


@pytest.mark.asyncio
async def test_watcher_skips_all_prefix_commands():
    from unittest.mock import patch
    from agent.modules.group.afk import watch
    for prefix in '/!.#$%&?':
        with patch('agent.modules.group.afk.clear',AsyncMock()) as clear:
            await watch(NS())(None,NS(text=prefix+'help',chat=NS(id=-100,type=ChatType.SUPERGROUP),from_user=NS(id=22,is_bot=False)))
            clear.assert_not_awaited()


@pytest.mark.asyncio
async def test_watcher_resolves_current_username_with_bounded_lookup():
    from unittest.mock import patch
    from pyrogram.enums import MessageEntityType
    from agent.modules.group.afk import watch
    message=NS(text='hi @target',chat=NS(id=-100,type=ChatType.SUPERGROUP),from_user=NS(id=33,is_bot=False),entities=[NS(type=MessageEntityType.MENTION,offset=3,length=7)],reply=AsyncMock())
    client=NS(get_users=AsyncMock(return_value=NS(id=22)))
    ctx=NS()
    with patch('agent.modules.group.afk.clear',AsyncMock()),patch('agent.modules.group.afk.notice',AsyncMock(return_value=None)) as notice:
        await watch(ctx)(client,message)
        client.get_users.assert_awaited_once_with('@target')
        notice.assert_awaited_once_with(ctx,-100,22)


@pytest.mark.asyncio
async def test_pg_afk_fails_closed_without_database():
    from agent.platform.afk import toggle,AFKError
    with pytest.raises(AFKError,match='unavailable'):
        await toggle(NS(db=None),-100,22,1,'away')
