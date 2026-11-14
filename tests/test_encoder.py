"""Encoder module — exercised against a real FFmpeg binary."""

import asyncio
import subprocess

import pytest

from agent.modules import encoder as enc
from agent.platform.jobs import Job


@pytest.fixture(scope="module")
def sample_video(tmp_path_factory):
    """A genuine 1-second H.264 file produced by ffmpeg itself."""
    target = tmp_path_factory.mktemp("media") / "sample.mp4"
    subprocess.run(
        [
            enc.ffmpeg_path(), "-hide_banner", "-loglevel", "error", "-y",
            "-f", "lavfi", "-i", "testsrc=duration=1:size=160x120:rate=10",
            "-c:v", "libx264", "-pix_fmt", "yuv420p", str(target),
        ],
        check=True,
        timeout=120,
    )
    return target


def test_ffmpeg_is_available():
    assert enc.ffmpeg_path()


def test_probe_reads_real_streams(sample_video):
    info = asyncio.run(enc.probe(sample_video))

    assert info["has_video"] is True
    assert info["video_codec"] == "h264"
    assert (info["width"], info["height"]) == (160, 120)
    assert 0.9 <= info["duration"] <= 1.1


def test_build_command_uses_the_preset():
    command = enc.build_command(enc.Path("in.mp4"), enc.Path("out.mp4"), preset="fast")

    assert "-crf" in command and "28" in command
    assert "veryfast" in command
    assert "libx264" in command


def test_build_command_supports_hevc():
    command = enc.build_command(enc.Path("in.mp4"), enc.Path("out.mp4"), codec="h265")

    assert "libx265" in command


def test_run_ffmpeg_produces_a_valid_file(sample_video, tmp_path):
    job = Job(id="j1", module="encoder", owner_id=1)
    out = tmp_path / "out.mp4"

    asyncio.run(enc.run_ffmpeg(job, sample_video, out, preset="fast", codec="h264", duration=1.0))

    assert out.exists() and out.stat().st_size > 0
    assert asyncio.run(enc.validate_output(out)) is True


def test_validation_rejects_a_corrupt_file(tmp_path):
    broken = tmp_path / "broken.mp4"
    broken.write_bytes(b"not a video at all")

    assert asyncio.run(enc.validate_output(broken)) is False


def test_validation_rejects_an_empty_file(tmp_path):
    empty = tmp_path / "empty.mp4"
    empty.write_bytes(b"")

    assert asyncio.run(enc.validate_output(empty)) is False


def test_encode_job_runs_end_to_end(sample_video, tmp_path):
    from agent.platform.jobs import Job

    job = Job(id="j2", module="encoder", owner_id=1)

    produced = asyncio.run(enc.encode_job(job, None, sample_video, "fast", "h264"))

    assert produced.exists()
    assert asyncio.run(enc.validate_output(produced)) is True


def test_describe_is_human_readable():
    text = enc.describe({"has_video": True, "video_codec": "h264", "width": 160,
                         "height": 120, "duration": 1.0})

    assert "h264" in text and "160x120" in text
