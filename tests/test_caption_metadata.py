"""Reference metadata captions are literal, escaped and bounded at delivery."""
import html
import re
from types import SimpleNamespace
from unittest.mock import AsyncMock

from agent.platform.attachments import render_caption, CAPTION_KEY, attachment_kwargs
from agent.platform.media_rules import REPLACE_KEY
from agent.modules import renamer
from test_attachments import make_ctx, FakeMessage, run


def test_filename_metadata_and_reference_aliases():
    name = 'Show.S02E003.1080p.WEB-DL.x265.mkv'
    result = render_caption('{quality}|{season}|{episode}|{format}|{file_name}|{filename}', name=name, size='1 MB')
    assert result == '1080p|2|3|x265|' + name + '|' + name


def test_missing_metadata_is_honest_not_inferred_from_substrings():
    assert render_caption('{quality}|{season}|{episode}|{format}', name='wordx265foo.mkv', size='1 B') == 'unknown|unknown|unknown|unknown'


def test_interpolation_is_single_pass_and_escapes_untrusted_names():
    assert render_caption('<b>{name}</b> {size}', name='<a>&{size}.mkv', size='2 B') == '<b>&lt;a&gt;&amp;{size}.mkv</b> 2 B'


def test_expansion_never_cuts_markup_or_entities():
    result = render_caption('<b>{name}</b>', name='&😁'*1000, size='1 B')
    assert '<b>' not in result and '</b>' not in result
    visible = html.unescape(result)
    assert len(visible.encode('utf-16-le')) // 2 <= 1024
    assert result.endswith('…')
    assert not re.search(r'&(?!amp;|lt;|gt;)', result)


def test_caption_preview_uses_same_chat_rules_as_file_delivery(tmp_path):
    ctx = make_ctx(tmp_path)
    ctx.chats.put(77, REPLACE_KEY, {'Show': 'Series'})
    ctx.chats.put(77, CAPTION_KEY, '{filename} {quality} {season}/{episode} {format}')
    from agent.ui.tables import set_rich
    set_rich(True)
    request = FakeMessage('/viewcaption')
    request._client = SimpleNamespace(send_rich_message=AsyncMock())
    run(renamer.build(ctx)[1]['viewcaption'], request)
    expected = attachment_kwargs(ctx.chats, 77, name='Show.S01E01.1080p.x265.mkv', size='1.2 GB')['caption']
    assert expected in request._client.send_rich_message.await_args.kwargs['rich_text'].html
    assert 'Series.S01E01.1080p.x265.mkv 1080p 1/1 x265' in expected
