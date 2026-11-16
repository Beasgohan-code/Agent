"""Greeting SQL durability, isolation and atomic toggle semantics."""
import asyncio
import os
import uuid
from types import SimpleNamespace

import pytest

from agent.platform.db import Database
from agent.platform.greetings import Greetings
from agent.modules import welcome
import test_groups
from test_groups import FakeClient, FakeMessage, update, MEMBER, LEFT


def test_database_outage_refuses_settings_and_event_fallback(tmp_path):
    async def scenario():
        ctx = test_groups.ctx.__wrapped__(tmp_path)
        ctx.chats.set_greeting(-100900, 'welcome', 'stale legacy')
        ctx.db = SimpleNamespace(connected=False, _pool=None)
        _, commands = welcome.build(ctx)
        for name, text in [('setwelcome', 'new'), ('welcome', 'off'), ('welcome', ''), ('goodbye', 'Bye')]:
            request = FakeMessage('/' + name + (' ' + text if text else ''))
            await commands[name](FakeClient(), request)
            assert 'unconfirmed' in request.replies[-1]
        assert ctx.chats.greeting(-100900, 'welcome')['text'] == 'stale legacy'
        client = FakeClient()
        await welcome.watch(ctx)(client, update(new_status=MEMBER, old_status=LEFT))
        assert not client.calls
    asyncio.run(scenario())


@pytest.mark.skipif(not os.getenv('AGENT_TEST_DATABASE_URL'), reason='Disposable PostgreSQL required')
def test_restart_isolation_and_stale_toggle_preserves_sql_text():
    async def scenario():
        scope = 'greetings-test:' + uuid.uuid4().hex
        db = Database(os.environ['AGENT_TEST_DATABASE_URL'], scope=scope)
        clone = Database(os.environ['AGENT_TEST_DATABASE_URL'], scope=scope + ':clone')
        legacy = dict(text='legacy', enabled=True)
        try:
            assert await db.connect() and await clone.connect()
            service = Greetings(db)
            assert await service.get(-100, 'welcome', legacy) == legacy
            await service.toggle(-100, 'welcome', False, legacy)
            assert await service.get(-100, 'welcome', legacy) == dict(text='legacy', enabled=False)
            await service.set(-100, 'welcome', 'fresh\nlayout')
            row = await service.toggle(-100, 'welcome', False, dict(text='stale', enabled=True))
            assert row == dict(text='fresh\nlayout', enabled=False)
            # Repeated parallel toggles cannot replace text with stale caller state.
            await asyncio.gather(*(service.toggle(-100, 'welcome', bool(i % 2), legacy) for i in range(8)))
            assert (await service.get(-100, 'welcome', legacy))['text'] == 'fresh\nlayout'
            assert await service.get(-200, 'welcome', legacy) == legacy
            assert await service.get(-100, 'goodbye', legacy) == legacy
            assert await Greetings(clone).get(-100, 'welcome', legacy) == legacy
            await service.toggle(-100, 'welcome', False, legacy)
            await db.close()
            assert await db.connect()
            assert await service.get(-100, 'welcome', legacy) == dict(text='fresh\nlayout', enabled=False)
            with pytest.raises(ValueError):
                await service.set(-100, 'welcome', 'x'*1501)
            with pytest.raises(ValueError):
                await service.get(-100, 'invalid', legacy)
        finally:
            if db.connected:
                async with db._pool.acquire() as conn:
                    await conn.execute('DELETE FROM agent_greetings WHERE tenant=$1 OR tenant=$2', scope, scope + ':clone')
            await db.close()
            await clone.close()
    asyncio.run(scenario())
