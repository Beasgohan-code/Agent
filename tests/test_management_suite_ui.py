"""One management suite in the UI, unchanged mandatory backend modules."""

import asyncio

from test_plugin_panel import make_bot, FakeMessage, buttons
from agent.modules import ops
from agent.platform.policy import GROUP_CORE
from test_clone import build, FakeMessage as CloneMessage, TOKEN_A, run, FakeQuery


def test_runtime_groups_management_and_hides_internal_shell(tmp_path):
    bot = make_bot(tmp_path)
    _, handlers = ops.build(bot.modules)
    message = FakeMessage("/plugins")
    asyncio.run(handlers["plugins"](None, message))
    labels = [b.text for b in buttons(message.markup)]
    assert sum("Group Management" in label for label in labels) == 1
    data = [b.callback_data for b in buttons(message.markup)]
    assert all("plugin:" + slug not in data for slug in GROUP_CORE if slug != "group")
    assert "plugin:ops" not in data and "plugin:core" not in data
    assert set(GROUP_CORE) <= {m.slug for m in bot.registry.manifests()}


def test_clone_delete_button_requires_confirmation(tmp_path):
    ctx, _, commands = build(tmp_path)
    run(commands["clone"], ctx, CloneMessage("/clone " + TOKEN_A))
    query = FakeQuery("clone:111111111:delete")
    asyncio.run(ctx.actions.dispatch(None, query))
    assert ctx.clones.record(111111111) is not None
    assert ctx.clones.is_running(111111111)
    assert any(
        b.callback_data == "clone:111111111:delete_confirm"
        for row in query.edits[-1][1].inline_keyboard
        for b in row
    )
    confirm = FakeQuery("clone:111111111:delete_confirm")
    asyncio.run(ctx.actions.dispatch(None, confirm))
    assert ctx.clones.record(111111111) is None


def test_file_clone_details_warn_when_archive_is_unconfigured(tmp_path):
    ctx, _, commands = build(tmp_path)
    run(commands["clone"], ctx, CloneMessage("/clone " + TOKEN_A + " files"))
    query = FakeQuery("clone:111111111:details")
    query.message.chat.id = query.from_user.id
    asyncio.run(ctx.actions.dispatch(None, query))
    assert "Archive channel" in query.edits[-1][0]
    assert "Not configured" in query.edits[-1][0]
    assert TOKEN_A not in query.edits[-1][0]


def test_clone_details_are_private_and_recheck_ownership(tmp_path):
    ctx, _, commands = build(tmp_path)
    run(commands["clone"], ctx, CloneMessage("/clone " + TOKEN_A))
    for uid in (22, 999):
        query = FakeQuery("clone:111111111:details", uid=uid)
        asyncio.run(ctx.actions.dispatch(None, query))
        assert not query.edits
        assert query.answers[-1][1] is True


def test_delete_confirmation_rechecks_actor(tmp_path):
    ctx, _, commands = build(tmp_path)
    run(commands["clone"], ctx, CloneMessage("/clone " + TOKEN_A))
    query = FakeQuery("clone:111111111:delete_confirm", uid=999)
    asyncio.run(ctx.actions.dispatch(None, query))
    assert ctx.clones.record(111111111) is not None
    assert query.answers[-1][1] is True


def test_mybots_keeps_private_destinations_out_of_groups(tmp_path):
    ctx, _, commands = build(tmp_path)
    message = CloneMessage("/mybots")
    message.chat.id = -100
    run(commands["mybots"], ctx, message)
    assert "privately" in message.replies[0]
    assert not message.markups[0] if message.markups else True
