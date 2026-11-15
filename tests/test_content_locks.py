import asyncio
from types import SimpleNamespace as NS
from unittest.mock import AsyncMock
import test_moderation as fixtures
from agent.modules.moderation import locks
from agent.modules import moderation


def test_locks_multitype_persistence_and_input_permissions(tmp_path):
    async def scenario():
        ctx = fixtures.ctx.__wrapped__(tmp_path)
        commands = moderation.build(ctx)[1]
        denied = fixtures.FakeMessage('/lock gif video')
        await commands['lock'](fixtures.FakeClient(caller=fixtures.MEMBER), denied)
        assert locks.read(ctx, denied.chat.id) == set()
        await commands['lock'](fixtures.FakeClient(), fixtures.FakeMessage('/lock gif video sticker'))
        assert locks.read(ctx, denied.chat.id) == {'gif','video','sticker'}
        await commands['unlock'](fixtures.FakeClient(), fixtures.FakeMessage('/unlock video'))
        assert locks.read(ctx, denied.chat.id) == {'gif','sticker'}
        await commands['lock'](fixtures.FakeClient(), fixtures.FakeMessage('/lock photo unsupported'))
        assert locks.read(ctx, denied.chat.id) == {'gif','sticker'}
        ctx.db = NS(connected=True, flush=AsyncMock(return_value=0))
        failed = fixtures.FakeMessage('/lock photo')
        await commands['lock'](fixtures.FakeClient(), failed)
        assert 'not confirmed' in failed.replies[-1]
        assert locks.read(ctx, failed.chat.id) == {'gif','sticker'}
        ctx.db.connected = False
        await commands['unlock'](fixtures.FakeClient(), fixtures.FakeMessage('/unlock all'))
        ctx.db = None
        assert locks.read(ctx, failed.chat.id) == {'gif','sticker'}
    asyncio.run(scenario())


def test_lock_enforcement_admin_exemption_bot_rights_and_blocklist_precedence(tmp_path, monkeypatch):
    async def scenario():
        ctx = fixtures.ctx.__wrapped__(tmp_path)
        ctx.chats.put(-100500, locks.KEY, ['gif'])
        message = fixtures.FakeMessage('')
        message.animation = NS(file_id='animation')
        client = fixtures.FakeClient()
        client.get_me = AsyncMock(return_value=NS(id=99))
        async def member(chat, uid):
            return fixtures.member(fixtures.ADMIN if uid == 99 else fixtures.MEMBER)
        client.get_chat_member = AsyncMock(side_effect=member)
        client.delete_messages = AsyncMock(return_value=True)
        assert await locks.enforce(ctx, client, message)
        client.delete_messages.assert_awaited_once_with(-100500, message.id)
        client.delete_messages.reset_mock()
        blocklist = AsyncMock(return_value=False)
        monkeypatch.setattr(moderation, 'enforce_blocklist', blocklist)
        monkeypatch.setattr(moderation, 'clean_service', AsyncMock(return_value=False))
        await moderation.watch(ctx)(client, message)
        blocklist.assert_not_awaited()
        client.get_chat_member.side_effect = None
        client.get_chat_member.return_value = fixtures.member(fixtures.ADMIN)
        client.delete_messages.reset_mock()
        assert not await locks.enforce(ctx, client, message)
        client.delete_messages.assert_not_awaited()
        client.get_chat_member.side_effect = member
        client.delete_messages.side_effect = RuntimeError('secret API details')
        assert await locks.enforce(ctx, client, message)
        assert not message.replies
    asyncio.run(scenario())


def test_lock_state_is_group_scoped_and_all_means_supported_types_only(tmp_path):
    async def scenario():
        ctx = fixtures.ctx.__wrapped__(tmp_path)
        commands = locks.build(ctx)
        await commands['lock'](fixtures.FakeClient(), fixtures.FakeMessage('/lock all'))
        assert locks.read(ctx, -100500) == set(locks.TYPES)
        assert locks.read(ctx, -100501) == set()
        await commands['unlock'](fixtures.FakeClient(), fixtures.FakeMessage('/unlock all'))
        assert locks.read(ctx, -100500) == set()
    asyncio.run(scenario())


def test_locks_persist_in_existing_postgres_chat_store_and_isolate_clone(tmp_path):
    import os
    import uuid
    import pytest
    from agent.platform.db import Database
    from agent.platform.chats import ChatStore
    if not os.environ.get('AGENT_TEST_DATABASE_URL'):
        pytest.skip('PostgreSQL required')
    async def scenario():
        scope = 'locks-test:' + uuid.uuid4().hex
        dbs = [Database(os.environ['AGENT_TEST_DATABASE_URL'], scope=value, required=True)
               for value in (scope, scope, scope + ':clone')]
        try:
            first = dbs[0]
            assert await first.connect()
            await first.load()
            ctx = fixtures.ctx.__wrapped__(tmp_path)
            ctx.db = first
            ctx.chats = ChatStore(tmp_path / 'first', db=first)
            await locks.build(ctx)['lock'](fixtures.FakeClient(), fixtures.FakeMessage('/lock gif sticker'))
            assert locks.read(ctx, -100500) == {'gif','sticker'}
            for index, db in enumerate(dbs[1:], 1):
                assert await db.connect()
                await db.load()
                other = NS(db=db, chats=ChatStore(tmp_path / str(index), db=db))
                assert locks.read(other, -100500) == ({'gif','sticker'} if index == 1 else set())
                assert locks.read(other, -100501) == set()
        finally:
            if dbs[0].connected:
                async with dbs[0]._pool.acquire() as conn:
                    await conn.execute('DELETE FROM agent_documents WHERE name LIKE $1', scope + ':%')
            for db in dbs:
                await db.close()
    asyncio.run(scenario())


def test_entity_locks_handle_captions_and_hidden_links_without_text_heuristics():
    from pyrogram.enums import MessageEntityType as E
    for kind, entity in [('url', E.URL), ('url', E.TEXT_LINK), ('email', E.EMAIL),
                         ('phone', E.PHONE_NUMBER), ('spoiler', E.SPOILER),
                         ('cashtag', E.CASHTAG), ('emojicustom', E.CUSTOM_EMOJI), ('command', E.BOT_COMMAND)]:
        message = NS(text='not a URL', entities=[NS(type=entity)], caption_entities=[])
        assert locks.matches(message, kind)
        message.entities = []
        message.caption_entities = [NS(type=entity)]
        assert locks.matches(message, kind)
        message.caption_entities = [NS(type=E.BOLD)]
        assert not locks.matches(message, kind)
    assert not locks.matches(NS(text='https://example.test @user 12345'), 'url')


def test_forward_and_sticker_subtype_locks_do_not_delete_unrelated_types():
    assert locks.matches(NS(forward_from=NS(id=11)), 'forward')
    assert locks.matches(NS(forward_origin=NS()), 'forward')
    assert not locks.matches(NS(reply_to_message=NS()), 'forward')
    assert locks.matches(NS(sticker=NS(is_animated=True)), 'stickeranimated')
    assert not locks.matches(NS(sticker=NS(is_animated=False)), 'stickeranimated')
    assert locks.matches(NS(sticker=NS(premium_animation=NS(file_id='premium'))), 'stickerpremium')
    assert not locks.matches(NS(sticker=NS()), 'stickerpremium')


def test_url_caption_lock_is_enforced_before_blocklists(tmp_path, monkeypatch):
    from pyrogram.enums import MessageEntityType as E
    async def scenario():
        ctx = fixtures.ctx.__wrapped__(tmp_path)
        ctx.chats.put(-100500, locks.KEY, ['url'])
        message = fixtures.FakeMessage('')
        message.caption = 'click here'
        message.caption_entities = [NS(type=E.TEXT_LINK, url='https://example.test')]
        client = fixtures.FakeClient()
        client.get_me = AsyncMock(return_value=NS(id=99))
        async def member(chat, uid):
            return fixtures.member(fixtures.ADMIN if uid == 99 else fixtures.MEMBER)
        client.get_chat_member = AsyncMock(side_effect=member)
        client.delete_messages = AsyncMock(return_value=True)
        blocklist = AsyncMock(return_value=False)
        monkeypatch.setattr(moderation, 'enforce_blocklist', blocklist)
        monkeypatch.setattr(moderation, 'clean_service', AsyncMock(return_value=False))
        await moderation.watch(ctx)(client, message)
        client.delete_messages.assert_awaited_once_with(-100500, message.id)
        blocklist.assert_not_awaited()
    asyncio.run(scenario())


def test_url_allowlist_uses_domain_boundaries_all_links_and_utf16_offsets():
    from pyrogram.enums import MessageEntityType as E
    def linked(*urls):
        return NS(entities=[NS(type=E.TEXT_LINK, url=url) for url in urls])
    allowed = {'wikipedia.org'}
    assert locks.url_allowed(linked('https://en.wikipedia.org/wiki/Test'), allowed)
    assert not locks.url_allowed(linked('https://wikipedia.org.evil.test'), allowed)
    assert not locks.url_allowed(linked('https://notwikipedia.org'), allowed)
    assert not locks.url_allowed(linked('https://wikipedia.org', 'https://evil.test'), allowed)
    assert not locks.url_allowed(linked('https://wikipedia.org@evil.test'), allowed)
    assert not locks.url_allowed(linked('https://wikipedia.org:bad'), allowed)
    text = '😀 https://wikipedia.org'
    entity = NS(type=E.URL, offset=3, length=len('https://wikipedia.org'))
    assert locks.url_allowed(NS(text=text, entities=[entity]), allowed)
    assert locks.url_allowed(NS(caption=text, caption_entities=[entity]), allowed)
    entity.offset = 999
    assert not locks.url_allowed(NS(text=text, entities=[entity]), allowed)


def test_domain_allowlist_commands_validate_whole_batch_and_do_not_bypass_other_locks(tmp_path):
    from pyrogram.enums import MessageEntityType as E
    async def scenario():
        ctx = fixtures.ctx.__wrapped__(tmp_path)
        command = locks.build(ctx)
        client = fixtures.FakeClient()
        await command['allowlist'](client, fixtures.FakeMessage('/allowlist wikipedia.org telegram.org'))
        assert locks.read_domains(ctx, -100500) == {'wikipedia.org','telegram.org'}
        await command['allowlist'](client, fixtures.FakeMessage('/allowlist safe.test https://unsupported.test/path'))
        assert locks.read_domains(ctx, -100500) == {'wikipedia.org','telegram.org'}
        await command['rmallowlist'](client, fixtures.FakeMessage('/rmallowlist telegram.org'))
        assert locks.read_domains(ctx, -100500) == {'wikipedia.org'}
        ctx.chats.put(-100500, locks.KEY, ['url'])
        msg = fixtures.FakeMessage('')
        msg.caption_entities = [NS(type=E.TEXT_LINK, url='https://en.wikipedia.org')]
        msg.photo = NS(file_id='photo')
        client.get_me = AsyncMock(return_value=NS(id=99))
        async def member(chat, uid):
            return fixtures.member(fixtures.ADMIN if uid == 99 else fixtures.MEMBER)
        client.get_chat_member = AsyncMock(side_effect=member)
        client.delete_messages = AsyncMock(return_value=True)
        assert not await locks.enforce(ctx, client, msg)
        client.delete_messages.assert_not_awaited()
        ctx.chats.put(-100500, locks.KEY, ['url','photo'])
        assert await locks.enforce(ctx, client, msg)
        client.delete_messages.assert_awaited_once()
    asyncio.run(scenario())


def test_clear_allowlist_requires_current_group_owner_and_explicit_confirmation(tmp_path):
    async def scenario():
        ctx = fixtures.ctx.__wrapped__(tmp_path)
        ctx.chats.put(-100500, locks.ALLOW_KEY, ['wikipedia.org'])
        command = locks.build(ctx)['rmallowlistall']
        await command(fixtures.FakeClient(), fixtures.FakeMessage('/rmallowlistall confirm'))
        assert locks.read_domains(ctx, -100500) == {'wikipedia.org'}
        owner = fixtures.FakeClient(caller=fixtures.OWNER)
        await command(owner, fixtures.FakeMessage('/rmallowlistall'))
        assert locks.read_domains(ctx, -100500) == {'wikipedia.org'}
        await command(owner, fixtures.FakeMessage('/rmallowlistall confirm'))
        assert locks.read_domains(ctx, -100500) == set()
    asyncio.run(scenario())


def test_forward_subtypes_distinguish_bot_user_channel_and_hidden_user():
    from pyrogram.enums import ChatType, MessageOriginType as O
    for origin in (NS(forward_from=NS(is_bot=True)),
                   NS(forward_origin=NS(sender_user=NS(is_bot=True)))):
        assert locks.matches(origin, 'forwardbot')
        assert not locks.matches(origin, 'forwarduser')
        assert not locks.matches(origin, 'forwardchannel')
    for origin in (NS(forward_from=NS(is_bot=False)),
                   NS(forward_origin=NS(type=O.HIDDEN_USER)), NS(forward_sender_name='Hidden')):
        assert locks.matches(origin, 'forwarduser')
        assert not locks.matches(origin, 'forwardbot')
    channel = NS(forward_origin=NS(chat=NS(type=ChatType.CHANNEL)))
    assert locks.matches(channel, 'forwardchannel')
    assert not locks.matches(NS(forward_from_chat=NS(type=ChatType.SUPERGROUP)), 'forwardchannel')
    assert not locks.matches(NS(reply_to_message=NS()), 'forwarduser')


def test_url_buttons_lock_and_domain_exemptions_do_not_treat_callbacks_as_links(tmp_path):
    async def scenario():
        ctx = fixtures.ctx.__wrapped__(tmp_path)
        ctx.chats.put(-100500, locks.KEY, ['button'])
        ctx.chats.put(-100500, locks.ALLOW_KEY, ['wikipedia.org'])
        msg = fixtures.FakeMessage('')
        callback = NS(callback_data='safe:action')
        msg.reply_markup = NS(inline_keyboard=[[callback]])
        assert not locks.matches(msg, 'button')
        client = fixtures.FakeClient()
        client.get_me = AsyncMock(return_value=NS(id=99))
        async def member(chat, uid):
            return fixtures.member(fixtures.ADMIN if uid == 99 else fixtures.MEMBER)
        client.get_chat_member = AsyncMock(side_effect=member)
        client.delete_messages = AsyncMock(return_value=True)
        msg.reply_markup.inline_keyboard[0].append(NS(url='https://en.wikipedia.org'))
        assert locks.matches(msg, 'button')
        assert not await locks.enforce(ctx, client, msg)
        client.delete_messages.assert_not_awaited()
        msg.reply_markup.inline_keyboard.append([NS(url='https://evil.test')])
        assert await locks.enforce(ctx, client, msg)
        client.delete_messages.assert_awaited_once_with(-100500, msg.id)
    asyncio.run(scenario())


def test_script_locks_cover_text_captions_and_supplementary_characters():
    for kind, samples in {'cjk': ['中文', 'ひらがな', 'カタカナ', '한글', '𠀀', 'ｶﾀｶﾅ'],
                          'cyrillic': ['Привет', 'Ї', 'ꙮ'],
                          'rtl': ['مرحبا', 'שלום', '\u202ehello', '\u2067hello']}.items():
        for sample in samples:
            assert locks.matches(NS(text='prefix ' + sample), kind)
            assert locks.matches(NS(caption=sample), kind)
        assert not locks.matches(NS(text='hello 123 😀', caption='English'), kind)
        assert not locks.matches(NS(), kind)
    assert not locks.matches(NS(text='മലയാളം'), 'cjk')
    assert not locks.matches(NS(text='മലയാളം'), 'rtl')


def test_new_metadata_locks_distinguish_external_replies_and_story_shares():
    for kind, field in [('externalreply', 'external_reply'), ('forwardstory', 'story'), ('checklist', 'checklist')]:
        assert locks.matches(NS(**{field: NS()}), kind)
        assert not locks.matches(NS(reply_to_message=NS(), reply_to_story=NS()), kind)


def test_script_caption_lock_actual_enforcement_keeps_admin_exemption(tmp_path):
    async def scenario():
        ctx = fixtures.ctx.__wrapped__(tmp_path)
        commands = moderation.build(ctx)[1]
        await commands['lock'](fixtures.FakeClient(), fixtures.FakeMessage('/lock cjk cyrillic rtl externalreply forwardstory checklist'))
        assert locks.read(ctx, -100500) == {'cjk','cyrillic','rtl','externalreply','forwardstory','checklist'}
        message = fixtures.FakeMessage('')
        message.caption = 'Mixed caption 中文'
        client = fixtures.FakeClient()
        client.get_me = AsyncMock(return_value=NS(id=99))
        async def member(chat, uid):
            return fixtures.member(fixtures.ADMIN if uid == 99 else fixtures.MEMBER)
        client.get_chat_member = AsyncMock(side_effect=member)
        client.delete_messages = AsyncMock(return_value=True)
        assert await locks.enforce(ctx, client, message)
        client.delete_messages.assert_awaited_once()
        client.delete_messages.reset_mock()
        client.get_chat_member = AsyncMock(return_value=fixtures.member(fixtures.ADMIN))
        assert not await locks.enforce(ctx, client, message)
        client.delete_messages.assert_not_awaited()
    asyncio.run(scenario())
