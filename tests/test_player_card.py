"""The player card: transport buttons instead of typing /pause.

A voice-chat control is the one place where a button beats a command — the
phone is in a pocket, the call is going, and ``/pause`` is a keyboard away.
These tests hold the card to the same rule as the commands it replaces: only
staff, or whoever queued the track, may press it.
"""

import asyncio
import time
from types import SimpleNamespace

from pyrogram.enums import ButtonStyle, ChatMemberStatus, ChatType

from agent.config import Settings
from agent.health import HealthMonitor
from agent.modules import music
from agent.modules.music import TRANSPORT
from agent.platform.actions import ActionRouter
from agent.platform.context import ModuleContext
from agent.platform.jobs import JobQueue
from agent.platform.links import LinkStore
from agent.platform.storage import Storage
from agent.platform.voice import Playback, VoiceUnavailable
from agent.ui.theme import Theme

ENV = {
    "BOT_TOKEN": "123456789:AAHfakeTokenValueForTests_1234567890abc",
    "API_ID": "1234567",
    "API_HASH": "0123456789abcdef0123456789abcdef",
}
CHAT = -100
OWNER = 11
REQUESTER = 22
STRANGER = 33


class FakeEngine:
    """Just enough of the voice engine: a playback per chat and the calls."""

    def __init__(self, playback=None):
        self.playbacks = {CHAT: playback} if playback is not None else {}
        self.calls = []

    def playback(self, chat_id):
        return self.playbacks.get(chat_id)

    async def pause(self, chat_id):
        self.calls.append(("pause", chat_id))
        playing = self.playbacks.get(chat_id)
        if playing is None:
            raise VoiceUnavailable("nothing is playing")
        playing.paused_at = time.time()

    async def resume(self, chat_id):
        self.calls.append(("resume", chat_id))
        playing = self.playbacks.get(chat_id)
        if playing is None:
            raise VoiceUnavailable("nothing is playing")
        playing.paused_at = None

    async def leave(self, chat_id):
        self.calls.append(("leave", chat_id))
        self.playbacks.pop(chat_id, None)


class FakeClient:
    def __init__(self, *, staff=()):
        self.staff = set(staff)

    async def get_chat_member(self, chat_id, user_id):
        status = (
            ChatMemberStatus.ADMINISTRATOR
            if user_id in self.staff
            else ChatMemberStatus.MEMBER
        )
        return SimpleNamespace(status=status, privileges=None)


class FakeMessage:
    def __init__(self):
        self.chat = SimpleNamespace(id=CHAT, type=ChatType.SUPERGROUP)
        self.id = 5
        self.from_user = SimpleNamespace(id=REQUESTER, first_name="Ada")
        self.edits = []

    async def edit_text(self, text=None, reply_markup=None, **kwargs):
        self.edits.append((text, reply_markup))
        return self


class FakeQuery:
    def __init__(self, data, *, user_id):
        self.data = data
        self.from_user = SimpleNamespace(id=user_id)
        self.message = FakeMessage()
        self.answers = []

    async def answer(self, text=None, show_alert=False):
        self.answers.append((text, show_alert))


def playing() -> Playback:
    return Playback(
        title="Tum Hi Ho", source="https://example.test/a.mp3", requested_by=REQUESTER
    )


def build(tmp_path, monkeypatch, *, playback=None, staff=()):
    settings = Settings.from_env({**ENV, "OWNER_ID": str(OWNER)})
    ctx = ModuleContext(
        settings=settings,
        theme=Theme(),
        sender=None,
        jobs=JobQueue(),
        storage=Storage(tmp_path / "storage"),
        links=LinkStore(tmp_path / "links", "secret"),
        monitor=HealthMonitor(),
    )
    ctx.actions = ActionRouter()
    ctx.voice = FakeEngine(playback)
    # The engine is fake, not absent: capability is the only thing to stub.
    monkeypatch.setattr(music, "capability", lambda _session: (True, "ok"))
    manifest, handlers = music.build(ctx)
    return ctx, manifest, handlers


def press(ctx, data, *, user_id, client=None):
    query = FakeQuery(f"{TRANSPORT}:{data}", user_id=user_id)
    asyncio.run(ctx.actions.dispatch(client or FakeClient(), query))
    return query


def buttons(query):
    markup = query.message.edits[-1][1]
    return [button for row in markup.inline_keyboard for button in row]


def test_the_card_carries_the_three_transport_buttons(tmp_path, monkeypatch):
    ctx, _manifest, handlers = build(tmp_path, monkeypatch, playback=playing())

    assert "nowplaying" in handlers
    assert TRANSPORT in ctx.actions.prefixes()
    query = press(ctx, "pause", user_id=REQUESTER)
    pause = buttons(query)[0]

    assert pause.callback_data == f"{TRANSPORT}:resume"  # the card now offers resume
    assert pause.style is ButtonStyle.PRIMARY
    assert buttons(query)[-1].style is ButtonStyle.DANGER


def test_the_requester_may_pause_and_the_card_flips_to_resume(tmp_path, monkeypatch):
    engine_ctx, _, _ = build(tmp_path, monkeypatch, playback=playing())

    query = press(engine_ctx, "pause", user_id=REQUESTER)

    assert engine_ctx.voice.calls == [("pause", CHAT)]
    assert query.answers == [("Paused.", False)]
    text, markup = query.message.edits[-1]
    assert "Tum Hi Ho" in text and "paused" in text
    assert markup.inline_keyboard[0][0].text.endswith("Resume")


def test_staff_may_press_and_resume_again(tmp_path, monkeypatch):
    ctx, _, _ = build(tmp_path, monkeypatch, playback=playing(), staff=(OWNER,))

    press(ctx, "pause", user_id=OWNER)
    query = press(ctx, "resume", user_id=OWNER)

    assert ctx.voice.calls == [("pause", CHAT), ("resume", CHAT)]
    assert query.answers == [("Resumed.", False)]
    assert query.message.edits[-1][1].inline_keyboard[0][0].text.endswith("Pause")


def test_a_stranger_gets_an_alert_and_nothing_else(tmp_path, monkeypatch):
    ctx, _, _ = build(tmp_path, monkeypatch, playback=playing())

    query = press(ctx, "stop", user_id=STRANGER)

    assert ctx.voice.calls == []  # the engine was never touched
    assert query.message.edits == []  # the card was not rewritten
    text, alert = query.answers[-1]
    assert alert is True and "whoever queued" in text


def test_skipping_the_last_track_leaves_and_clears_the_card(tmp_path, monkeypatch):
    ctx, _, _ = build(tmp_path, monkeypatch, playback=playing())

    query = press(ctx, "skip", user_id=REQUESTER)

    assert ("leave", CHAT) in ctx.voice.calls
    assert query.answers[-1][0].startswith("Queue finished")
    text, markup = query.message.edits[-1]
    assert markup is None and "Nothing playing" in text


def test_stopping_clears_the_queue_and_drops_the_buttons(tmp_path, monkeypatch):
    ctx, _, _ = build(tmp_path, monkeypatch, playback=playing())

    query = press(ctx, "stop", user_id=REQUESTER)

    assert ("leave", CHAT) in ctx.voice.calls
    assert query.answers == [("Stopped and left the voice chat.", False)]
    assert query.message.edits[-1][1] is None


def test_a_press_with_nothing_playing_says_so_instead_of_crashing(tmp_path, monkeypatch):
    ctx, _, _ = build(tmp_path, monkeypatch, playback=None)

    query = press(ctx, "pause", user_id=REQUESTER)

    # No playback means the requester rule cannot apply, so it is a refusal.
    assert query.answers[-1][1] is True
    assert ctx.voice.calls == []
