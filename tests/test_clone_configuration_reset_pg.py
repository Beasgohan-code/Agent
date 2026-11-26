"""Owner-only channel reset uses canonical CAS and lifecycle fencing."""
import asyncio
import os
import uuid
import pytest
from agent.modules.clone.configuration import ConfigurationWriteError
from agent.modules.clone.control_centre import CloneControlCentre
from agent.modules.clone.manager import CloneManager
from agent.modules.clone.store import Clone, CloneStore
from agent.platform.db import Database
from agent.platform.secrets import SecretBox
from test_atomic_clones import KEY
from test_clone import build, MEMBER, OWNER, TOKEN_A, TOKEN_B
from test_clone_control_centre import private_query

pytestmark = pytest.mark.skipif(not os.environ.get('AGENT_TEST_DATABASE_URL'), reason='Database required')

@pytest.mark.parametrize('field', ['log_channel', 'storage_channel'])
def test_reset_preview_save_isolated_and_stale_rejected(tmp_path, field):
    async def scenario():
        db = Database(os.environ['AGENT_TEST_DATABASE_URL'], scope='reset:' + uuid.uuid4().hex)
        assert await db.connect()
        try:
            ctx, _, _ = build(tmp_path / 'ctx')
            store = CloneStore(tmp_path, db=db, box=SecretBox(KEY))
            manager = CloneManager(ctx.settings, store)
            centre = CloneControlCentre(ctx, manager)
            a = await store.aadd(Clone(111111111, MEMBER, TOKEN_A, log_channel=-100111, storage_channel=-100222), owner_limit=3, total_limit=5)
            b = await store.aadd(Clone(222222222, MEMBER, TOKEN_B, log_channel=-100333), owner_limit=3, total_limit=5)
            suffix = f'{field}:1:{a.lifecycle_generation}'
            for actor in (OWNER, 999):
                denied = private_query(f'cc:{a.bot_id}:save:{suffix}', actor)
                await centre.press(None, denied, denied.data.split(':', 1)[1])
                assert not denied.edits and denied.answers[-1][1]
            group = private_query(f'cc:{a.bot_id}:save:{suffix}')
            group.message.chat.id = -100
            await centre.press(None, group, group.data.split(':', 1)[1])
            assert not group.edits and group.answers[-1][1]
            preview = private_query(f'cc:{a.bot_id}:reset:{suffix}')
            await centre.press(None, preview, preview.data.split(':', 1)[1])
            assert 'Preview' in preview.edits[-1][0]
            assert getattr(store.get(a.bot_id), field) is not None
            save = private_query(f'cc:{a.bot_id}:save:{suffix}')
            await centre.press(None, save, save.data.split(':', 1)[1])
            assert save.edits and 'Saved desired revision 2' in save.edits[-1][0]
            assert getattr(store.get(a.bot_id), field) is None
            assert store.get(b.bot_id).as_json() == b.as_json()
            assert (await manager.configuration.read(a.bot_id))['pending_revision'] == 2
            replay = private_query(save.data)
            await centre.press(None, replay, replay.data.split(':', 1)[1])
            assert not replay.edits and replay.answers[-1][1]
            # Authority must reject controller Owner and lifecycle mismatch at DB boundary too.
            for actor, generation in ((OWNER, a.lifecycle_generation), (MEMBER, a.lifecycle_generation + 100)):
                with pytest.raises(ConfigurationWriteError):
                    await manager.configuration.write(a.bot_id, actor_id=actor, expected_revision=2,
                        request_id='forged' + str(actor), changes={field: None}, owner_only=True, expected_generation=generation)
            await db.close()
            unavailable = private_query(f'cc:{a.bot_id}:reset:{field}:2:{a.lifecycle_generation}')
            await centre.press(None, unavailable, unavailable.data.split(':', 1)[1])
            assert not unavailable.edits and unavailable.answers[-1][1]
        finally:
            await db.close()
    asyncio.run(scenario())
