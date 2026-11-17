"""Admin statistics use real current counts and group-scoped recorded history."""
from types import SimpleNamespace as NS
from unittest.mock import AsyncMock
import pytest
import test_group as fixtures
from agent.modules import group


@pytest.mark.asyncio
async def test_userstats_reads_live_group_count(tmp_path):
    ctx=fixtures.ctx.__wrapped__(tmp_path)
    ctx.monitor=NS(snapshot=lambda:NS(uptime_seconds=125))
    client=fixtures.FakeClient()
    client.get_chat_members_count=AsyncMock(return_value=42)
    item=fixtures.FakeMessage('/userstats')
    await group.build(ctx)[1]['userstats'](client,item)
    client.get_chat_members_count.assert_awaited_once_with(item.chat.id)
    text=str(item.replies[-1])
    assert '42' in text and '2m' in text and 'live' in text.lower()


@pytest.mark.asyncio
async def test_denied_stats_never_read_counts(tmp_path):
    ctx=fixtures.ctx.__wrapped__(tmp_path)
    client=fixtures.FakeClient(caller=fixtures.MEMBER)
    client.get_chat_members_count=AsyncMock()
    commands=group.build(ctx)[1]
    for name in ('userstats','recentactivity'):
        item=fixtures.FakeMessage('/'+name)
        await commands[name](client,item)
        assert 'permission' in str(item.replies[-1]).lower()
    client.get_chat_members_count.assert_not_awaited()


@pytest.mark.asyncio
async def test_activity_scopes_and_does_not_expose_reasons(tmp_path):
    ctx=fixtures.ctx.__wrapped__(tmp_path)
    ctx.chats.log(fixtures.CHAT,'warn',actor_id=11,target_id=22,reason='PRIVATE_REASON')
    ctx.chats.log(-200,'SECRET_OTHER_GROUP',actor_id=11,reason='SECRET')
    item=fixtures.FakeMessage('/recentactivity')
    await group.build(ctx)[1]['recentactivity'](fixtures.FakeClient(),item)
    text=str(item.replies[-1])
    assert 'warn' in text and 'PRIVATE_REASON' not in text and 'SECRET' not in text
    assert 'complete' in text.lower()


@pytest.mark.asyncio
async def test_failed_count_never_uses_fake_zero(tmp_path):
    ctx=fixtures.ctx.__wrapped__(tmp_path)
    client=fixtures.FakeClient()
    client.get_chat_members_count=AsyncMock(side_effect=RuntimeError('SECRET'))
    item=fixtures.FakeMessage('/userstats')
    await group.build(ctx)[1]['userstats'](client,item)
    assert 'unavailable' in str(item.replies[-1]).lower() and 'SECRET' not in str(item.replies[-1])


@pytest.mark.asyncio
async def test_stats_invalid_args_rejected_before_live_count(tmp_path):
    ctx=fixtures.ctx.__wrapped__(tmp_path)
    client=fixtures.FakeClient()
    client.get_chat_members_count=AsyncMock()
    commands=group.build(ctx)[1]
    for name in ('userstats','recentactivity'):
        item=fixtures.FakeMessage('/'+name+' -200')
        await commands[name](client,item)
        assert 'Usage' in str(item.replies[-1])
    client.get_chat_members_count.assert_not_awaited()


@pytest.mark.asyncio
async def test_recent_activity_escapes_action_names(tmp_path):
    ctx=fixtures.ctx.__wrapped__(tmp_path)
    ctx.chats.log(fixtures.CHAT,'<script>action</script>',actor_id=11)
    item=fixtures.FakeMessage('/recentactivity')
    await group.build(ctx)[1]['recentactivity'](fixtures.FakeClient(),item)
    assert '<script>' not in str(item.replies[-1])
    assert '&lt;script&gt;' in str(item.replies[-1])
