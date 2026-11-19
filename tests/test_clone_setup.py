"""Guided creation never persists unverified tokens or accepts other users' buttons."""

import asyncio
import json
import time
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from test_clone import build, FakeMessage, FakePremium, TOKEN_A, MEMBER
from agent.platform.roles import SudoStore


def query(state, user=MEMBER):
    message = FakeMessage("", uid=user)
    message.edit_text = AsyncMock()
    return SimpleNamespace(
        from_user=SimpleNamespace(id=user), message=message, answer=AsyncMock()
    )


async def api(token, method, **values):
    if method == "getMe":
        return {"id": 111111111, "is_bot": True, "username": "verified_bot"}
    if method == "getChat":
        return {"id": values["chat_id"], "type": "channel"}
    if method == "getChatMember":
        return {"status": "administrator", "can_post_messages": True}
    raise AssertionError(method)


async def identity_step(ctx):
    wizard = ctx.clone_setup
    wizard.api = AsyncMock(side_effect=api)
    await wizard.begin(FakeMessage("/clone"))
    await wizard.receive(None, FakeMessage(TOKEN_A))
    return wizard, wizard.active(MEMBER)


def test_guided_filestore_setup_validates_and_configures_owned_clone(tmp_path):
    async def scenario():
        ctx, _, _ = build(tmp_path)
        wizard, state = await identity_step(ctx)
        assert state.step == "plugin"
        assert not ctx.clones.current()
        await wizard.press(None, query(state), state.nonce + ":files")
        await wizard.receive(None, FakeMessage("-100100"))
        assert state.step == "storage"
        await wizard.receive(None, FakeMessage("-100200"))
        assert state.step == "confirm"
        await wizard.press(None, query(state), state.nonce + ":create")
        record = ctx.clones.current()[0]
        assert record.owner_id == MEMBER
        assert record.selected_plugins == ("filestore",)
        assert record.log_channel == -100100
        assert record.storage_channel == -100200
        settings = ctx.clones.settings_for(record)
        assert settings.owner_id == MEMBER
        assert settings.bot_id == record.bot_id
        assert settings.link_secret != ctx.settings.link_secret
        assert settings.session_string is None
        assert settings.plugins == ("filestore",)
        assert settings.storage_channel == -100200
        assert wizard.active(MEMBER) is None
        assert TOKEN_A not in (tmp_path / "data" / "clones.json").read_text()
        persisted = json.loads((tmp_path / "data" / "clones.json").read_text())
        assert persisted[0]["managed_owner"] is True

    asyncio.run(scenario())


def test_telegram_identity_must_match_token_and_be_bot(tmp_path):
    async def scenario():
        ctx, _, _ = build(tmp_path)
        wizard = ctx.clone_setup
        wizard.api = AsyncMock(return_value={"id": 999, "is_bot": False})
        await wizard.begin(FakeMessage("/clone"))
        await wizard.receive(None, FakeMessage(TOKEN_A))
        assert wizard.active(MEMBER).step == "token"
        assert wizard.active(MEMBER).token == ""
        assert not ctx.clones.current()

    asyncio.run(scenario())


def test_wrong_user_cannot_advance_or_cancel_setup(tmp_path):
    async def scenario():
        ctx, _, _ = build(tmp_path)
        wizard, state = await identity_step(ctx)
        press = query(state, 999)
        await wizard.press(None, press, state.nonce + ":files")
        assert state.step == "plugin"
        assert press.answer.await_args.kwargs["show_alert"]

    asyncio.run(scenario())


def test_expired_setup_refuses_buttons(tmp_path):
    async def scenario():
        ctx, _, _ = build(tmp_path)
        wizard, state = await identity_step(ctx)
        state.expires = time.monotonic() - 1
        await wizard.press(None, query(state), state.nonce + ":files")
        assert wizard.active(MEMBER) is None
        assert not ctx.clones.current()

    asyncio.run(scenario())


def test_channel_requires_both_operator_and_clone_admin_rights(tmp_path):
    async def scenario():
        ctx, _, _ = build(tmp_path)
        wizard, state = await identity_step(ctx)
        await wizard.press(None, query(state), state.nonce + ":files")

        async def forbidden(token, method, **values):
            if method == "getChatMember":
                return {"status": "member"}
            return await api(token, method, **values)

        wizard.api = AsyncMock(side_effect=forbidden)
        await wizard.receive(None, FakeMessage("-100100"))
        assert state.step == "log"
        assert state.log_channel is None
        assert not ctx.clones.current()

    asyncio.run(scenario())


def test_no_secrets_requested_without_encryption(tmp_path):
    async def scenario():
        ctx, _, _ = build(tmp_path)
        wizard = ctx.clone_setup
        wizard.store._box = SimpleNamespace(enabled=False)
        message = FakeMessage("/clone")
        await wizard.begin(message)
        assert wizard.active(MEMBER) is None
        assert "TOKEN_KEY" in message.replies[0]

    asyncio.run(scenario())


def test_free_member_denied_sudo_grant_does_not_enable_setup(tmp_path):
    async def scenario():
        ctx, _, commands = build(tmp_path, premium=FakePremium())
        denied = FakeMessage("/clone")
        await commands["clone"](None, denied)
        assert ctx.clone_setup.active(MEMBER) is None
        ctx.sudo.change(11, MEMBER, add=True)
        await commands["clone"](None, FakeMessage("/clone"))
        assert ctx.clone_setup.active(MEMBER) is None

    asyncio.run(scenario())


def test_sudo_cannot_grant_itself_owner_privileges(tmp_path):
    store = SudoStore(tmp_path, owner_id=11)
    store.change(11, 22, add=True)
    assert SudoStore(tmp_path, owner_id=11).contains(22)
    with pytest.raises(PermissionError):
        store.change(22, 33, add=True)
    store.change(11, 22, add=False)
    assert not store.contains(22)


def test_group_command_never_starts_credential_collection(tmp_path):
    async def scenario():
        ctx, _, commands = build(tmp_path)
        message = FakeMessage("/clone " + TOKEN_A)
        message.chat.id = -100
        await commands["clone"](None, message)
        assert not ctx.clones.current()
        assert ctx.clone_setup.active(MEMBER) is None
        assert TOKEN_A not in message.replies[0]

    asyncio.run(scenario())


def test_clone_does_not_inherit_parent_credentials_or_recursive_cloning(tmp_path):
    from dataclasses import replace
    from agent.modules.clone.store import Clone

    ctx, _, _ = build(tmp_path)
    ctx.clones._settings = replace(
        ctx.settings,
        session_string="PARENT_PRIVATE_SESSION",
        log_channel=-100111,
        storage_channel=-100222,
        plugins=("*",),
        health_port=8080,
    )
    settings = ctx.clones.settings_for(
        Clone(bot_id=111111111, owner_id=22, token=TOKEN_A)
    )
    assert settings.session_string is None
    assert settings.log_channel is None
    assert settings.storage_channel is None
    assert settings.health_port is None
    assert "clone" not in settings.plugins
    assert "*" not in settings.plugins


def test_premium_loss_stops_running_clone_on_supervisor_pass(tmp_path):
    async def scenario():
        ledger = FakePremium({MEMBER})
        ctx, _, commands = build(tmp_path, premium=ledger)
        await commands["clone"](None, FakeMessage("/clone " + TOKEN_A))
        ledger.ids.clear()
        await ctx.clones.supervise()
        assert not ctx.clones.running()
        assert ctx.clones.record(111111111).disabled

    asyncio.run(scenario())


def test_revoked_token_at_confirmation_does_not_create_clone(tmp_path):
    async def scenario():
        ctx, _, _ = build(tmp_path)
        wizard, state = await identity_step(ctx)
        await wizard.press(None, query(state), state.nonce + ":files")
        await wizard.receive(None, FakeMessage("skip"))
        await wizard.receive(None, FakeMessage("-100200"))
        wizard.api = AsyncMock(return_value={"id": 999, "is_bot": True})
        final = query(state)
        await wizard.press(None, final, state.nonce + ":create")
        assert not ctx.clones.current()
        assert wizard.active(MEMBER) is None
        assert all(TOKEN_A not in body for body in final.message.replies)

    asyncio.run(scenario())


def test_clone_record_cannot_be_overwritten_by_another_owner(tmp_path):
    from agent.modules.clone.store import CloneStore, Clone

    from agent.platform.secrets import SecretBox
    store = CloneStore(tmp_path, box=SecretBox("MDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDA="))
    store.add(Clone(bot_id=111111111, owner_id=22, token=TOKEN_A))
    with pytest.raises(ValueError, match="ownership cannot be overwritten"):
        store.add(Clone(bot_id=111111111, owner_id=33, token=TOKEN_A))
    assert store.get(111111111).owner_id == 22


def test_setup_secret_is_excluded_from_representation(tmp_path):
    async def scenario():
        ctx, _, _ = build(tmp_path)
        wizard, state = await identity_step(ctx)
        assert TOKEN_A not in repr(state)
        assert TOKEN_A not in repr(wizard.sessions)
        wizard.cancel(MEMBER)
        assert not wizard.sessions

    asyncio.run(scenario())


def test_clone_owner_always_comes_from_recorded_token_sender(tmp_path):
    from agent.modules.clone.store import Clone

    ctx, _, _ = build(tmp_path)
    # Even an older record's compatibility flag must not substitute the parent.
    record = Clone(bot_id=111111111, owner_id=33, token=TOKEN_A, managed_owner=False)
    assert ctx.clones.settings_for(record).owner_id == 33


def test_clone_does_not_inherit_parent_ai_credentials(tmp_path):
    from dataclasses import replace
    from agent.modules.clone.store import Clone

    ctx, _, _ = build(tmp_path)
    ctx.clones._settings = replace(
        ctx.settings, ai_api_key="PARENT_PRIVATE_AI_KEY", ai_model="parent-model"
    )
    settings = ctx.clones.settings_for(
        Clone(bot_id=111111111, owner_id=MEMBER, token=TOKEN_A)
    )
    assert settings.ai_api_key is None
    assert settings.ai_model is None


@pytest.mark.parametrize(
    "template", ["encoder", "moderation", "postmaker", "linkshare", "leech"]
)
@pytest.mark.parametrize("log", ["skip", "-100100"])
def test_guided_templates_create_only_selected_feature(tmp_path, template, log):
    async def scenario():
        ctx, _, _ = build(tmp_path)
        wizard, state = await identity_step(ctx)
        await wizard.press(None, query(state), state.nonce + ":" + template)
        assert state.step == "log"
        await wizard.receive(None, FakeMessage(log))
        assert state.step == "confirm"
        await wizard.press(None, query(state), state.nonce + ":create")
        record = ctx.clones.current()[0]
        assert record.selected_plugins == (template,)
        assert record.storage_channel is None
        assert record.log_channel == (None if log == "skip" else -100100)
        assert ctx.clones.settings_for(record).plugins == (template,)
        assert ctx.clones.settings_for(record).owner_id == MEMBER
        assert wizard.active(MEMBER) is None

    asyncio.run(scenario())


@pytest.mark.parametrize("action", ["music", "clone", "unknown"])
def test_unreviewed_template_callback_cannot_select_feature(tmp_path, action):
    async def scenario():
        ctx, _, _ = build(tmp_path)
        wizard, state = await identity_step(ctx)
        await wizard.press(None, query(state), state.nonce + ":" + action)
        assert state.step == "plugin"
        assert not ctx.clones.current()

    asyncio.run(scenario())


@pytest.mark.parametrize(
    "selection", [("clone",), ("encoder", "unknown"), ("filestore", "ops")]
)
def test_persisted_unsupported_selection_fails_closed(tmp_path, selection):
    from agent.modules.clone.manager import CloneError
    from agent.modules.clone.store import Clone

    ctx, _, _ = build(tmp_path)
    with pytest.raises(CloneError, match="unsupported"):
        ctx.clones.settings_for(
            Clone(
                bot_id=111111111,
                owner_id=MEMBER,
                token=TOKEN_A,
                selected_plugins=selection,
            )
        )


def test_guided_clone_reports_custom_selection_even_while_stopped(tmp_path):
    from agent.modules.clone.catalog import selection_label
    from agent.modules.clone.store import Clone

    ctx, _, _ = build(tmp_path)
    ctx.clones._store.add(
        Clone(
            bot_id=111111111,
            owner_id=MEMBER,
            token=TOKEN_A,
            profile="tiny",
            selected_plugins=("encoder",),
        )
    )
    assert ctx.clones.profile(111111111) == "custom"
    assert selection_label(("encoder",)) == "Encoder"
    assert selection_label(("<untrusted>",)) == "unsupported"


def test_guided_ai_clone_uses_encrypted_isolated_credentials(tmp_path):
    from agent.modules.clone.store import CloneStore

    async def scenario():
        ctx, _, _ = build(tmp_path)
        wizard, state = await identity_step(ctx)
        await wizard.press(None, query(state), state.nonce + ":ai_agent")
        assert state.step == "ai_key"
        key = "sk-private_clone_key_1234567890"
        secret_message = FakeMessage(key)
        await wizard.receive(None, secret_message)
        assert state.step == "ai_model"
        assert key not in repr(state)
        await wizard.receive(None, FakeMessage("chosen-model"))
        assert state.step == "log"
        await wizard.receive(None, FakeMessage("skip"))
        assert state.step == "confirm"
        await wizard.press(None, query(state), state.nonce + ":create")
        record = ctx.clones.current()[0]
        settings = ctx.clones.settings_for(record)
        assert settings.plugins == ("ai_agent",)
        assert settings.ai_api_key == key
        assert settings.ai_model == "chosen-model"
        assert key not in repr(record)
        assert TOKEN_A not in repr(record)
        assert state.ai_api_key == "" and state.token == ""
        raw = wizard.store.path.read_text()
        assert key not in raw
        assert "ai_api_key_enc" in raw
        restored = CloneStore(wizard.store.path.parent, box=wizard.store._box)
        assert restored.get(record.bot_id).ai_api_key == key

    asyncio.run(scenario())


@pytest.mark.parametrize("finish", ["cancel", "expire"])
def test_ai_draft_credentials_are_cleared(tmp_path, finish):
    async def scenario():
        ctx, _, _ = build(tmp_path)
        wizard, state = await identity_step(ctx)
        await wizard.press(None, query(state), state.nonce + ":ai_agent")
        await wizard.receive(None, FakeMessage("sk-private_clone_key_1234567890"))
        if finish == "cancel":
            wizard.cancel(MEMBER)
        else:
            state.expires = 0
            wizard.active(MEMBER)
        assert state.ai_api_key == "" and state.token == ""
        assert not ctx.clones.current()

    asyncio.run(scenario())


def test_ai_invalid_key_and_model_do_not_advance_setup(tmp_path):
    async def scenario():
        ctx, _, _ = build(tmp_path)
        wizard, state = await identity_step(ctx)
        await wizard.press(None, query(state), state.nonce + ":ai_agent")
        await wizard.receive(None, FakeMessage("not-a-key"))
        assert state.step == "ai_key"
        await wizard.receive(None, FakeMessage("sk-private_clone_key_1234567890"))
        await wizard.receive(None, FakeMessage("model with spaces"))
        assert state.step == "ai_model"

    asyncio.run(scenario())


def test_ai_secret_cannot_be_persisted_without_encryption(tmp_path):
    from agent.modules.clone.store import Clone, CloneStore
    from agent.platform.secrets import SecretBox, SecretError

    store = CloneStore(tmp_path, box=SecretBox(None))
    with pytest.raises(SecretError):
        store.add(
            Clone(
                bot_id=111111111,
                owner_id=MEMBER,
                token=TOKEN_A,
                ai_api_key="sk-private_clone_key_1234567890",
            )
        )
    assert store.count() == 0
    assert not store.path.exists()


def test_cancelling_during_key_message_deletion_cannot_restore_secret(tmp_path):
    async def scenario():
        ctx, _, _ = build(tmp_path)
        wizard, state = await identity_step(ctx)
        await wizard.press(None, query(state), state.nonce + ":ai_agent")
        request = FakeMessage("sk-private_clone_key_1234567890")

        async def cancel_during_delete():
            wizard.cancel(MEMBER)

        request.delete = AsyncMock(side_effect=cancel_during_delete)
        await wizard.receive(None, request)
        assert state.ai_api_key == ""
        assert wizard.active(MEMBER) is None

    asyncio.run(scenario())


def test_cancelled_creation_removes_record_and_clears_draft_secrets(tmp_path):
    async def scenario():
        ctx, _, _ = build(tmp_path)
        wizard, state = await identity_step(ctx)
        await wizard.press(None, query(state), state.nonce + ":leech")
        await wizard.receive(None, FakeMessage("skip"))
        entered = asyncio.Event()

        async def blocked(record):
            entered.set()
            await asyncio.Event().wait()

        wizard.manager.start = AsyncMock(side_effect=blocked)
        task = asyncio.create_task(
            wizard.press(None, query(state), state.nonce + ":create")
        )
        await entered.wait()
        task.cancel()
        result = await asyncio.gather(task, return_exceptions=True)
        assert isinstance(result[0], asyncio.CancelledError)
        assert wizard.store.count() == 0
        assert wizard.active(MEMBER) is None
        assert not state.token and not state.ai_api_key

    asyncio.run(scenario())


def test_clone_command_resumes_draft_without_echoing_or_extending_secrets(tmp_path):
    async def scenario():
        ctx, _, _ = build(tmp_path)
        wizard, state = await identity_step(ctx)
        nonce, expiry = state.nonce, state.expires
        request = FakeMessage("/clone")
        await wizard.begin(request)
        assert wizard.active(MEMBER) is state
        assert (
            state.token == TOKEN_A and state.nonce == nonce and state.expires == expiry
        )
        assert TOKEN_A not in str(request.replies)
        assert "Resume clone setup" in str(request.replies)
        state.step = "confirm"
        state.ai_api_key = "SECRET_AI_KEY"
        state.assistant_session = "SECRET_ASSISTANT"
        request = FakeMessage("/clone")
        await wizard.begin(request)
        body = str(request.replies)
        assert "Clone review" in body and "not configured" in body
        assert all(
            secret not in body
            for secret in [TOKEN_A, "SECRET_AI_KEY", "SECRET_ASSISTANT"]
        )

    asyncio.run(scenario())


def test_starting_draft_is_not_expired_or_replaced(tmp_path):
    async def scenario():
        ctx, _, _ = build(tmp_path)
        wizard, state = await identity_step(ctx)
        state.step = "starting"
        state.expires = 0
        assert wizard.active(MEMBER) is state
        request = FakeMessage("/clone")
        await wizard.begin(request)
        assert wizard.active(MEMBER) is state
        assert state.token == TOKEN_A
        assert "already starting" in str(request.replies)
        request = FakeMessage("/cancel")
        await wizard.receive(None, request)
        assert wizard.active(MEMBER) is state
        # Explicit lifecycle completion still clears all secret fields.
        wizard.cancel(MEMBER)
        assert wizard.active(MEMBER) is None and state.token == ""

    asyncio.run(scenario())


def test_encryption_guidance_explains_owner_key_without_collecting_secrets(tmp_path):
    async def scenario():
        ctx, _, _ = build(tmp_path)
        wizard = ctx.clone_setup
        wizard.store._box = SimpleNamespace(enabled=False)
        request = FakeMessage("/clone")
        await wizard.begin(request)
        body = str(request.replies)
        assert "Deployment Owner only" in body
        assert "not your BotFather token" in body
        assert "Do not send it in Telegram" in body
        assert wizard.active(MEMBER) is None
        assert TOKEN_A not in body
        request = FakeMessage("/clone")
        request.from_user = None
        await wizard.begin(request)
        assert "personal Telegram identity" in str(request.replies)

    asyncio.run(scenario())


def test_guided_file_suite_requires_archive_and_preserves_all_selected_plugins(
    tmp_path,
):
    from agent.modules.clone.catalog import FILE_SUITE, selection_label

    async def scenario():
        ctx, _, _ = build(tmp_path)
        wizard, state = await identity_step(ctx)
        await wizard.press(None, query(state), state.nonce + ":file_suite")
        assert state.step == "log"
        await wizard.receive(None, FakeMessage("skip"))
        assert state.step == "storage"
        assert not ctx.clones.current()
        await wizard.receive(None, FakeMessage("-100100"))
        assert state.step == "confirm"
        await wizard.press(None, query(state), state.nonce + ":create")
        record = ctx.clones.current()[0]
        assert record.selected_plugins == tuple(sorted(FILE_SUITE))
        assert record.storage_channel == -100100
        assert ctx.clones.settings_for(record).plugins == tuple(sorted(FILE_SUITE))
        assert selection_label(("filestore",)) == "FileStore"
        assert wizard.active(MEMBER) is None

    asyncio.run(scenario())


def test_managed_import_requires_event_and_explicit_private_consent(tmp_path):
    async def scenario():
        ctx, _, _ = build(tmp_path)
        wizard = ctx.clone_setup
        wizard.api = AsyncMock(side_effect=api)
        client = SimpleNamespace(get_managed_bot_token=AsyncMock(return_value=TOKEN_A))
        msg = FakeMessage('/clone managed 111111111')
        await wizard.import_managed(client, msg, 111111111)
        client.get_managed_bot_token.assert_not_awaited()
        assert wizard.offer_managed(MEMBER, 111111111)
        assert wizard.active(MEMBER) is None
        await wizard.import_managed(client, msg, 111111111)
        client.get_managed_bot_token.assert_awaited_once_with(111111111)
        state = wizard.active(MEMBER)
        assert state.step == 'plugin'
        assert state.token == TOKEN_A
        assert not ctx.clones.current()  # draft only; Create still required
        assert (MEMBER, 111111111) not in wizard._managed_offers
        assert TOKEN_A not in repr(state)
    asyncio.run(scenario())


@pytest.mark.parametrize('case', ['foreign', 'group', 'expired', 'quota', 'encryption', 'existing', 'busy'])
def test_managed_import_preexport_safeguards(tmp_path, case):
    async def scenario():
        ctx, _, _ = build(tmp_path)
        wizard = ctx.clone_setup
        wizard.offer_managed(MEMBER, 111111111)
        client = SimpleNamespace(get_managed_bot_token=AsyncMock(return_value=TOKEN_A))
        msg = FakeMessage('/clone managed 111111111')
        if case == 'foreign':
            msg = FakeMessage('', uid=999)
        elif case == 'group':
            msg.chat.id = -123
        elif case == 'expired':
            wizard._managed_offers[(MEMBER, 111111111)] = 0
        elif case == 'quota':
            wizard.quota = lambda uid: 0
        elif case == 'encryption':
            wizard.store.encrypted = lambda: False
        elif case == 'existing':
            wizard.store.get = lambda bot_id: object()
        elif case == 'busy':
            await wizard.begin(msg)
            wizard.active(MEMBER).step = 'plugin'
        await wizard.import_managed(client, msg, 111111111)
        client.get_managed_bot_token.assert_not_awaited()
    asyncio.run(scenario())


@pytest.mark.parametrize('case', ['wrong_token', 'wrong_identity', 'cancel', 'revoke', 'full', 'expired', 'export_error'])
def test_managed_import_rechecks_after_network_without_secret_leaks(tmp_path, case):
    async def scenario():
        ctx, _, _ = build(tmp_path)
        wizard = ctx.clone_setup
        wizard.offer_managed(MEMBER, 111111111)
        async def export(bot_id):
            if case == 'cancel':
                wizard.cancel(MEMBER)
            elif case == 'revoke':
                wizard.entitled = AsyncMock(return_value=False)
            elif case == 'full':
                wizard.quota = lambda uid: 0
            elif case == 'expired':
                wizard._managed_offers[(MEMBER, bot_id)] = 0
            elif case == 'export_error':
                raise RuntimeError(TOKEN_A)
            return TOKEN_A if case != 'wrong_token' else '222222222:AAHfakeTokenValueForTests_bbbbbbbb'
        wizard.api = AsyncMock(return_value={'id': 999, 'is_bot': True} if case == 'wrong_identity'
                               else {'id': 111111111, 'is_bot': True})
        msg = FakeMessage('/clone managed 111111111')
        await wizard.import_managed(SimpleNamespace(get_managed_bot_token=export), msg, 111111111)
        state = wizard.active(MEMBER)
        assert state is None or state.token == ''
        assert not ctx.clones.current()
        assert TOKEN_A not in str(msg.replies)
    asyncio.run(scenario())


def test_managed_offers_are_bounded_and_expire(tmp_path):
    ctx, _, _ = build(tmp_path)
    wizard = ctx.clone_setup
    for bot in range(1000, 1100):
        assert wizard.offer_managed(MEMBER, bot)
    assert not wizard.offer_managed(MEMBER, 1200)
    wizard._managed_offers[(MEMBER, 1000)] = 0
    assert wizard.offer_managed(MEMBER, 1200)
    assert len(wizard._managed_offers) == 100


def test_managed_notice_to_command_route_requires_final_confirmation(tmp_path):
    from agent.modules.core import extra_handlers
    async def scenario():
        ctx, _, handlers = build(tmp_path)
        wizard = ctx.clone_setup
        wizard.api = AsyncMock(side_effect=api)
        client = SimpleNamespace(send_message=AsyncMock(), get_managed_bot_token=AsyncMock(return_value=TOKEN_A))
        await extra_handlers(ctx)[1].callback(client, SimpleNamespace(
            user=SimpleNamespace(id=MEMBER, is_bot=False),
            bot=SimpleNamespace(id=111111111, is_bot=True)))
        assert '/clone managed 111111111' in client.send_message.await_args.args[1]
        client.get_managed_bot_token.assert_not_awaited()
        await handlers['clone'](client, FakeMessage('/clone managed 111111111'))
        state = wizard.active(MEMBER)
        assert state.step == 'plugin'
        assert not ctx.clones.current()
        await wizard.press(None, query(state), state.nonce + ':files')
        await wizard.receive(None, FakeMessage('-100100'))
        await wizard.receive(None, FakeMessage('-100200'))
        assert not ctx.clones.current()
        await wizard.press(None, query(state), state.nonce + ':create')
        record = ctx.clones.current()[0]
        assert record.bot_id == 111111111 and record.owner_id == MEMBER
        assert TOKEN_A not in (tmp_path / 'data' / 'clones.json').read_text()
    asyncio.run(scenario())


def test_concurrent_managed_import_exports_once(tmp_path):
    async def scenario():
        ctx, _, _ = build(tmp_path)
        wizard = ctx.clone_setup
        wizard.offer_managed(MEMBER, 111111111)
        await wizard.begin(FakeMessage('/clone'))
        wizard.api = AsyncMock(side_effect=api)
        async def export(bot_id):
            await asyncio.sleep(0)
            return TOKEN_A
        client = SimpleNamespace(get_managed_bot_token=AsyncMock(side_effect=export))
        await asyncio.gather(*(wizard.import_managed(client, FakeMessage(''), 111111111) for _ in range(2)))
        client.get_managed_bot_token.assert_awaited_once()
        assert wizard.active(MEMBER).step == 'plugin'
    asyncio.run(scenario())


@pytest.mark.parametrize('case', ['cancel', 'expiry', 'revoke', 'capacity'])
def test_managed_import_rechecks_after_identity_verification(tmp_path, case):
    async def scenario():
        ctx, _, _ = build(tmp_path)
        wizard = ctx.clone_setup
        wizard.offer_managed(MEMBER, 111111111)
        async def verify(*args):
            if case == 'cancel':
                wizard.cancel(MEMBER)
            elif case == 'expiry':
                wizard._managed_offers[(MEMBER, 111111111)] = 0
            elif case == 'revoke':
                wizard.entitled = AsyncMock(return_value=False)
            elif case == 'capacity':
                wizard.quota = lambda uid: 0
            return {'id': 111111111, 'is_bot': True}
        wizard.api = verify
        await wizard.import_managed(SimpleNamespace(get_managed_bot_token=AsyncMock(return_value=TOKEN_A)),
                                    FakeMessage(''), 111111111)
        state = wizard.active(MEMBER)
        assert state is None or not state.token
    asyncio.run(scenario())


def test_managed_creation_is_capability_gated_and_draft_only(tmp_path):
    async def scenario():
        ctx, _, _ = build(tmp_path)
        wizard = ctx.clone_setup
        client = SimpleNamespace(me=SimpleNamespace(can_manage_bots=True), send_message=AsyncMock())
        ctx.client = client
        msg = FakeMessage('/clone')
        await wizard.begin(msg)
        state = wizard.active(MEMBER)
        buttons = [button for row in msg.markups[-1].inline_keyboard for button in row]
        assert any(button.callback_data.endswith(':managed_create') for button in buttons)
        press = query(state)
        await wizard.press(client, press, state.nonce + ':managed_create')
        args = client.send_message.await_args
        assert args.args[0] == MEMBER
        keyboard = args.kwargs['reply_markup']
        assert keyboard.one_time_keyboard and keyboard.resize_keyboard
        request = keyboard.keyboard[0][0].request_managed_bot
        assert request.button_id > 0
        assert request.suggested_username.endswith('Bot')
        from pyrogram import raw
        encoded = await keyboard.write(None)
        assert isinstance(encoded.rows[0].buttons[0].type.peer_type, raw.types.RequestPeerTypeCreateBot)
        assert encoded.write()  # native wire serialization, not just a mocked send
        assert state.step == 'token' and state.token == ''
        assert not ctx.clones.current()
        assert not wizard._managed_offers  # only Telegram events can attest creator ownership
    asyncio.run(scenario())


@pytest.mark.parametrize('case', ['unsupported', 'unknown', 'foreign', 'group', 'stale', 'capacity', 'encryption', 'advanced'])
def test_managed_creation_refuses_unavailable_or_untrusted_callbacks(tmp_path, case):
    async def scenario():
        ctx, _, _ = build(tmp_path)
        wizard = ctx.clone_setup
        client = SimpleNamespace(me=SimpleNamespace(can_manage_bots=True), send_message=AsyncMock())
        ctx.client = client
        await wizard.begin(FakeMessage('/clone'))
        state = wizard.active(MEMBER)
        press = query(state)
        nonce = state.nonce
        if case == 'unsupported':
            client.me.can_manage_bots = False
        elif case == 'unknown':
            client.me = None
        elif case == 'foreign':
            press.from_user.id = 999
        elif case == 'group':
            press.message.chat.id = -123
        elif case == 'stale':
            nonce = 'invalid'
        elif case == 'capacity':
            wizard.quota = lambda uid: 0
        elif case == 'encryption':
            wizard.store.encrypted = lambda: False
        elif case == 'advanced':
            state.step = 'plugin'
        await wizard.press(client, press, nonce + ':managed_create')
        client.send_message.assert_not_awaited()
    asyncio.run(scenario())


def test_unknown_capability_keeps_manual_setup_without_lookup(tmp_path):
    async def scenario():
        ctx, _, _ = build(tmp_path)
        ctx.client = SimpleNamespace(get_me=AsyncMock())
        msg = FakeMessage('/clone')
        await ctx.clone_setup.begin(msg)
        buttons = [button for row in msg.markups[-1].inline_keyboard for button in row]
        assert not any(button.callback_data.endswith(':managed_create') for button in buttons)
        assert 'Send the token' in msg.replies[-1]
        ctx.client.get_me.assert_not_awaited()
    asyncio.run(scenario())


def test_managed_creation_rechecks_cancellation_after_acknowledgement(tmp_path):
    async def scenario():
        ctx, _, _ = build(tmp_path)
        wizard = ctx.clone_setup
        client = SimpleNamespace(me=SimpleNamespace(can_manage_bots=True), send_message=AsyncMock())
        ctx.client = client
        await wizard.begin(FakeMessage('/clone'))
        state = wizard.active(MEMBER)
        press = query(state)
        async def cancel(*args, **kwargs):
            wizard.cancel(MEMBER)
        press.answer.side_effect = cancel
        await wizard.press(client, press, state.nonce + ':managed_create')
        client.send_message.assert_not_awaited()
    asyncio.run(scenario())


def test_resume_restores_native_option_without_extending_expiry(tmp_path):
    async def scenario():
        ctx, _, _ = build(tmp_path)
        wizard = ctx.clone_setup
        await wizard.begin(FakeMessage('/clone'))
        state = wizard.active(MEMBER)
        expiry = state.expires
        ctx.client = SimpleNamespace(me=SimpleNamespace(can_manage_bots=True))
        msg = FakeMessage('/clone')
        await wizard.begin(msg)
        assert any(button.callback_data.endswith(':managed_create')
                   for row in msg.markups[-1].inline_keyboard for button in row)
        assert state.expires == expiry
    asyncio.run(scenario())


@pytest.mark.parametrize('change', ['premium', 'capacity', 'encryption', 'capability'])
def test_managed_creation_rechecks_access_after_acknowledgement(tmp_path, change):
    async def scenario():
        ctx, _, _ = build(tmp_path)
        wizard = ctx.clone_setup
        client = SimpleNamespace(me=SimpleNamespace(can_manage_bots=True), send_message=AsyncMock())
        ctx.client = client
        await wizard.begin(FakeMessage('/clone'))
        state = wizard.active(MEMBER)
        press = query(state)
        async def change_access(*args, **kwargs):
            if change == 'premium':
                wizard.entitled = AsyncMock(return_value=False)
            elif change == 'capacity':
                wizard.quota = lambda uid: 0
            elif change == 'encryption':
                wizard.store.encrypted = lambda: False
            elif change == 'capability':
                client.me.can_manage_bots = False
        press.answer.side_effect = change_access
        await wizard.press(client, press, state.nonce + ':managed_create')
        client.send_message.assert_not_awaited()
    asyncio.run(scenario())
