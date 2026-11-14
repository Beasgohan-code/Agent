"""Music — a voice-chat player built on py-tgcalls and Telethon.

It is **gated on capability**, not on hope. ``agent.platform.voice.capability``
answers two questions — is a ``SESSION_STRING`` configured, and are ``telethon``,
``pytgcalls`` and ``ntgcalls`` importable? When either answer is no, ``build()``
returns a manifest with **zero commands**: the plugin shows up in ``/plugins``
with the reason, and none of its buttons exist. A player that cannot join a call
must not offer ``/play``.
"""

from __future__ import annotations

import logging
import asyncio
import html
from collections import deque
from weakref import WeakValueDictionary
from dataclasses import replace
from types import SimpleNamespace

from pyrogram.enums import ButtonStyle, ChatType
from pyrogram.types import InlineKeyboardButton as Button
from pyrogram.types import InlineKeyboardMarkup as Keyboard

from ...platform.manifest import PluginManifest
from ...platform.voice import VoiceUnavailable, capability
from ...ui.tables import Panel, Table, kv_table, panel
from ..moderation import is_moderator
from .queue import QueueBook, Track
from .controls import COMMANDS as EXTRA_COMMANDS, build_controls
from .playlists import COMMANDS as PLAYLIST_COMMANDS, build_playlists
from .sources import SourceError, resolve
from ...utils import rich as rich_ui
from ...utils.rich import reply

logger = logging.getLogger(__name__)

MANIFEST = PluginManifest(
    slug="music",
    name="Music · VC player",
    version="1.0.0",
    description="Stream audio into the group's voice chat (needs SESSION_STRING).",
    commands=("play", "pause", "resume", "skip", "stop", "queue", "nowplaying", "leave",
              "q", "end", "resetplayer", "playnext", *EXTRA_COMMANDS, *PLAYLIST_COMMANDS),
    permissions=("messages.read", "messages.send", "voice.stream"),
    scope="group",
)

#: Shown in /plugins when the engine cannot run here.
UNAVAILABLE_NOTE = "unavailable in this deployment: {reason}"

#: Callback prefix the player card's transport buttons answer on.
TRANSPORT = "music"


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
    history, volumes = {}, {}
    locks = WeakValueDictionary()

    def remember(chat_id, title):
        if chat_id not in history and len(history) >= 200:
            history.pop(next(iter(history)))
        history.setdefault(chat_id, deque(maxlen=15)).append(title[:160])

    def chat_lock(chat_id):
        return locks.setdefault(chat_id, asyncio.Lock())
    gate = getattr(ctx, "plugin_gate", None)

    async def _cleanup_group(chat_id):
        queues.drop(chat_id)
        history.pop(chat_id, None)
        volumes.pop(chat_id, None)
        if engine.playback(chat_id) is not None:
            await engine.leave(chat_id)

    async def cleanup_group(chat_id):
        async with chat_lock(chat_id):
            await _cleanup_group(chat_id)

    if gate is not None:
        gate.cleanup_hook("music", cleanup_group)

    def _in_group(message) -> bool:
        chat = getattr(message, "chat", None)
        return getattr(chat, "type", None) in (ChatType.GROUP, ChatType.SUPERGROUP)

    async def _play_next(chat_id: int, *, force=False) -> str | None:
        """Advance the queue; returns the title that started, or None."""
        if gate is not None and not await gate.allowed(chat_id, "music"):
            await _cleanup_group(chat_id)
            return None
        queue = queues.for_chat(chat_id)
        previous, waiting = queue.current, list(queue.waiting)
        track = queue.advance(force=force)
        if track is None:
            queues.drop(chat_id)
            return None
        try:
            await engine.play(
                chat_id, track.source, title=track.title, requested_by=track.requested_by
            )
        except BaseException:
            queue.current, queue.waiting = previous, waiting
            raise
        remember(chat_id, track.title)
        logger.info(
            "now playing chat=%s title=%r requested_by=%s", chat_id, track.title, track.requested_by
        )
        return track.title

    async def on_stream_end(chat_id: int) -> None:
        """Called by the engine when a stream finishes on its own."""
        try:
            async with chat_lock(chat_id):
                if await _play_next(chat_id) is None:
                    await engine.leave(chat_id)
        except Exception:  # noqa: BLE001 - an ended stream must not kill the handler
            logger.exception("could not advance the queue in chat %s", chat_id)

    def _card(chat_id: int) -> Panel:
        """The player card, read from the engine at the moment it is drawn."""
        playback = engine.playback(chat_id)
        if playback is None:
            return panel(
                "Nothing playing",
                icon=ctx.theme.emoji("stats"),
                lines=["The queue is empty, so there is no card to show."],
                note="<code>/play &lt;url or reply&gt;</code> starts something.",
            )
        rows = [
            ("Track", playback.title),
            ("State", "paused" if playback.paused else "playing"),
            ("Elapsed", clock(playback.elapsed)),
            ("Requested by", str(playback.requested_by or "\u2014")),
        ]
        return panel(
            "Now playing",
            icon=ctx.theme.emoji("fire"),
            table=kv_table(rows),
            note="Staff and whoever queued the track get the buttons; everyone else can read it.",
            footer="Elapsed time is measured by this process, not read back from the call.",
        )

    def _transport(chat_id: int) -> Keyboard:
        """Pause/resume is one button that says which way it goes."""
        playback = engine.playback(chat_id)
        paused = bool(getattr(playback, "paused", False))
        label, action = ("\u25b6\ufe0f Resume", "resume") if paused else ("\u23f8 Pause", "pause")
        return Keyboard(
            [
                [
                    Button(
                        label,
                        callback_data=f"{TRANSPORT}:{action}",
                        style=ButtonStyle.PRIMARY,
                    ),
                    Button("\u23ed Skip", callback_data=f"{TRANSPORT}:skip"),
                ],
                [
                    Button(
                        "\u23f9 Stop and clear",
                        callback_data=f"{TRANSPORT}:stop",
                        style=ButtonStyle.DANGER,
                    )
                ],
            ]
        )

    async def _may_press(client, chat, presser, chat_id: int) -> bool:
        """The same rule as ``/pause``: staff, or the member who queued it."""
        if presser is None:
            return False
        proxy = SimpleNamespace(chat=chat, from_user=presser)
        if await is_moderator(client, proxy, owner_id=ctx.settings.owner_id):
            return True
        playback = engine.playback(chat_id)
        return playback is not None and playback.requested_by == getattr(presser, "id", None)

    async def on_transport(client, query, rest: str) -> None:
        """A press on the player card's buttons."""
        action = (rest or "").strip().lower()
        message = getattr(query, "message", None)
        chat = getattr(message, "chat", None)
        chat_id = getattr(chat, "id", None)
        presser = getattr(query, "from_user", None)
        if chat_id is None or action not in ("pause", "resume", "skip", "stop"):
            await query.answer("That control is no longer available.", show_alert=True)
            return
        if not await _may_press(client, chat, presser, chat_id):
            await query.answer(
                "Only staff \u2014 or whoever queued the track \u2014 can do that.",
                show_alert=True,
            )
            return
        try:
            if action == "pause":
                await engine.pause(chat_id)
                said = "Paused."
            elif action == "resume":
                await engine.resume(chat_id)
                said = "Resumed."
            elif action == "skip":
                started = await _play_next(chat_id, force=True)
                if started is None:
                    try:
                        await engine.leave(chat_id)
                    except VoiceUnavailable:
                        logger.debug("leave after an empty skip failed", exc_info=True)
                    said = "Queue finished \u2014 left the voice chat."
                else:
                    said = f"Now playing {started}."
            else:
                queues.for_chat(chat_id).stop()
                await engine.leave(chat_id)
                said = "Stopped and left the voice chat."
        except VoiceUnavailable as exc:
            await query.answer(str(exc), show_alert=True)
            return
        logger.info(
            "transport %s chat=%s by=%s", action, chat_id, getattr(presser, "id", None)
        )
        card = _card(chat_id)
        keyboard = _transport(chat_id) if engine.playback(chat_id) is not None else None
        try:
            await rich_ui.edit(query, card, reply_markup=keyboard)
        except Exception:  # noqa: BLE001 - a stale card is not a failed control
            logger.debug("could not redraw the player card", exc_info=True)
        await query.answer(said)

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
        if rest[0].split('@')[0].lower() == '/playnext' and not await is_moderator(client, message, owner_id=ctx.settings.owner_id):
            await reply(message, "Only group administrators can insert ahead of other queued requests.")
            return
        argument = rest[1].strip() if len(rest) > 1 else ""
        try:
            source, title = await resolve(message, argument or None)
        except SourceError as exc:
            await reply(message, f"<b>Cannot play that</b>\n{html.escape(str(exc))}.")
            return
        if gate is not None and not await gate.allowed(message.chat.id, "music"):
            await _cleanup_group(message.chat.id)
            await reply(message, "Music is no longer active in this group.")
            return
        title = title[:160]
        queue = queues.for_chat(message.chat.id)
        track = Track(title=title, source=source, requested_by=message.from_user.id)
        playback = engine.playback(message.chat.id)
        if playback is not None or queue.current is not None:
            try:
                position = queue.add(track)
                if _args(message)[0].split('@')[0].lower() == '/playnext':
                    queue.waiting.insert(0, queue.waiting.pop())
                    position = 1
            except ValueError as error:
                await reply(message, str(error))
                return
            await reply(message, 
                f"Queued <b>{html.escape(title)}</b> at position {position}.\n"
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
        remember(message.chat.id, track.title)
        await reply(
            message,
            _card(message.chat.id),
            reply_markup=_transport(message.chat.id),
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
            started = await _play_next(message.chat.id, force=True)
        except Exception as exc:  # noqa: BLE001 - the engine's reason reaches the chat
            await reply(message, f"Could not skip ({type(exc).__name__}). No queue change was confirmed.")
            return
        if started is None:
            try:
                await engine.leave(message.chat.id)
            except Exception:  # noqa: BLE001 - leaving is best effort here
                logger.debug("leave after empty skip failed", exc_info=True)
            await reply(message, "Queue finished — left the voice chat.")
            return
        await reply(message, f"Now playing <b>{html.escape(started)}</b>.")

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
        queues.drop(message.chat.id)
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
        for position, track in enumerate(queue.waiting[:max(0, 15 - len(rows))], start=1):
            rows.append((str(position), track.title, f"by {track.requested_by or '—'}"))
        await reply(message, 
            panel(
                "Queue",
                icon=ctx.theme.emoji("stats"),
                subtitle=f"Showing <b>{len(rows)}</b> of {len(queue.waiting) + (1 if playback else 0)} item(s).",
                table=Table(headers=("#", "Track", "State"), rows=tuple(rows)),
                note="<code>/skip</code> advances, <code>/stop</code> clears everything.",
            )
        )

    async def nowplaying(client, message):
        playback = engine.playback(message.chat.id)
        if playback is None:
            await reply(message, "Nothing is playing here.")
            return
        await reply(
            message,
            _card(message.chat.id),
            reply_markup=_transport(message.chat.id),
        )

    def serialized(handler):
        async def wrapped(client, message):
            if not _in_group(message):
                await reply(message, "Music commands are available in groups only.")
                return
            if getattr(message, "from_user", None) is None:
                await reply(message, "Use your personal Telegram user identity for music commands.")
                return
            async with chat_lock(message.chat.id):
                return await handler(client, message)
        return wrapped

    async def transport_locked(client, query, rest):
        chat_id = getattr(getattr(getattr(query, "message", None), "chat", None), "id", None)
        if chat_id is None:
            return await query.answer("That control is no longer available.", show_alert=True)
        async with chat_lock(chat_id):
            return await on_transport(client, query, rest)

    if hasattr(engine, "set_stream_end_handler"):
        engine.set_stream_end_handler(on_stream_end)

    router = getattr(ctx, "actions", None)
    if router is not None and not router.handles(f"{TRANSPORT}:x"):
        router.register(TRANSPORT, transport_locked)

    logger.info("Music handlers registered; engine startup is checked by the bot lifecycle")
    handlers = {
        "play": play,
        "pause": pause,
        "resume": resume,
        "skip": skip,
        "stop": stop,
        "queue": show_queue,
        "nowplaying": nowplaying,
        "leave": leave,
        "q": show_queue,
        "end": stop,
        "resetplayer": stop,
        "playnext": play,
        **build_controls(ctx, queues, history, volumes, _play_next),
    }
    db = getattr(ctx, "db", None)
    if db is not None and db.connected:
        handlers.update(build_playlists(ctx, queues))
        manifest = MANIFEST
    else:
        manifest = replace(MANIFEST, commands=tuple(name for name in MANIFEST.commands if name not in PLAYLIST_COMMANDS),
                           description=MANIFEST.description + " Saved playlists unavailable without PostgreSQL.")
    return manifest, {name: serialized(handler) for name, handler in handlers.items()}
