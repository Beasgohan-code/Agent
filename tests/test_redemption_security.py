import asyncio
from types import SimpleNamespace as NS
from unittest.mock import AsyncMock
from agent.modules import linkshare
from agent.platform.deeplinks import DeepLinkRouter
from test_plugins import make_ctx
from pyrogram.enums import ChatType


def request(text, uid, mid):
    return NS(text=text, id=mid, from_user=NS(id=uid),
              chat=NS(id=uid, type=ChatType.PRIVATE), reply=AsyncMock())


def test_duplicate_update_and_delivery_failure_do_not_redeem_again(tmp_path, monkeypatch, caplog):
    async def scenario():
        ctx = make_ctx(tmp_path)
        ctx.deeplinks = DeepLinkRouter()
        grant = ctx.links.create('file', 11)
        ctx.storage = NS(get=lambda _: NS(name='SECRET_FILENAME', size=1))
        delivery = AsyncMock(side_effect=RuntimeError('SECRET_DELIVERY'))
        monkeypatch.setattr(linkshare, 'send_stored', delivery)
        linkshare.build(ctx)
        msg = request('/start', 22, 17)
        msg.reply.side_effect = RuntimeError('SECRET_REPLY')
        for _ in range(2):
            assert await ctx.deeplinks.dispatch(None, msg, 'link_' + grant.token)
        delivery.assert_awaited_once()
        assert ctx.links.get(grant.token).uses == 1
        assert grant.token not in caplog.text
        assert 'SECRET' not in caplog.text
    asyncio.run(scenario())


def test_expired_token_does_not_claim_or_deliver(tmp_path, monkeypatch, caplog):
    async def scenario():
        ctx = make_ctx(tmp_path)
        ctx.deeplinks = DeepLinkRouter()
        grant = ctx.links.create('file', 11, ttl_hours=0)
        delivery = AsyncMock()
        monkeypatch.setattr(linkshare, 'send_stored', delivery)
        linkshare.build(ctx)
        msg = request('/start', 22, 18)
        await ctx.deeplinks.dispatch(None, msg, 'link_' + grant.token)
        delivery.assert_not_awaited()
        assert ctx.links.get(grant.token).uses == 0
        assert 'expired' in str(msg.reply.await_args.args[0])
        assert grant.token not in caplog.text
    asyncio.run(scenario())
