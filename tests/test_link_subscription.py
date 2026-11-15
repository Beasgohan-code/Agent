import asyncio
from types import SimpleNamespace as NS
from unittest.mock import AsyncMock
import pytest
from pyrogram.enums import ChatMemberStatus as Status, ChatType
from agent.modules import linkshare
from agent.modules.linkshare.subscription import DOCUMENT, build, member_allowed
from agent.platform.deeplinks import DeepLinkRouter
from test_plugins import make_ctx
from test_archive_links import request


class PolicyDB:
    connected = True
    def __init__(self):
        self.policy = {}
        self.flush = AsyncMock(return_value=1)
    def get(self, key, default=None):
        assert key == DOCUMENT
        return self.policy
    def save(self, key, value):
        assert key == DOCUMENT
        self.policy = value


@pytest.mark.parametrize('status,ismember,expected', [
    (Status.MEMBER, False, True), (Status.ADMINISTRATOR, False, True),
    (Status.OWNER, False, True), (Status.LEFT, True, False),
    (Status.BANNED, True, False), (Status.RESTRICTED, True, True),
    (Status.RESTRICTED, False, False)])
def test_subscription_requires_actual_membership(status, ismember, expected):
    assert member_allowed(NS(status=status, is_member=ismember)) is expected


def test_subscription_configuration_checks_owner_channel_and_persistence(tmp_path):
    async def scenario():
        ctx = make_ctx(tmp_path); ctx.db = PolicyDB()
        command = build(ctx)
        client = NS(get_chat=AsyncMock(return_value=NS(type=ChatType.CHANNEL)),
                    get_chat_member=AsyncMock(return_value=NS(status=Status.ADMINISTRATOR)))
        denied = request('/linkchannel -100123'); denied.from_user.id = 99; denied.chat.id = 99
        await command(client, denied)
        client.get_chat.assert_not_awaited()
        await command(client, request('/linkchannel -100123'))
        assert ctx.db.policy == {'channel': -100123}
        ctx.db.flush.return_value = 0
        failed = request('/linkchannel off')
        await command(client, failed)
        assert ctx.db.policy == {'channel': -100123}
        assert 'not confirmed' in failed.reply.await_args.args[0]
        client.get_chat_member.side_effect = RuntimeError('private API secret')
        bad = request('/linkchannel -100456')
        await command(client, bad)
        assert ctx.db.policy == {'channel': -100123}
        assert 'private API secret' not in bad.reply.await_args.args[0]
    asyncio.run(scenario())


def test_redemption_checks_subscription_before_consuming_or_delivering(tmp_path, monkeypatch):
    async def scenario():
        ctx = make_ctx(tmp_path); ctx.db = PolicyDB(); ctx.db.policy = {'channel': -100123}
        ctx.deeplinks = DeepLinkRouter()
        file = NS(name='entry.txt', size=3)
        record = NS(file_id='owned-file', token='token', max_uses=2, remaining=1, uses=1)
        ctx.links = NS(aresolve=AsyncMock(return_value=record), aconsume=AsyncMock(return_value=record))
        ctx.storage = NS(get=lambda key: file)
        deliver = AsyncMock(return_value=True); monkeypatch.setattr(linkshare, 'send_stored', deliver)
        linkshare.build(ctx)
        client = NS(get_chat_member=AsyncMock(return_value=NS(status=Status.LEFT)))
        msg = request('/start link_token')
        await ctx.deeplinks.dispatch(client, msg, 'link_token')
        ctx.links.aconsume.assert_not_awaited(); deliver.assert_not_awaited()
        client.get_chat_member.return_value = NS(status=Status.MEMBER)
        await ctx.deeplinks.dispatch(client, msg, 'link_token')
        ctx.links.aconsume.assert_awaited_once_with('token'); deliver.assert_awaited_once()
        ctx.links.aconsume.reset_mock(); ctx.db.connected = False
        await ctx.deeplinks.dispatch(client, msg, 'link_token')
        ctx.links.aconsume.assert_not_awaited()
    asyncio.run(scenario())


def test_membership_api_errors_and_malformed_policy_fail_closed(tmp_path):
    from agent.modules.linkshare.subscription import allowed
    async def scenario():
        ctx = make_ctx(tmp_path); ctx.db = PolicyDB()
        ctx.db.policy = {'channel': -100123}
        client = NS(get_chat_member=AsyncMock(side_effect=RuntimeError('private provider secret')))
        msg = request('/start link_token')
        assert not await allowed(ctx, client, msg)
        assert 'private provider secret' not in msg.reply.await_args.args[0]
        for value in ({'channel': '-100123'}, {'channel': True}, {'channel': 123}, ['invalid']):
            ctx.db.policy = value
            assert not await allowed(ctx, client, msg)
        ctx.db.policy = {'channel': None}
        assert await allowed(ctx, client, msg)
    asyncio.run(scenario())


def test_multiple_required_channels_validate_atomically_and_require_all_memberships(tmp_path):
    from agent.modules.linkshare.subscription import allowed
    async def scenario():
        ctx = make_ctx(tmp_path); ctx.db = PolicyDB()
        client = NS(get_chat=AsyncMock(return_value=NS(type=ChatType.CHANNEL)),
                    get_chat_member=AsyncMock(return_value=NS(status=Status.ADMINISTRATOR)))
        command = build(ctx)
        await command(client, request('/linkchannel -100123 -100456'))
        assert ctx.db.policy == {'channels': [-100123, -100456]}
        async def membership(channel, uid):
            return NS(status=Status.MEMBER if channel == -100123 else Status.LEFT)
        client.get_chat_member.side_effect = membership
        msg = request('/start link_token')
        assert not await allowed(ctx, client, msg)
        assert '-100456' in msg.reply.await_args.args[0]
        assert '-100123' not in msg.reply.await_args.args[0]
        old = ctx.db.policy
        await command(client, request('/linkchannel -100789 -100999'))
        assert ctx.db.policy == old
        await command(client, request('/linkchannel -100123 -100123'))
        assert ctx.db.policy == old
        client.get_chat_member.side_effect = None
        client.get_chat_member.return_value = NS(status=Status.MEMBER)
        assert await allowed(ctx, client, msg)
        await command(client, request('/linkchannel off'))
        assert ctx.db.policy == {'channels': []}
        assert await allowed(ctx, client, msg)
    asyncio.run(scenario())


def test_denied_members_get_only_verified_public_channel_buttons(tmp_path):
    from agent.modules.linkshare.subscription import allowed
    async def scenario():
        ctx = make_ctx(tmp_path); ctx.db = PolicyDB()
        ctx.db.policy = {'channels': [-100123, -100456]}
        async def chat(channel):
            return NS(id=channel, type=ChatType.CHANNEL,
                      username='PublicChannel' if channel == -100123 else 'https://evil.invalid')
        client = NS(get_chat_member=AsyncMock(return_value=NS(status=Status.LEFT)),
                    get_chat=AsyncMock(side_effect=chat))
        msg = request('/start link_token')
        assert not await allowed(ctx, client, msg)
        rows = msg.reply.await_args.kwargs['reply_markup'].inline_keyboard
        assert len(rows) == 1 and rows[0][0].url == 'https://t.me/PublicChannel'
        client.get_chat.side_effect = None
        client.get_chat.return_value = NS(id=-999, type=ChatType.CHANNEL, username='WrongChannel')
        other = request('/start link_token')
        assert not await allowed(ctx, client, other)
        assert 'reply_markup' not in other.reply.await_args.kwargs
    asyncio.run(scenario())


def test_stalled_membership_times_out_without_spending_access(tmp_path, monkeypatch):
    from agent.modules.linkshare import subscription
    async def scenario():
        ctx = make_ctx(tmp_path); ctx.db = PolicyDB(); ctx.db.policy = {'channel': -100123}
        monkeypatch.setattr(subscription, 'API_TIMEOUT', 0.01)
        async def stalled(*args):
            await asyncio.Event().wait()
        client = NS(get_chat_member=stalled, get_chat=stalled)
        msg = request('/start link_token')
        assert not await asyncio.wait_for(subscription.allowed(ctx, client, msg), timeout=1)
        assert 'no link use was spent' in msg.reply.await_args.args[0]
    asyncio.run(scenario())
