"""Themed queue navigation remains read-only and ownership/expiry bound."""
from types import SimpleNamespace
import pytest
from pyrogram.enums import ButtonStyle
from agent.modules.music.queue_cards import QueueCards
from agent.ui.theme import Theme


@pytest.mark.parametrize('custom', [True, False])
def test_music_queue_buttons_are_compact_themed_and_keep_exact_actions(custom):
    theme = Theme() if custom else Theme({})
    cards = QueueCards(theme=theme)
    for page, pages in ((1, 1), (1, 3), (2, 3), (3, 3)):
        keyboard = cards.keyboard('a'*16, page, pages)
        buttons = [b for row in keyboard.inline_keyboard for b in row]
        expected = {f'mqueue:{"a"*16}:{page}', f'mqueue:{"a"*16}:close'}
        if page > 1:
            expected.add(f'mqueue:{"a"*16}:{page-1}')
        if page < pages:
            expected.add(f'mqueue:{"a"*16}:{page+1}')
        assert {b.callback_data for b in buttons} == expected
        assert all(len(row) <= 2 for row in keyboard.inline_keyboard)
        assert all(len(b.callback_data.encode()) <= 64 and b.style is not None for b in buttons)
        assert all(bool(b.icon_custom_emoji_id) == custom for b in buttons)
        close = next(b for b in buttons if b.callback_data.endswith(':close'))
        assert close.style == ButtonStyle.DANGER
        assert 'meiko' not in str(keyboard).lower()


def test_music_card_identity_and_ttl_stay_required():
    now = [100.0]
    cards = QueueCards(theme=Theme(), clock=lambda: now[0])
    cards.cards['token'] = (-100, 44, 22, 200.0)
    def query(chat=-100, mid=44, uid=22):
        return SimpleNamespace(message=SimpleNamespace(chat=SimpleNamespace(id=chat), id=mid), from_user=SimpleNamespace(id=uid))
    assert cards.resolve(query(), 'token')
    for q in (query(chat=-101), query(mid=45), query(uid=23)):
        assert not cards.resolve(q, 'token')
    assert not cards.resolve(query(), 'forged')
    now[0] = 200
    assert not cards.resolve(query(), 'token')
    assert 'token' not in cards.cards
