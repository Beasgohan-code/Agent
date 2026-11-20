"""The small media tools: their command lines, and the job's return value."""

import asyncio
from pathlib import Path

from agent.modules.encoder import audio_command, clip_command, screens_command
from agent.platform.jobs import JobQueue, JobState

SRC = Path("/tmp/in.mkv")
DST = Path("/tmp/out.mp4")


def test_a_clip_is_stream_copied_not_re_encoded():
    command = clip_command(SRC, DST, start=12, length=30)

    assert command[command.index("-ss") + 1] == "12"
    assert command[command.index("-t") + 1] == "30"
    assert command[command.index("-c") + 1] == "copy"
    assert command[-1] == str(DST)


def test_audio_is_mp3_at_a_stated_bitrate():
    command = audio_command(SRC, DST)

    assert "libmp3lame" in command
    assert command[command.index("-b:a") + 1] == "192k"
    assert "-vn" in command


def test_the_contact_sheet_is_one_tiled_frame():
    command = screens_command(SRC, DST, count=9, duration=90)

    assert "-frames:v" in command and command[command.index("-frames:v") + 1] == "1"
    filter_arg = command[command.index("-vf") + 1]
    assert "tile=3x3" in filter_arg and "scale=320:-2" in filter_arg
    assert command[-1] == str(DST)


def test_a_job_keeps_what_its_runner_returned():
    queue = JobQueue()

    async def main():
        job = queue.submit("test", 1, lambda _job: asyncio.sleep(0, result="/tmp/out.mp4"))
        await job.task
        return job

    job = asyncio.run(main())

    assert job.state is JobState.DONE
    assert job.result == "/tmp/out.mp4"
    assert job.as_dict()["result"] == "/tmp/out.mp4"
