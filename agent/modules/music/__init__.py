"""Music — a voice-chat player built on py-tgcalls and Telethon.

The playback surface follows Playeon and Videl0 (``play``, ``pause``, ``resume``,
``skip``, ``stop``, ``queue``, ``nowplaying``, ``leave``) but the implementation
is this repository's: one engine on the shared context, one queue book, and one
place where a failure is turned into a sentence.

It is **gated on capability**, not on hope. ``agent.platform.voice.capability``
answers two questions — is a ``SESSION_STRING`` configured, and are ``telethon``,
``pytgcalls`` and ``ntgcalls`` importable? When either answer is no, ``build()``
returns a manifest with **zero commands**: the plugin shows up in ``/plugins``
with the reason, and none of its buttons exist. A player that cannot join a call
must not offer ``/play``.

Why a second session: a bot token cannot join a group call by itself, so audio
goes through a user session (the "assistant" every voice-chat bot uses) while
commands stay on wzgram. Nothing about the bot's identity changes.
"""

from __future__ import annotations

import logging
from dataclasses import replace

from pyrogram.enums import ChatType

from ...platform.manifest import PluginManifest
from ...platform.voice import VoiceUnavailable, capability
from ...ui.tables import Table, kv_table, panel
from ..moderation import is_moderator
from .queue import QueueBook, Track
from .sources import SourceError, resolve
from ...utils.rich import reply

logger = logging.getLogger(__name__)

MANIFEST = PluginManifest(
    slug="music",
    name="Music · VC player",
    version="1.0.0",
    description="Stream audio into the group's voice chat (needs SESSION_STRING).",
    commands=("play", "pause", "resume", "skip", "stop", "queue", "nowplaying", "leave"),
    permissions=("messages.read", "messages.send", "voice.stream"),
    scope="group",
)

#: Shown in /plugins when the engine cannot run here.
UNAVAILABLE_NOTE = "unavailable in this deployment: {reason}"


def _args(message) -> list[str]:
    return (getattr(message, "text", "") or "").split(maxsplit=1)


def clock(seconds: float) -> str:
    total = max(0, int(seconds))
    minutes, rest = divmod(total, 60)
    hours, minutes = divmod(minutes, 60)
    return f"{hours}:{minutes:02d}:{rest:02d}" if hours else f"{minutes}:{rest:02d}"


def build(ctx):
    """Wire the player, or register nothing when it cannot work."""
    engine = getattr(ctx, "voice", None)
    ok, reason = capability(getattr(ctx.settings, "session_string", None))
    if engine is None or not ok:
        logger.info("Music plugin registers no commands (%s)", reason)
        return (
            replace(
                MANIFEST,
                commands=(),
                description=MANIFEST.description + " — " + UNAVAILABLE_NOTE.format(reason=reason),
            ),
            {},
        )

    queues = QueueBook()

    def _in_group(message) -> bool:
        chat = getattr(message, "chat", None)
        return getattr(chat, "type", None) in (ChatType.GROUP, ChatType.SUPERGROUP)

    async def _play_next(chat_id: int) -> str | None:
        """Advance the queue; returns the title that started, or None."""
        queue = queues.for_chat(chat_id)
        track = queue.advance()
        if track is None:
            queues.drop(chat_id)
            return None
        await engine.play(
            chat_id, track.source, title=track.title, requested_by=track.requested_by
        )
        logger.info(
            "now playing chat=%s title=%r requested_by=%s", chat_id, track.title, track.requested_by
        )
        return track.title

    async def on_stream_end(chat_id: int) -> None:
        """Called by the engine when a stream finishes on its own."""
        try:
            await _play_next(chat_id)
        except Exception:  # noqa: BLE001 - an ended stream must not kill the handler
            logger.exception("could not advance the queue in chat %s", chat_id)

    async def _can_control(client, message) -> bool:
        """Moderators always; a member only over their own track."""
        if await is_moderator(client, message, owner_id=ctx.settings.owner_id):
            return True
        playback = engine.playback(message.chat.id)
        if playback is not None and playback.requested_by == message.from_user.id:
            return True
        await reply(message, 
            "Only staff — or whoever requested the current track — can do that."
        )
        return False

    # -- /play -------------------------------------------------------------

    async def play(client, message):
        if not _in_group(message):
            await reply(message, "Voice chat only exists in groups.")
            return
        rest = _args(message)
        argument = rest[1].strip() if len(rest) > 1 else ""
        try:
            source, title = await resolve(message, argument or None)
        except SourceError as exc:
            await reply(message, f"<b>Cannot play that</b>\n{exc}.")
            return
        queue = queues.for_chat(message.chat.id)
        track = Track(title=title, source=source, requested_by=message.from_user.id)
        playback = engine.playback(message.chat.id)
        if playback is not None or queue.current is not None:
            position = queue.add(track)
            await reply(message, 
                f"Queued <b>{title}</b> at position {position}.\n"
                f"<code>/queue</code> shows the list."
            )
            return
        try:
            await engine.play(
                message.chat.id, source, title=title, requested_by=message.from_user.id
            )
            logger.info(
                "play started chat=%s title=%r by=%s source=%s",
                message.chat.id,
                title,
                message.from_user.id,
                source,
            )
        except VoiceUnavailable as exc:
            await reply(message, f"<b>Could not start playback</b>\n{exc}")
            return
        queue.current = track
        await reply(message, 
            panel(
                "Now playing",
                icon=ctx.theme.emoji("fire"),
                table=kv_table([("Track", title), ("Position", "1 of 1")]),
                note="<code>/pause</code> · <code>/skip</code> · <code>/stop</code>",
                footer="Streaming into this group's voice chat.",
            )
        )

    # -- transport controls ------------------------------------------------

    async def pause(client, message):
        if not await _can_control(client, message):
            return
        try:
            await engine.pause(message.chat.id)
        except VoiceUnavailable as exc:
            await reply(message, f"Nothing to pause: {exc}")
            return
        logger.info("paused chat=%s by=%s", message.chat.id, message.from_user.id)
        await reply(message, "Paused.")

    async def resume(client, message):
        if not await _can_control(client, message):
            return
        try:
            await engine.resume(message.chat.id)
        except VoiceUnavailable as exc:
            await reply(message, f"Nothing to resume: {exc}")
            return
        await reply(message, "Resumed.")

    async def skip(client, message):
        if not await _can_control(client, message):
            return
        try:
            started = await _play_next(message.chat.id)
        except Exception as exc:  # noqa: BLE001 - the engine's reason reaches the chat
            await reply(message, f"Could not skip: {type(exc).__name__}: {exc}")
            return
        if started is None:
            try:
                await engine.leave(message.chat.id)
            except Exception:  # noqa: BLE001 - leaving is best effort here
                logger.debug("leave after empty skip failed", exc_info=True)
            await reply(message, "Queue finished — left the voice chat.")
            return
        await reply(message, f"Now playing <b>{started}</b>.")

    async def stop(client, message):
        if not await _can_control(client, message):
            return
        queues.for_chat(message.chat.id).stop()
        try:
            await engine.leave(message.chat.id)
        except VoiceUnavailable as exc:
            await reply(message, f"Stopped, but the engine was already idle ({exc}).")
            return
        logger.info("stopped chat=%s by=%s", message.chat.id, message.from_user.id)
        await reply(message, "Stopped and left the voice chat. The queue is cleared.")

    async def leave(client, message):
        if not await _can_control(client, message):
            return
        try:
            await engine.leave(message.chat.id)
        except VoiceUnavailable as exc:
            await reply(message, f"I am not in a voice chat here ({exc}).")
            return
        await reply(message, "Left the voice chat.")

    # -- reporting ---------------------------------------------------------

    async def show_queue(client, message):
        queue = queues.for_chat(message.chat.id)
        playback = engine.playback(message.chat.id)
        if playback is None and not queue.waiting:
            await reply(message, 
                panel(
                    "Queue",
                    icon=ctx.theme.emoji("stats"),
                    lines=["Nothing queued."],
                    note="<code>/play &lt;url&gt;</code> or reply with <code>/play</code>.",
                )
            )
            return
        rows = []
        if playback is not None:
            rows.append(("now", playback.title, "playing" if not playback.paused else "paused"))
        for position, track in enumerate(queue.waiting, start=1):
            rows.append((str(position), track.title, f"by {track.requested_by or '—'}"))
        await reply(message, 
            panel(
                "Queue",
                icon=ctx.theme.emoji("stats"),
                subtitle=f"<b>{len(rows)}</b> item(s).",
                table=Table(headers=("#", "Track", "State"), rows=tuple(rows)),
                note="<code>/skip</code> advances, <code>/stop</code> clears everything.",
            )
        )

    async def nowplaying(client, message):
        playback = engine.playback(message.chat.id)
        if playback is None:
            await reply(message, "Nothing is playing here.")
            return
        rows = [
            ("Track", playback.title),
            ("State", "paused" if playback.paused else "playing"),
            ("Elapsed", clock(playback.elapsed)),
            ("Requested by", str(playback.requested_by or "—")),
        ]
        await reply(message, 
            panel(
                "Now playing",
                icon=ctx.theme.emoji("fire"),
                table=kv_table(rows),
                footer="Elapsed time is measured by this process, not read back from the call.",
            )
        )

    if hasattr(engine, "set_stream_end_handler"):
        engine.set_stream_end_handler(on_stream_end)

    logger.info("Music plugin ready (voice-chat engine connected)")
    return MANIFEST, {
        "play": play,
        "pause": pause,
        "resume": resume,
        "skip": skip,
        "stop": stop,
        "queue": show_queue,
        "nowplaying": nowplaying,
        "leave": leave,
    }
