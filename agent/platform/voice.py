"""Agent — voice-chat streaming, on real libraries.

The engine drives ``pytgcalls``/``ntgcalls`` for the audio stream and
``telethon`` for the user session a group call requires; every call is against
the installed package, so :func:`capability` decides whether the player exists
at all rather than failing later.

Everything here is optional. Without ``SESSION_STRING`` the capability check
fails, :class:`VoiceEngine` is never constructed, and the music module registers
no commands at all rather than offering buttons that cannot work.
"""

from __future__ import annotations

import asyncio
import importlib.util
import logging
import time
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)

#: How long a stop may take before the process continues anyway.
STOP_TIMEOUT = 10.0
START_TIMEOUT = 30.0


class VoiceUnavailable(RuntimeError):
    """Raised when the voice engine cannot run in this deployment."""


@dataclass
class Playback:
    """What the engine believes it is playing in one chat."""

    title: str
    source: str
    requested_by: int | None = None
    started_at: float = field(default_factory=time.time)
    paused_at: float | None = None
    paused_total: float = 0.0

    @property
    def elapsed(self) -> float:
        end = self.paused_at if self.paused_at is not None else time.time()
        return max(0.0, end - self.started_at - self.paused_total)

    @property
    def paused(self) -> bool:
        return self.paused_at is not None


def capability(session_string: str | None) -> tuple[bool, str]:
    """Can this deployment stream into a voice chat? (ok, reason)."""
    if not session_string:
        return False, "SESSION_STRING is not set, so no user session can join a call"
    missing = [
        name
        for name in ("ntgcalls", "pytgcalls", "telethon")
        if importlib.util.find_spec(name) is None
    ]
    if missing:  # pragma: no cover - exercised by packaging tests
        return False, f"voice-chat dependencies are missing ({', '.join(missing)})"
    return True, ""


class VoiceEngine:
    """Thin, honest wrapper around ``py-tgcalls``.

        The wrapper exists for two reasons: the library is imported only when a
        session exists, and every failure is reported with the exception type instead
        of being swallowed into a silent "nothing is playing".
        
    """

    def __init__(
        self,
        *,
        session_string: str,
        api_id: int,
        api_hash: str,
        on_stream_end=None,
        assistant_lease=None,
    ) -> None:
        self._assistant_lease = assistant_lease
        self._lifecycle_lock = asyncio.Lock()
        self._session_string = session_string
        self._api_id = api_id
        self._api_hash = api_hash
        self._on_stream_end = on_stream_end
        self._client = None
        self._call = None
        self._connected = False
        self.playbacks: dict[int, Playback] = {}

    @property
    def connected(self) -> bool:
        return self._connected

    def set_stream_end_handler(self, handler) -> None:
        """Install the callback fired when a stream finishes on its own."""
        self._on_stream_end = handler

    async def start(self) -> None:
        """Bound startup and clean partial clients, including on cancellation."""
        async with self._lifecycle_lock:
            if self._connected:
                return
            try:
                await asyncio.wait_for(self._start(), timeout=START_TIMEOUT)
            except BaseException as exc:
                await self._stop()
                if isinstance(exc, asyncio.CancelledError):
                    raise
                if not isinstance(exc, Exception):
                    raise
                raise VoiceUnavailable(f"Voice startup failed ({type(exc).__name__}). Check assistant authorization and voice dependencies.") from None

    async def _start(self) -> None:
        try:
            from pytgcalls import PyTgCalls
            from pytgcalls import filters as vc_filters
            from pytgcalls.types import StreamEnded
            from telethon import TelegramClient
            from telethon.sessions import StringSession
        except ImportError as exc:  # pragma: no cover - packaging guard
            raise VoiceUnavailable(f"voice-chat dependencies missing: {exc.name}") from exc

        client = TelegramClient(
            StringSession(self._session_string),
            self._api_id,
            self._api_hash,
            # Quiet: the library logs every raw update at INFO by default.
            sequential_updates=True,
        )
        self._client = client
        await client.connect()
        if not await client.is_user_authorized():
            raise VoiceUnavailable(
                "the session string is not authorised; generate a new one with "
                "the documented script"
            )
        identity = await client.get_me()
        if identity is None or getattr(identity, "bot", False):
            raise VoiceUnavailable("the assistant must be an authorized user account, not a bot")
        if self._assistant_lease is not None:
            await self._assistant_lease.acquire(getattr(identity, "id", None))
        call = PyTgCalls(client)
        self._call = call

        ended = StreamEnded.Type.AUDIO

        @call.on_update(vc_filters.stream_end(ended))
        async def _ended(_client, update):  # noqa: ANN001 - library handler shape
            # Read at call time: the module installs its handler after start().
            if self._on_stream_end is None:
                return
            try:
                await self._on_stream_end(int(update.chat_id))
            except Exception:  # noqa: BLE001 - a handler must not kill the engine
                logger.exception("stream-end handler failed")

        await call.start()
        self._client = client
        self._call = call
        self._connected = True
        if self._assistant_lease is not None:
            self._assistant_lease.watch(self.shutdown)
        logger.info("Voice chat engine connected (telethon + py-tgcalls)")

    async def stop(self) -> None:
        async with self._lifecycle_lock:
            await self._stop()

    async def _stop(self) -> None:
        self._connected = False
        call, client = self._call, self._client
        self._call = None
        self._client = None
        self.playbacks.clear()
        try:
            if call is not None:
                try:
                    await asyncio.wait_for(call.stop(), timeout=STOP_TIMEOUT)
                except Exception:  # shutdown continues after timeout/failure
                    logger.debug("py-tgcalls stop failed")
        finally:
            try:
                if client is not None:
                    try:
                        await asyncio.wait_for(client.disconnect(), timeout=STOP_TIMEOUT)
                    except Exception:
                        logger.debug("telethon disconnect failed")
            finally:
                if self._assistant_lease is not None:
                    try:
                        await self._assistant_lease.release()
                    except Exception:
                        logger.warning("assistant ownership release failed")

    def _require(self):
        if (not self._connected or self._call is None
                or (self._assistant_lease is not None and not self._assistant_lease.held)):
            raise VoiceUnavailable("the voice engine is not running")
        return self._call

    async def play(self, chat_id: int, source: str, *, title: str, requested_by: int | None = None) -> None:
        """Join the call in *chat_id* if needed and start streaming *source*."""
        call = self._require()
        try:
            await call.play(int(chat_id), source)
        except Exception as exc:  # noqa: BLE001 - the command reports the reason
            logger.exception("play failed in chat %s", chat_id)
            raise VoiceUnavailable(f"{type(exc).__name__}: {exc}") from exc
        self.playbacks[int(chat_id)] = Playback(
            title=title, source=source, requested_by=requested_by
        )

    async def pause(self, chat_id: int) -> None:
        call = self._require()
        await call.pause(int(chat_id))
        playback = self.playbacks.get(int(chat_id))
        if playback is not None and playback.paused_at is None:
            playback.paused_at = time.time()

    async def resume(self, chat_id: int) -> None:
        call = self._require()
        await call.resume(int(chat_id))
        playback = self.playbacks.get(int(chat_id))
        if playback is not None and playback.paused_at is not None:
            playback.paused_total += time.time() - playback.paused_at
            playback.paused_at = None

    async def leave(self, chat_id: int) -> None:
        call = self._require()
        try:
            await call.leave_call(int(chat_id))
        finally:
            self.playbacks.pop(int(chat_id), None)

    async def volume(self, chat_id: int, volume: int) -> None:
        call = self._require()
        await call.change_volume_call(int(chat_id), max(1, min(200, int(volume))))

    def playback(self, chat_id: int) -> Playback | None:
        return self.playbacks.get(int(chat_id))

    async def shutdown(self) -> None:
        """Stop without letting a wedged library hold the process open."""
        try:
            await asyncio.wait_for(self.stop(), timeout=START_TIMEOUT + 2 * STOP_TIMEOUT + 16)
        except Exception:  # noqa: BLE001 - shutdown continues regardless
            logger.warning("voice engine did not stop cleanly")
