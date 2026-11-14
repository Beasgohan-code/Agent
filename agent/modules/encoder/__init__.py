"""Encoder module — real FFmpeg encoding.

The binary comes from ``imageio-ffmpeg`` when the host has no ``ffmpeg`` on
PATH. ``ffprobe`` is not assumed: streams are parsed from ffmpeg's own banner.
"""

from __future__ import annotations

import asyncio
import html
import logging
import math
import re
import shutil
import tempfile
from pathlib import Path

from ...platform.attachments import attachment_kwargs
from ...platform.jobs import Job
from ...platform.manifest import PluginManifest
from ...ui.tables import kv_table, panel
from ...utils.rich import reply
from ..filestore.vault import human_bytes

logger = logging.getLogger(__name__)

MANIFEST = PluginManifest(
    slug="encoder",
    name="Encoder",
    version="1.0.0",
    description="FFmpeg video/audio encoding with presets, live progress and output validation.",
    commands=(
        "encode",
        "compress",
        "sample",
        "toaudio",
        "screens",
        "mediainfo",
    ),
    permissions=("messages.read", "files.write", "process.spawn"),
)

PRESETS: dict[str, tuple[int, str]] = {
    "fast": (28, "veryfast"),
    "balanced": (23, "medium"),
    "quality": (18, "slow"),
}

_DURATION_RE = re.compile(r"Duration:\s*(\d+):(\d+):(\d+\.\d+)")
_VIDEO_RE = re.compile(r"Stream #\d+:\d+.*?: Video: (\w+).*?(\d{2,5})x(\d{2,5})")
_AUDIO_RE = re.compile(r"Stream #\d+:\d+.*?: Audio: (\w+)")


class EncoderUnavailable(RuntimeError):
    """Raised when no usable FFmpeg binary exists."""


def ffmpeg_path() -> str:
    """System ffmpeg if present, else the imageio-ffmpeg wheel."""
    system = shutil.which("ffmpeg")
    if system:
        return system
    try:
        import imageio_ffmpeg

        return imageio_ffmpeg.get_ffmpeg_exe()
    except Exception as exc:  # pragma: no cover - depends on the host
        raise EncoderUnavailable("ffmpeg is not installed (pip install imageio-ffmpeg)") from exc


async def probe(path: Path) -> dict:
    """Read duration and stream info using ffmpeg's banner (no ffprobe)."""
    process = await asyncio.create_subprocess_exec(
        ffmpeg_path(), "-hide_banner", "-i", str(path),
        stdout=asyncio.subprocess.DEVNULL,
        stderr=asyncio.subprocess.PIPE,
    )
    try:
        _, raw = await asyncio.wait_for(process.communicate(), timeout=60)
    except BaseException:
        if process.returncode is None:
            process.kill()
            await process.wait()
        raise
    banner = (raw or b"").decode(errors="ignore")
    duration = 0.0
    if match := _DURATION_RE.search(banner):
        hours, minutes, seconds = match.groups()
        duration = int(hours) * 3600 + int(minutes) * 60 + float(seconds)
    video = _VIDEO_RE.search(banner)
    audio = _AUDIO_RE.search(banner)
    return {
        "duration": duration,
        "video_codec": video.group(1) if video else None,
        "width": int(video.group(2)) if video else None,
        "height": int(video.group(3)) if video else None,
        "audio_codec": audio.group(1) if audio else None,
        "has_video": bool(video),
        "has_audio": bool(audio),
    }


def build_command(src: Path, dst: Path, *, preset: str = "balanced", codec: str = "h264") -> list[str]:
    crf, x264 = PRESETS.get(preset, PRESETS["balanced"])
    encoder = "libx265" if codec in ("h265", "hevc") else "libx264"
    return [
        ffmpeg_path(),
        "-hide_banner",
        "-loglevel", "error",
        "-nostats",
        "-progress", "pipe:1",
        "-y",
        "-i", str(src),
        "-c:v", encoder,
        "-crf", str(crf),
        "-preset", x264,
        "-c:a", "aac",
        "-b:a", "128k",
        str(dst),
    ]


async def run_tool(job: Job, command: list[str], dst: Path, *, duration: float) -> Path:
    """Run any ffmpeg command line, feeding progress into *job*.

    One runner for every tool keeps cancellation honest: whatever is running,
    cancelling the job kills the child instead of leaving it to finish.
    """
    process = await asyncio.create_subprocess_exec(
        *command,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.DEVNULL,
    )
    try:
        assert process.stdout is not None
        while True:
            line = await process.stdout.readline()
            if not line:
                break
            key, _, value = line.decode(errors="ignore").strip().partition("=")
            if key in ("out_time_ms", "out_time_us") and duration > 0 and value.isdigit():
                seconds = int(value) / 1_000_000
                job.progress = min(0.99, seconds / duration)
                job.detail = f"{seconds:.0f}s / {duration:.0f}s"
        await process.wait()
    except BaseException:
        if process.returncode is None:
            process.kill()
            await process.wait()
        raise

    if process.returncode != 0:
        raise RuntimeError(f"ffmpeg exited {process.returncode}; media conversion was not confirmed")
    return dst


async def run_ffmpeg(job: Job, src: Path, dst: Path, *, preset: str, codec: str, duration: float) -> Path:
    """The encode itself, on the shared runner."""
    return await run_tool(
        job, build_command(src, dst, preset=preset, codec=codec), dst, duration=duration
    )


def clip_command(src: Path, dst: Path, *, start: float, length: float) -> list[str]:
    """A short cut, stream-copied: no re-encode, so it is fast and lossless."""
    return [
        ffmpeg_path(),
        "-hide_banner",
        "-loglevel",
        "error",
        "-nostats",
        "-progress",
        "pipe:1",
        "-y",
        "-ss",
        str(start),
        "-i",
        str(src),
        "-t",
        str(length),
        "-c",
        "copy",
        "-map",
        "0",
        str(dst),
    ]


def audio_command(src: Path, dst: Path) -> list[str]:
    """The audio track, as MP3 at 192 kbit/s — playable everywhere."""
    return [
        ffmpeg_path(),
        "-hide_banner",
        "-loglevel",
        "error",
        "-nostats",
        "-progress",
        "pipe:1",
        "-y",
        "-i",
        str(src),
        "-vn",
        "-c:a",
        "libmp3lame",
        "-b:a",
        "192k",
        str(dst),
    ]


def screens_command(src: Path, dst: Path, *, count: int = 9, duration: float = 0.0) -> list[str]:
    """A contact sheet: *count* frames laid out in a 3x3 grid."""
    columns = 3
    rows = max(1, (count + columns - 1) // columns)
    every = max(1.0, duration / (count + 1)) if duration else 10.0
    return [
        ffmpeg_path(),
        "-hide_banner",
        "-loglevel",
        "error",
        "-nostats",
        "-progress",
        "pipe:1",
        "-y",
        "-i",
        str(src),
        "-vf",
        f"select='not(mod(n,{int(max(1, every * 25))}))',scale=320:-1,tile={columns}x{rows}",
        "-frames:v",
        "1",
        "-q:v",
        "3",
        str(dst),
    ]


async def validate_output(path: Path) -> bool:
    """Decode the whole output with errors fatal — a real integrity check."""
    if not path.exists() or path.stat().st_size == 0:
        return False
    process = await asyncio.create_subprocess_exec(
        ffmpeg_path(), "-hide_banner", "-v", "error", "-i", str(path), "-f", "null", "-",
        stdout=asyncio.subprocess.DEVNULL,
        stderr=asyncio.subprocess.PIPE,
    )
    _, stderr = await process.communicate()
    return process.returncode == 0 and not stderr.strip()


def describe(info: dict) -> str:
    if not info.get("has_video"):
        return "audio only" if info.get("has_audio") else "no media streams"
    size = f"{info['width']}x{info['height']}" if info.get("width") else "?"
    return f"{info['video_codec']} {size}, {info['duration']:.1f}s"


async def encode_job(job: Job, ctx, src: Path, preset: str, codec: str) -> Path:
    """Job body: probe → encode → validate, cleaning up on failure."""
    info = await probe(src)
    job.detail = f"encoding {preset}"
    output = Path(tempfile.mkdtemp(prefix="enc-")) / (src.stem + "-encoded.mp4")
    produced = await run_ffmpeg(job, src, output, preset=preset, codec=codec, duration=info["duration"])
    if not await validate_output(produced):
        produced.unlink(missing_ok=True)
        raise RuntimeError("output failed validation (unplayable or empty)")
    return produced


def _source_media(message):
    """The document/video this command is replying to, if any."""
    replied = getattr(message, "reply_to_message", None)
    if replied is None:
        return None
    return getattr(replied, "video", None) or getattr(replied, "document", None)


def build(ctx):
    """Wire commands → handlers for this module."""

    async def encode(_client, message):
        media = _source_media(message)
        if media is None:
            await reply(message, 
                "Reply to a video or document with /encode.\n"
                "Optional: /encode <preset>  (fast, balanced, quality)"
            )
            return

        parts = (getattr(message, "text", "") or "").split()
        preset = parts[1].lower() if len(parts) > 1 else "balanced"
        if preset not in PRESETS:
            await reply(message, f"Unknown preset {preset!r}. Choose: {', '.join(PRESETS)}")
            return

        owner = message.from_user.id
        await reply(message, f"Downloading and queueing ({preset})…")
        try:
            source = await message.reply_to_message.download()
        except Exception as exc:  # noqa: BLE001 - reported to the user
            logger.exception("Download failed for encoder")
            await reply(message, f"Could not download that file: {type(exc).__name__}")
            return
        if not source:
            await reply(message, "Telegram returned no file to encode.")
            return

        src = Path(source)
        job = ctx.jobs.submit(
            "encoder",
            owner,
            lambda j: encode_job(j, ctx, src, preset, "h264"),
            label=src.name,
        )
        await reply(message, 
            f"Encoding job <code>{job.id}</code> started ({preset}). "
            "Use <code>/cancel</code> to stop it."
        )
        await job.task

        if job.state.value == "done":
            await _deliver(_client, message, job, Path(job.result))
        elif job.state.value == "cancelled":
            await reply(message, "Encode cancelled.")
        else:
            await reply(message, "Encode failed. Check the input media and try a supported preset; raw tool output is withheld.")

    async def _deliver(client, message, job: Job, produced: Path) -> None:
        """Send the file a tool produced, with the chat's caption/thumbnail."""
        size = human_bytes(produced.stat().st_size)
        if client is None or not hasattr(client, "send_document"):
            await reply(
                message,
                f"<b>{html.escape(job.label)} finished</b>\n"
                f"<code>{html.escape(produced.name)}</code> · {size}",
            )
            return
        try:
            await client.send_document(
                message.chat.id,
                str(produced),
                file_name=produced.name,
                **attachment_kwargs(
                    ctx.chats,
                    message.chat.id,
                    name=produced.name,
                    size=human_bytes(produced.stat().st_size),
                ),
            )
        except Exception as exc:  # noqa: BLE001 - the job still happened
            logger.exception("could not deliver %s", produced)
            await reply(message, f"The job finished but sending it failed: {type(exc).__name__}")

    async def _run_tool(client, message, *, kind: str, label: str, make) -> None:
        """Shared body for the tools: download, queue, report, deliver."""
        media = _source_media(message)
        if media is None:
            await reply(message, f"Reply to a video or document with /{kind}.")
            return
        try:
            source = await message.reply_to_message.download()
        except Exception as exc:  # noqa: BLE001
            await reply(message, f"Could not download that file: {type(exc).__name__}")
            return
        if not source:
            await reply(message, "Telegram returned no file to work on.")
            return
        src = Path(source)
        job = ctx.jobs.submit("encoder", message.from_user.id, make(src), label=label)
        await reply(
            message,
            f"Job <code>{job.id}</code> started ({html.escape(label)}). "
            "<code>/cancel</code> stops it.",
        )
        await job.task
        if job.state.value != "done":
            reason = "cancelled" if job.state.value == "cancelled" else "Conversion failed; raw tool output is withheld."
            await reply(message, f"<b>{html.escape(label)} failed</b>\n{html.escape(reason)}")
            return
        await _deliver(client, message, job, Path(job.result))

    async def compress(client, message):
        """A smaller file, quickly — /encode fast with the name people expect."""
        media = _source_media(message)
        if media is None:
            await reply(message, "Reply to a video with /compress.")
            return
        try:
            source = await message.reply_to_message.download()
        except Exception as exc:  # noqa: BLE001
            await reply(message, f"Could not download that file: {type(exc).__name__}")
            return
        if not source:
            await reply(message, 'Telegram returned no file to work on.')
            return
        src = Path(source)
        job = ctx.jobs.submit(
            "encoder",
            message.from_user.id,
            lambda j: encode_job(j, ctx, src, "fast", "h264"),
            label=f"{src.stem}-compressed",
        )
        await reply(message, f"Compressing as <code>{job.id}</code> (fast preset).")
        await job.task
        if job.state.value != "done":
            await reply(message, "Compression cancelled." if job.state.value == "cancelled" else "Compression failed; raw tool output is withheld.")
            return
        await _deliver(client, message, job, Path(job.result))

    def _seconds(parts: list[str], index: int, default: float) -> float:
        try:
            return max(0.0, float(parts[index]))
        except (IndexError, ValueError):
            return default

    async def sample(client, message):
        """``/sample [start] [length]`` — a stream-copied clip."""
        parts = (getattr(message, "text", "") or "").split()
        start = _seconds(parts, 1, 0.0)
        length = min(300.0, _seconds(parts, 2, 30.0)) or 30.0

        def make(src: Path):
            async def run(job: Job) -> Path:
                info = await probe(src)
                dst = Path(tempfile.mkdtemp(prefix="sample-")) / f"{src.stem}-sample{src.suffix}"
                job.detail = f"{length:.0f}s from {start:.0f}s"
                return await run_tool(
                    job, clip_command(src, dst, start=start, length=length), dst,
                    duration=min(length, info["duration"] or length),
                )

            return run

        await _run_tool(client, message, kind="sample", label=f"sample {length:.0f}s", make=make)

    async def toaudio(client, message):
        """The audio track as MP3."""

        def make(src: Path):
            async def run(job: Job) -> Path:
                info = await probe(src)
                dst = Path(tempfile.mkdtemp(prefix="audio-")) / f"{src.stem}.mp3"
                job.detail = "extracting audio"
                return await run_tool(job, audio_command(src, dst), dst, duration=info["duration"])

            return run

        await _run_tool(client, message, kind="toaudio", label="audio", make=make)

    async def screens(client, message):
        """/screens — a fixed-layout contact sheet of the replied video."""

        def make(src: Path):
            async def run(job: Job) -> Path:
                info = await probe(src)
                dst = Path(tempfile.mkdtemp(prefix="screens-")) / f"{src.stem}-screens.jpg"
                job.detail = "building the sheet"
                return await run_tool(
                    job,
                    screens_command(src, dst, duration=info["duration"]),
                    dst,
                    duration=info["duration"],
                )

            return run

        await _run_tool(client, message, kind="screens", label="contact sheet", make=make)

    async def mediainfo(_client, message):
        media = _source_media(message)
        if media is None:
            await reply(message, "Reply to a video or document with /mediainfo.")
            return
        try:
            source = await message.reply_to_message.download()
        except Exception as exc:  # noqa: BLE001
            await reply(message, f"Could not download that file: {type(exc).__name__}")
            return
        if not source:
            await reply(message, 'Telegram returned no file to inspect.')
            return
        try:
            info = await probe(Path(source))
        except Exception as error:
            await reply(message, f'Could not inspect the media ({type(error).__name__}). No raw paths or tool output are displayed.')
            return
        rows = [
            ("Video", info["video_codec"] or "none"),
            ("Resolution", f"{info['width']}x{info['height']}" if info.get("width") else "n/a"),
            ("Audio", info["audio_codec"] or "none"),
            ("Duration", f"{info['duration']:.2f}s"),
            ("Streams", describe(info)),
        ]
        await reply(message, 
            panel(
                "Media info",
                icon=ctx.theme.emoji("gear"),
                subtitle="Probed from the replied file, not from the caption.",
                table=kv_table(rows),
                note="Encode it with <code>/encode fast|balanced|quality</code>.",
            )
        )


    def validated(name, handler):
        async def wrapped(client, message):
            user_id = getattr(getattr(message, 'from_user', None), 'id', None)
            if not isinstance(user_id, int) or isinstance(user_id, bool) or user_id <= 0:
                await reply(message, 'Use your personal Telegram user identity for Encoder commands.')
                return
            args = (getattr(message, 'text', '') or '').split()[1:]
            problem = None
            if name in ('compress', 'toaudio', 'screens', 'mediainfo') and args:
                problem = f'Use /{name} without arguments.'
            elif name == 'encode' and (len(args) > 1 or (args and args[0].lower() not in PRESETS)):
                problem = 'Use /encode [fast|balanced|quality].'
            elif name == 'sample':
                try:
                    if len(args) > 2 or any(len(value) > 20 for value in args):
                        raise ValueError()
                    values = [float(value) for value in args]
                    if any(not math.isfinite(value) for value in values):
                        raise ValueError()
                    if values and not 0 <= values[0] <= 86400:
                        raise ValueError()
                    if len(values) > 1 and not 0 < values[1] <= 300:
                        raise ValueError()
                except ValueError:
                    problem = 'Use /sample [start_seconds] [length_seconds]: start 0–86400, length above 0 up to 300. Finite numbers only.'
            if problem:
                await reply(message, panel('Check Encoder options', icon=ctx.theme.emoji('info'),
                    lines=[html.escape(problem)], footer='/encode fast|balanced|quality · /help'))
                return
            return await handler(client, message)
        return wrapped

    handlers = {
        "encode": encode,
        "compress": compress,
        "sample": sample,
        "toaudio": toaudio,
        "screens": screens,
        "mediainfo": mediainfo,

    }
    return MANIFEST, {name: validated(name, handler) for name, handler in handlers.items()}
