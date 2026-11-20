"""Saver word workflows reach real media paths without cross-chat mutations."""
import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from agent.modules import renamer
from agent.platform.attachments import CAPTION_KEY, attachment_kwargs
from agent.platform.media_rules import DELETE_KEY, REPLACE_KEY, transform
from test_attachments import make_ctx, FakeMessage, FakeClient


def call(commands, text, client=None, chat_id=77):
    message = FakeMessage(text, chat_id=chat_id)
    asyncio.run(commands[text.split()[0][1:]](client or FakeClient(), message))
    return message


def test_literal_non_cascading_rules_and_chat_isolation(tmp_path):
    ctx = make_ctx(tmp_path)
    commands = renamer.build(ctx)[1]
    call(commands, '/set_repl_word old new')
    call(commands, '/set_repl_word new other')
    call(commands, '/set_del_word junk .*')
    assert transform(ctx.chats, 77, 'old new junk .*') == 'new other  '
    assert transform(ctx.chats, 78, 'old junk') == 'old junk'
    call(commands, '/rem_repl_word old')
    call(commands, '/rem_del_word junk')
    assert transform(ctx.chats, 77, 'old junk') == 'old junk'


def test_caption_filename_alias_and_delivery_use_same_rules(tmp_path):
    ctx = make_ctx(tmp_path)
    commands = renamer.build(ctx)[1]
    call(commands, '/set_repl_word old new')
    ctx.chats.put(77, CAPTION_KEY, '{filename} / {name} / {size}')
    kwargs = attachment_kwargs(ctx.chats, 77, name='old.mkv', size='1 MB')
    assert kwargs['caption'] == 'new.mkv / new.mkv / 1 MB'
    assert attachment_kwargs(ctx.chats, 78, name='old.mkv', size='1 MB') == {}


@pytest.mark.parametrize('text', ['/set_repl_word only', '/set_repl_word a b c', '/rem_repl_word a b', '/set_del_word', '/set_del_word ' + 'x'*65])
def test_bad_rules_do_not_write(tmp_path, text):
    ctx = make_ctx(tmp_path)
    commands = renamer.build(ctx)[1]
    call(commands, text)
    assert ctx.chats.get(77, DELETE_KEY) is None
    assert ctx.chats.get(77, REPLACE_KEY) is None


def test_rule_count_bound_and_deduplication(tmp_path):
    ctx = make_ctx(tmp_path)
    commands = renamer.build(ctx)[1]
    call(commands, '/set_del_word ' + ' '.join('w'+str(i) for i in range(20)))
    call(commands, '/set_del_word w0')
    assert len(ctx.chats.get(77, DELETE_KEY)) == 20
    rejected = call(commands, '/set_del_word overflow')
    assert 'At most 20' in rejected.replies[-1]
    assert len(ctx.chats.get(77, DELETE_KEY)) == 20


def test_group_rule_permissions_and_anonymous_identity(tmp_path, monkeypatch):
    ctx = make_ctx(tmp_path)
    monkeypatch.setattr('agent.modules.renamer.rules.is_moderator', AsyncMock(return_value=False))
    commands = renamer.build(ctx)[1]
    denied = call(commands, '/set_del_word test', chat_id=-100)
    assert 'administrators' in denied.replies[-1]
    assert ctx.chats.get(-100, DELETE_KEY) is None
    message = FakeMessage('/set_del_word test')
    message.from_user = None
    asyncio.run(commands['set_del_word'](FakeClient(), message))
    assert 'personal Telegram' in message.replies[-1]


def test_rename_applies_rules_and_saved_caption(tmp_path):
    ctx = make_ctx(tmp_path)
    commands = renamer.build(ctx)[1]
    call(commands, '/set_repl_word Show Series')
    call(commands, '/set_repl_word Series Other')
    ctx.chats.put(77, CAPTION_KEY, '{filename} · {size}')
    request = FakeMessage('/rename')
    request.reply_to_message = SimpleNamespace(document=SimpleNamespace(file_name='Show.S01E02.720p.mkv', file_id='cached', file_size=123))
    client = FakeClient()
    asyncio.run(commands['rename'](client, request))
    _, _, kwargs = client.sent[0]
    assert kwargs['file_name'] == 'Series S01E02 [720p].mkv'
    assert kwargs['caption'] == 'Series S01E02 [720p].mkv · 123 bytes'
