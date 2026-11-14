"""Encoder module — real FFmpeg encoding.

Behaviour studied in ``abhinai2244/ENCODING-BOT`` (AGPL-3.0): its source was
read for workflow and command semantics only; none of its code is copied, so
nothing here inherits that licence.

The binary comes from ``imageio-ffmpeg`` when the host has no ``ffmpeg`` on
PATH. ``ffprobe`` is not assumed: streams are parsed from ffmpeg's own banner.
"""

from __future__ import annotations

import asyncio
import html
import logging
import re
import shutil
import tempfile
from pathlib import Path

from ..platform.jobs import Job
from ..platform.manifest import PluginManifest
from ..ui.tables import Table, kv_table, panel

logger = logging.getLogger(__name__)

MANIFEST = PluginManifest(
    slug="encoder",
    name="Encoder",
    version="1.0.0",
    description="FFmpeg video/audio encoding with presets, live progress and output validation.",
    commands=("encode", "encinfo", "enccancel", "encpreset"),
    permissions=("messages.read", "files.write", "process.spawn"),
)

#: name -> (crf, x264 preset). Mirrors the preset idea from ENCODING-BOT.
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
    _, raw = await asyncio.wait_for(process.communicate(), timeout=60)
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


async def run_ffmpeg(job: Job, src: Path, dst: Path, *, preset: str, codec: str, duration: float) -> Path:
    """Run the encode, feeding progress into *job*. Kills the child on cancel."""
    command = build_command(src, dst, preset=preset, codec=codec)
    process = await asyncio.create_subprocess_exec(
        *command,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
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
    except asyncio.CancelledError:
        if process.returncode is None:
            process.kill()
            await process.wait()
        raise

    if process.returncode != 0:
        stderr = (await process.stderr.read()).decode(errors="ignore")[-400:] if process.stderr else ""
        raise RuntimeError(f"ffmpeg exited {process.returncode}: {stderr.strip()}")
    return dst


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
            await message.reply(
                "Reply to a video or document with /encode.\n"
                "Optional: /encode <preset>  (fast, balanced, quality)"
            )
            return

        parts = (getattr(message, "text", "") or "").split()
        preset = parts[1].lower() if len(parts) > 1 else "balanced"
        if preset not in PRESETS:
            await message.reply(f"Unknown preset {preset!r}. Choose: {', '.join(PRESETS)}")
            return

        owner = message.from_user.id
        await message.reply(f"Downloading and queueing ({preset})…")
        try:
            source = await message.reply_to_message.download()
        except Exception as exc:  # noqa: BLE001 - reported to the user
            logger.exception("Download failed for encoder")
            await message.reply(f"Could not download that file: {type(exc).__name__}")
            return
        if not source:
            await message.reply("Telegram returned no file to encode.")
            return

        src = Path(source)
        job = ctx.jobs.submit(
            "encoder",
            owner,
            lambda j: encode_job(j, ctx, src, preset, "h264"),
            label=src.name,
        )
        await message.reply(
            f"Encoding job <code>{job.id}</code> started ({preset}). "
            "Use <code>/enccancel</code> to stop it."
        )
        await job.task

        if job.state.value == "done":
            await message.reply(f"Encode finished: {html.escape(job.label)} → MP4, validated.")
        elif job.state.value == "cancelled":
            await message.reply("Encode cancelled.")
        else:
            await message.reply(f"Encode failed: {html.escape(str(job.error))}")

    async def encinfo(_client, message):
        media = _source_media(message)
        if media is None:
            await message.reply("Reply to a video or document with /encinfo.")
            return
        try:
            source = await message.reply_to_message.download()
        except Exception as exc:  # noqa: BLE001
            await message.reply(f"Could not download that file: {type(exc).__name__}")
            return
        info = await probe(Path(source))
        rows = [
            ("Video", info["video_codec"] or "none"),
            ("Resolution", f"{info['width']}x{info['height']}" if info.get("width") else "n/a"),
            ("Audio", info["audio_codec"] or "none"),
            ("Duration", f"{info['duration']:.2f}s"),
            ("Streams", describe(info)),
        ]
        await message.reply(
            panel(
                "Media info",
                icon=ctx.theme.emoji("gear"),
                subtitle="Probed from the replied file, not from the caption.",
                table=kv_table(rows),
                note="Encode it with <code>/encode fast|balanced|quality</code>.",
            )
        )

    async def enccancel(_client, message):
        owner = message.from_user.id
        prefixes = (getattr(message, "text", "") or "").split()
        target = prefixes[1] if len(prefixes) > 1 else None
        stopped = 0
        for job in ctx.jobs.active():
            if job.owner_id != owner:
                continue
            if target and job.id != target:
                continue
            stopped += bool(ctx.jobs.cancel(job.id, owner_id=owner))
        await message.reply(
            f"Cancelled {stopped} job(s)." if stopped else "Nothing of yours was running."
        )

    async def encpreset(_client, message):
        table = Table(
            headers=("Preset", "CRF", "x264 speed"),
            rows=tuple(
                (name, str(crf), x264) for name, (crf, x264) in PRESETS.items()
            ),
            aligns=("left", "right", "left"),
        )
        await message.reply(
            panel(
                "Encoding presets",
                icon=ctx.theme.emoji("fire"),
                subtitle="Lower CRF means higher quality and a bigger file.",
                table=table,
                note="Pick one with <code>/encode &lt;preset&gt;</code>.",
                footer="H.264 in an MP4 container, validated after encoding.",
            )
        )

    return MANIFEST, {
        "encode": encode,
        "encinfo": encinfo,
        "enccancel": enccancel,
        "encpreset": encpreset,
    }
