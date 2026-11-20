"""All punctuation aliases share dispatch, scope and policy authorization."""

import asyncio
from types import SimpleNamespace as NS

from agent.platform.commands import command_filter, command_name


def test_prefixes_mentions_quotes_and_noncommands():
    async def scenario():
        client = NS(me=NS(username="MeikoBot"))
        for prefix in "/!.#$%&?":
            message = NS(text=prefix + 'BaN@meikobot 22 "a reason"', caption=None)
            assert await command_filter("ban")(client, message)
            assert message.command == ["ban", "22", "a reason"]
            assert command_name(message.text) == "ban"
            for text in (
                prefix + "bananas",
                prefix + "ban@otherbot",
                "hello " + prefix + "ban",
                prefix + prefix + "ban",
            ):
                assert not await command_filter("ban")(
                    client, NS(text=text, caption=None)
                )
        assert command_name("Really?") is None
        assert command_name(".123") is None
        assert command_name("? hello") is None

    asyncio.run(scenario())


def test_every_registered_command_uses_the_shared_prefixes():
    from test_bot import make_settings
    from agent.bot import AgentBot

    bot = AgentBot(make_settings())
    bot.build()
    # Combined scope filters retain the command filter as their left operand.
    commands = [
        handler.filters.base
        for handler in bot._handlers
        if hasattr(getattr(handler, "filters", None), "base")
        and hasattr(handler.filters.base, "commands")
    ]
    assert len(commands) > 100
    assert all(f.prefixes == set("/!.#$%&?") for f in commands)


def test_auto_reply_filter_skips_alias_commands(tmp_path):
    import test_moderation as fixtures
    from agent.modules.filters import watch
    from unittest.mock import AsyncMock, patch

    async def scenario():
        ctx = fixtures.ctx.__wrapped__(tmp_path)
        reader = AsyncMock()
        with patch("agent.modules.filters.operate", reader):
            for prefix in "/!.#$%&?":
                await watch(ctx)(None, NS(text=prefix + "ban 22"))
        reader.assert_not_awaited()

    asyncio.run(scenario())


def test_ban_aliases_keep_live_moderator_checks(tmp_path):
    import test_moderation as fixtures
    from agent.modules import moderation

    async def scenario():
        ctx = fixtures.ctx.__wrapped__(tmp_path)
        _, handlers = moderation.build(ctx)
        for prefix in "/!.#$%&?":
            for caller, allowed in ((fixtures.MEMBER, False), (fixtures.ADMIN, True)):
                client = fixtures.FakeClient(caller=caller)
                client.me = NS(username="MeikoBot")
                message = fixtures.FakeMessage(prefix + "ban reason", reply=True)
                message.caption = None
                assert await command_filter("ban")(client, message)
                await handlers["ban"](client, message)
                assert (("ban", 22) in client.calls) is allowed

    asyncio.run(scenario())


def test_clone_wizard_cancel_aliases_discard_drafts(tmp_path):
    from test_clone import build, FakeMessage, MEMBER

    async def scenario():
        for i, prefix in enumerate("/!.#$%&?"):
            ctx, _, _ = build(tmp_path / str(i))
            wizard = ctx.clone_setup
            await wizard.begin(FakeMessage("/clone"))
            assert wizard.active(MEMBER) is not None
            await wizard.receive(None, FakeMessage(prefix + "cancel"))
            assert wizard.active(MEMBER) is None

    asyncio.run(scenario())


def test_all_registered_commands_parse_all_prefixes_and_mentions():
    from test_bot import make_settings
    from agent.bot import AgentBot

    async def scenario():
        bot = AgentBot(make_settings())
        bot.build()
        client = NS(me=NS(username="MeikoBot"))
        for handler in bot._handlers:
            flt = getattr(getattr(handler, "filters", None), "base", None)
            for command in getattr(flt, "commands", ()):
                for prefix in "/!.#$%&?":
                    for suffix in ("", "@MeikoBot"):
                        message = NS(
                            text=prefix + command + suffix + " argument", caption=None
                        )
                        assert await flt(client, message), (prefix, command)
                        assert message.command == [command, "argument"]

    asyncio.run(scenario())


def test_start_payload_and_help_accept_non_slash_commands():
    from agent.handlers.commands import start_payload
    from agent.ui.screens import help_lookup_screen, help_screen
    from agent.ui.theme import Theme

    for prefix in "/!.#$%&?":
        assert start_payload(prefix + "start@MeikoBot link_abc") == "link_abc"
        screen = help_lookup_screen(prefix + "play", None, Theme())
        assert "/play" in screen.rich_text and "Not found" not in screen.rich_text
    assert "all commands" in help_screen(None, Theme()).rich_text.lower()


def test_music_and_media_rule_aliases_execute_correct_operations(tmp_path, monkeypatch):
    from test_music_controls import wire, invoke, STRANGER
    from test_media_rules import make_ctx, call, DELETE_KEY
    from agent.modules import renamer

    async def scenario():
        ctx, _, handlers = wire(tmp_path / "music", monkeypatch)
        for prefix in "/!.#$%&?":
            request = await invoke(handlers, prefix + "loop one")
            assert "Repeat mode: one" in request.reply.await_args.args[0]
            request = await invoke(handlers, prefix + "playnext track", uid=STRANGER)
            assert "administrators" in request.reply.await_args.args[0]

    asyncio.run(scenario())
    ctx = make_ctx(tmp_path / "media")
    handlers = renamer.build(ctx)[1]
    for prefix in "/!.#$%&?":
        call(handlers, prefix + "set_del_word junk")
        assert ctx.chats.get(77, DELETE_KEY) == ["junk"]
        call(handlers, prefix + "rem_del_word junk")
        assert ctx.chats.get(77, DELETE_KEY) == []


def test_sudo_aliases_route_to_the_same_authority():
    from test_sudo_commands import test_command_routes_to_authoritative_service

    for prefix in "/!.#$%&?":
        for text, method in (
            ("sudo list", "listing"),
            ("sudoperms 22", "listing"),
            ("sudo add 22", "grant"),
            ("delsudo 22 diagnostics.read -100 reason", "revoke"),
        ):
            test_command_routes_to_authoritative_service(prefix + text, method)


def test_playlist_aliases_list_instead_of_loading(tmp_path, monkeypatch):
    from test_music_controls import wire, invoke
    from agent.modules.music import playlists
    from unittest.mock import AsyncMock

    async def scenario():
        ctx, _, handlers = wire(tmp_path, monkeypatch)
        from agent.modules.music.queue import QueueBook

        ctx.db = None
        handlers = playlists.build_playlists(ctx, QueueBook())
        listing = AsyncMock(return_value=[])
        monkeypatch.setattr(playlists.MusicPlaylists, "list", listing)
        for prefix in "/!.#$%&?":
            request = await invoke(handlers, prefix + "playlists")
            assert "Your saved playlists" in request.reply.await_args.args[0]
        assert listing.await_count == 8

    asyncio.run(scenario())


def test_literal_at_all_and_eall_are_specific_aliases_not_global_prefixes():
    async def scenario():
        client=NS(me=NS(username='MeikoBot'))
        for text,name in [('@all','all'),('@ALL','all'),('@eall','eall')]:
            message=NS(text=text,caption=None)
            assert await command_filter(name)(client,message)
            assert message.command==[name]
            assert command_name(text)==name
        for text in ('@alligator','hello @all','@all@otherbot','@@all','@ban','@etagall'):
            message=NS(text=text,caption=None)
            assert not await command_filter(['all','eall','ban'])(client,message)
            assert command_name(text) is None
        assert not await command_filter('ban')(client,NS(text='@all',caption=None))
    asyncio.run(scenario())


def test_reply_target_hydration_shared_by_admin_and_moderation():
    from unittest.mock import AsyncMock
    from agent.modules.group.admin import resolve,promotion_target
    from agent.modules.moderation.restrictions import target_and_reason
    async def scenario():
        for kind in ('demote','promote','ban'):
            source=NS(id=70,chat=NS(id=-100),from_user=NS(id=22),sender_chat=None)
            client=NS(get_messages=AsyncMock(return_value=source),get_users=AsyncMock())
            message=NS(id=90,text='/'+kind,chat=NS(id=-100),reply_to_message=None,reply_to_message_id=70)
            if kind=='demote':assert (await resolve(client,message)).id==22
            elif kind=='promote':assert (await promotion_target(client,message))[0].id==22
            else:assert (await target_and_reason(client,message))[0]==22
            client.get_messages.assert_awaited_once_with(-100,reply_to_message_ids=90,replies=0)
            client.get_users.assert_not_awaited()
    asyncio.run(scenario())


def test_missing_reply_never_falls_back_to_a_different_target():
    from unittest.mock import AsyncMock
    from agent.platform.commands import replied_message,ReplyTargetError
    async def scenario():
        for result in (None,NS(empty=True),NS(id=71,chat=NS(id=-100)),NS(id=70,chat=NS(id=-200))):
            message=NS(id=90,text='/ban 999',chat=NS(id=-100),reply_to_message=None,reply_to_message_id=70)
            client=NS(get_messages=AsyncMock(return_value=result))
            try:
                await replied_message(client,message)
            except ReplyTargetError:
                pass
            else:
                raise AssertionError('Invalid reply accepted')
            assert message.reply_to_message is None
            client.get_messages.assert_awaited_once()
        client=NS(get_messages=AsyncMock(side_effect=TimeoutError('PRIVATE_REPLY_DATA')))
        try:
            await replied_message(client,message)
        except ReplyTargetError as error:
            assert 'PRIVATE_REPLY_DATA' not in str(error)
        else:
            raise AssertionError('Failed reply accepted')
        client.get_messages.assert_awaited_once()
        # A forum thread reference alone must not select the topic creator.
        client.get_messages.reset_mock()
        message.topic_message=True
        message.message_thread_id=70
        try:
            await replied_message(client,message)
        except ReplyTargetError:
            pass
        else:
            raise AssertionError('Topic header treated as a personal reply')
        client.get_messages.assert_not_awaited()
    asyncio.run(scenario())


def test_loaded_replies_obey_reference_and_topic_guards():
    from unittest.mock import AsyncMock
    import pytest
    from agent.platform.commands import replied_message, ReplyTargetError

    async def scenario():
        for reference, source_id, topic in (
            (70, 71, False), (True, 70, False), ('70', 70, False),
            (0, 70, False), (70, True, False), (70, 70, True),
        ):
            source = NS(id=source_id, chat=NS(id=-100), from_user=NS(id=22))
            message = NS(id=90, chat=NS(id=-100), reply_to_message=source,
                         reply_to_message_id=reference, topic_message=topic, message_thread_id=70)
            client = NS(get_messages=AsyncMock())
            with pytest.raises(ReplyTargetError):
                await replied_message(client, message)
            client.get_messages.assert_not_awaited()
    asyncio.run(scenario())


def test_valid_loaded_reply_is_reused_without_network():
    from unittest.mock import AsyncMock
    from agent.platform.commands import replied_message

    async def scenario():
        source = NS(id=70, chat=NS(id=-100), from_user=NS(id=22))
        message = NS(id=90, chat=NS(id=-100), reply_to_message=source,
                     reply_to_message_id=70, topic_message=True, message_thread_id=60)
        client = NS(get_messages=AsyncMock())
        assert await replied_message(client, message) is source
        assert await replied_message(client, message) is source
        client.get_messages.assert_not_awaited()
    asyncio.run(scenario())


def test_invalid_loaded_reply_cannot_select_a_moderation_target():
    from unittest.mock import AsyncMock
    import pytest
    from agent.modules.moderation.restrictions import target_and_reason
    from agent.platform.commands import ReplyTargetError

    async def scenario():
        source = NS(id=71, chat=NS(id=-100), from_user=NS(id=22))
        message = NS(id=90, text='/ban 999', chat=NS(id=-100),
                     reply_to_message=source, reply_to_message_id=70)
        client = NS(get_messages=AsyncMock(), get_users=AsyncMock())
        with pytest.raises(ReplyTargetError):
            await target_and_reason(client, message)
        client.get_messages.assert_not_awaited()
        client.get_users.assert_not_awaited()
    asyncio.run(scenario())
