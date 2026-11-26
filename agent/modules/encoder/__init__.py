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
from ...platform.jobs import Job, JobAdmissionError
from ...platform.manifest import PluginManifest
from ...ui.tables import kv_table, panel
from ...utils.rich import reply
from ..filestore.vault import human_bytes
from .options import USAGE, VideoOptions, parse_options, audio_options, screen_count

logger = logging.getLogger(__name__)

MANIFEST = PluginManifest(
    group_compatible=False,
    clone_compatible=True,
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

PROBE_TIMEOUT = 60
MAX_PROBE_BYTES = 256 * 1024
INPUT_PROTOCOLS = "file,pipe"

CONVERSION_TIMEOUT = 60 * 60
VALIDATION_TIMEOUT = 5 * 60

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
        ffmpeg_path(), "-hide_banner", "-nostdin", "-protocol_whitelist", INPUT_PROTOCOLS, "-i", str(path),
        stdout=asyncio.subprocess.DEVNULL,
        stderr=asyncio.subprocess.PIPE,
    )
    try:
        async with asyncio.timeout(PROBE_TIMEOUT):
            chunks, size = [], 0
            while True:
                chunk = await process.stderr.read(8192)
                if not chunk:
                    break
                size += len(chunk)
                if size > MAX_PROBE_BYTES:
                    raise ValueError("Media diagnostics exceed the inspection limit.")
                chunks.append(chunk)
            await process.wait()
            raw = b"".join(chunks)
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
    if video is None and audio is None:
        raise ValueError("No supported audio/video streams were found.")
    return {
        "duration": duration,
        "video_codec": video.group(1) if video else None,
        "width": int(video.group(2)) if video else None,
        "height": int(video.group(3)) if video else None,
        "audio_codec": audio.group(1) if audio else None,
        "has_video": bool(video),
        "has_audio": bool(audio),
    }


def build_command(src: Path, dst: Path, *, preset: str = "balanced", codec: str = "h264",
                  options: VideoOptions | None = None) -> list[str]:
    if preset not in PRESETS or codec not in ("h264", "h265", "hevc"):
        raise ValueError(USAGE)
    options = options or VideoOptions()
    crf, x264 = PRESETS[preset]
    if options.crf is not None:
        crf = options.crf
    encoder = "libx265" if codec in ("h265", "hevc") else "libx264"
    filters = options.filters()
    return [
        ffmpeg_path(),
        "-hide_banner",
        "-loglevel", "error",
        "-nostats",
        "-progress", "pipe:1",
        "-y",
        "-protocol_whitelist", INPUT_PROTOCOLS,
        "-i", str(src),
        "-c:v", encoder,
        "-crf", str(crf),
        "-preset", x264,
        "-c:a", "aac",
        "-b:a", "128k",
        "-pix_fmt", "yuv420p",
        *(["-vf", ",".join(filters)] if filters else []),
        "-movflags", "+faststart",
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
        async with asyncio.timeout(CONVERSION_TIMEOUT):
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
        if process.returncode != 0:
            raise RuntimeError(f"ffmpeg exited {process.returncode}; media conversion was not confirmed")
        if not dst.is_file() or dst.stat().st_size == 0:
            raise RuntimeError("ffmpeg returned no nonempty output; media conversion was not confirmed")
    except BaseException:
        if process.returncode is None:
            process.kill()
            await process.wait()
        dst.unlink(missing_ok=True)
        raise

    return dst


async def run_ffmpeg(job: Job, src: Path, dst: Path, *, preset: str, codec: str, duration: float,
                     options: VideoOptions | None = None) -> Path:
    """The encode itself, on the shared runner."""
    return await run_tool(
        job, build_command(src, dst, preset=preset, codec=codec, options=options), dst, duration=duration
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
        "-protocol_whitelist", INPUT_PROTOCOLS,
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


def audio_command(src: Path, dst: Path, *, kind: str = "mp3", bitrate: int = 192) -> list[str]:
    """Extract one audio stream with bounded container-specific options."""
    if kind not in ("mp3", "m4a", "flac") or type(bitrate) is not int or bitrate not in (128, 192, 256, 320):
        raise ValueError("Invalid audio format or bitrate.")
    codec = {"mp3": "libmp3lame", "m4a": "aac", "flac": "flac"}[kind]
    return [
        ffmpeg_path(),
        "-hide_banner",
        "-loglevel",
        "error",
        "-nostats",
        "-progress",
        "pipe:1",
        "-y",
        "-protocol_whitelist", INPUT_PROTOCOLS,
        "-i",
        str(src),
        "-vn",
        "-c:a",
        codec,
        *(["-b:a", f"{bitrate}k"] if kind != "flac" else []),
        *(["-movflags", "+faststart"] if kind == "m4a" else []),
        str(dst),
    ]


def screens_command(src: Path, dst: Path, *, count: int = 9, duration: float = 0.0) -> list[str]:
    """A contact sheet: *count* frames laid out in a 3x3 grid."""
    if type(count) is not int or count not in (4, 9, 16):
        raise ValueError("Choose 4, 9 or 16 frames.")
    if not math.isfinite(duration) or duration < 0:
        raise ValueError("Invalid media duration.")
    columns = int(math.isqrt(count))
    rows = columns
    rate = count / duration if duration else 0.1
    return [
        ffmpeg_path(),
        "-hide_banner",
        "-loglevel",
        "error",
        "-nostats",
        "-progress",
        "pipe:1",
        "-y",
        "-protocol_whitelist", INPUT_PROTOCOLS,
        "-i",
        str(src),
        "-vf",
        f"fps={rate:.8f},scale=320:-2,tile={columns}x{rows}",
        "-frames:v",
        "1",
        "-q:v",
        "3",
        str(dst),
    ]


async def validate_output(path: Path) -> bool:
    """Decode with fatal errors, bounded runtime, and cancellation-safe cleanup.

    FFmpeg's error exit status is authoritative with ``-xerror``. Stderr is
    discarded rather than buffering arbitrary decoder diagnostics in memory.
    """
    if not path.is_file() or path.stat().st_size == 0:
        return False
    process = await asyncio.create_subprocess_exec(
        ffmpeg_path(), "-hide_banner", "-nostdin", "-v", "error", "-xerror",
        "-protocol_whitelist", INPUT_PROTOCOLS,
        "-i", str(path), "-f", "null", "-",
        stdout=asyncio.subprocess.DEVNULL,
        stderr=asyncio.subprocess.DEVNULL,
    )
    try:
        await asyncio.wait_for(process.wait(), timeout=VALIDATION_TIMEOUT)
    except BaseException:
        if process.returncode is None:
            process.kill()
            await process.wait()
        raise
    return process.returncode == 0


def describe(info: dict) -> str:
    if not info.get("has_video"):
        return "audio only" if info.get("has_audio") else "no media streams"
    size = f"{info['width']}x{info['height']}" if info.get("width") else "?"
    return f"{info['video_codec']} {size}, {info['duration']:.1f}s"


async def encode_job(job: Job, ctx, src: Path, preset: str, codec: str,
                     options: VideoOptions | None = None) -> Path:
    """Job body: probe → encode → validate, cleaning up on failure."""
    info = await probe(src)
    job.detail = f"encoding {preset}"
    output = Path(tempfile.mkdtemp(prefix="enc-")) / (src.stem + "-encoded.mp4")
    try:
        produced = await run_ffmpeg(job, src, output, preset=preset, codec=codec, duration=info["duration"],
                                    **({"options": options} if options is not None else {}))
        if not await validate_output(produced):
            raise RuntimeError("output failed validation (unplayable or empty)")
        return produced
    except BaseException:
        # Cleanup must not replace the conversion/cancellation exception, nor
        # log its chained diagnostic body or the job's local path.
        try:
            output.unlink(missing_ok=True)
        except OSError as error:
            logger.warning("#Errors Encoder output cleanup failed (%s).", type(error).__name__)
        # Only this job's newly created directory is owned here.
        try:
            output.parent.rmdir()
        except OSError as error:
            logger.warning("#Errors Encoder directory cleanup failed (%s).", type(error).__name__)
        raise


def _source_message(message):
    """Reviewed Encoder workflow: replied media first, then attached media."""
    replied = getattr(message, "reply_to_message", None)
    if replied is not None and (getattr(replied, "video", None) or getattr(replied, "document", None)):
        return replied
    if getattr(message, "video", None) or getattr(message, "document", None):
        return message
    return None


def _source_media(message):
    source = _source_message(message)
    return (getattr(source, "video", None) or getattr(source, "document", None)) if source is not None else None


def _command_text(message):
    return getattr(message, "text", None) or getattr(message, "caption", None) or ""


def build(ctx):
    """Wire commands → handlers for this module."""

    async def encode(_client, message):
        media = _source_media(message)
        if media is None:
            await reply(message, 
                "Reply to a video or document with /encode.\n"
                + USAGE
            )
            return

        parts = _command_text(message).split()
        preset, codec, options = parse_options(parts[1:])

        owner = message.from_user.id
        await reply(message, panel("Encoder request", icon=ctx.theme.emoji("gear"),
            table=kv_table([("Preset", preset), ("Codec", codec),
                            ("Quality (CRF)", str(options.crf if options.crf is not None else PRESETS[preset][0])),
                            ("Max height", options.height), ("Frame rate", options.fps)]),
            note="Downloading and queueing. Options apply only to this request; source is not modified."))
        try:
            source = await _source_message(message).download()
        except Exception as exc:  # noqa: BLE001 - reported to the user
            logger.warning("#Errors Encoder download failed (%s).", type(exc).__name__)
            await reply(message, f"Could not download that file: {type(exc).__name__}")
            return
        if not source:
            await reply(message, "Telegram returned no file to encode.")
            return

        src = Path(source)
        job = ctx.jobs.submit(
            "encoder",
            owner,
            lambda j: encode_job(j, ctx, src, preset, codec, options),
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
        try:
            byte_count = produced.stat().st_size
            if not produced.is_file() or byte_count <= 0:
                raise ValueError("Output is unavailable")
            size = human_bytes(byte_count)
        except OSError as exc:
            logger.warning("#Errors Encoder output access failed (%s).", type(exc).__name__)
            await reply(message, "The job finished but delivery was not confirmed: the output is unavailable. No automatic retry was attempted.")
            return
        except ValueError:
            logger.warning("#Errors Encoder output is not a nonempty regular file.")
            await reply(message, "The job finished but delivery was not confirmed: the output is unavailable. No automatic retry was attempted.")
            return
        if client is None or not hasattr(client, "send_document"):
            await reply(
                message,
                f"<b>{html.escape(job.label)} finished</b>\n"
                f"<code>{html.escape(produced.name)}</code> · {size}\nFile delivery is unavailable in this context.",
            )
            return
        try:
            sent = await client.send_document(
                message.chat.id,
                str(produced),
                file_name=produced.name,
                **attachment_kwargs(
                    ctx.chats,
                    message.chat.id,
                    name=produced.name,
                    size=size,
                ),
            )
            if sent is None or sent is False:
                raise RuntimeError("Delivery acknowledgement unavailable")
        except Exception as exc:  # the conversion still happened; do not resend
            logger.warning("#Errors Encoder delivery unconfirmed (%s).", type(exc).__name__)
            await reply(message, "The job finished but delivery was not confirmed. Check this chat before retrying; no automatic resend was attempted.")

    async def _run_tool(client, message, *, kind: str, label: str, make) -> None:
        """Shared body for the tools: download, queue, report, deliver."""
        media = _source_media(message)
        if media is None:
            await reply(message, f"Reply to a video or document with /{kind}.")
            return
        try:
            source = await _source_message(message).download()
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
            source = await _source_message(message).download()
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
        parts = _command_text(message).split()
        start = _seconds(parts, 1, 0.0)
        length = min(300.0, _seconds(parts, 2, 30.0)) or 30.0

        def make(src: Path):
            async def run(job: Job) -> Path:
                info = await probe(src)
                if info["duration"] > 0 and start >= info["duration"]:
                    raise ValueError("Sample start must be before the end of the media.")
                dst = Path(tempfile.mkdtemp(prefix="sample-")) / f"{src.stem}-sample{src.suffix}"
                job.detail = f"{length:.0f}s from {start:.0f}s"
                return await run_tool(
                    job, clip_command(src, dst, start=start, length=length), dst,
                    duration=min(length, info["duration"] or length),
                )

            return run

        await _run_tool(client, message, kind="sample", label=f"sample {length:.0f}s", make=make)

    async def toaudio(client, message):
        """Extract MP3, M4A or FLAC without accepting shell fragments."""
        kind, bitrate = audio_options(_command_text(message).split()[1:])

        def make(src: Path):
            async def run(job: Job) -> Path:
                info = await probe(src)
                if not info.get("has_audio"):
                    raise ValueError("No audio stream was found.")
                dst = Path(tempfile.mkdtemp(prefix="audio-")) / f"{src.stem}.{kind}"
                job.detail = "extracting audio"
                return await run_tool(job, audio_command(src, dst, kind=kind, bitrate=bitrate), dst, duration=info["duration"])

            return run

        await _run_tool(client, message, kind="toaudio", label=f"{kind.upper()} audio", make=make)

    async def screens(client, message):
        """/screens [4|9|16] — timestamp-sampled contact sheet."""
        count = screen_count(_command_text(message).split()[1:])

        def make(src: Path):
            async def run(job: Job) -> Path:
                info = await probe(src)
                if not info.get("has_video"):
                    raise ValueError("No video stream was found.")
                dst = Path(tempfile.mkdtemp(prefix="screens-")) / f"{src.stem}-screens.jpg"
                job.detail = "building the sheet"
                return await run_tool(
                    job,
                    screens_command(src, dst, count=count, duration=info["duration"]),
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
            source = await _source_message(message).download()
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
            args = _command_text(message).split()[1:]
            problem = None
            if name in ('compress', 'mediainfo') and args:
                problem = f'Use /{name} without arguments.'
            elif name in ('toaudio', 'screens'):
                try:
                    (audio_options if name == 'toaudio' else screen_count)(args)
                except ValueError as error:
                    problem = str(error)
            elif name == 'encode':
                try:
                    parse_options(args)
                except ValueError:
                    problem = USAGE
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
            try:
                # Info-only probing does not submit a conversion job. Preserve
                # missing-media usage replies, but reject queued tools before
                # download/progress when capacity is already unavailable.
                if name != 'mediainfo' and _source_media(message) is not None:
                    ctx.jobs.ensure_capacity()
                return await handler(client, message)
            except JobAdmissionError:
                # Submit rechecks after download: another request may have used
                # the last slot. The returned source may be caller-owned, so do
                # not guess ownership and unlink it on rejection.
                await reply(message, "No Encoder job was admitted. The queue is full or shutting down. Wait for active work to finish before retrying. No conversion started; any downloaded source was left unchanged.")
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
