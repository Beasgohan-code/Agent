"""Reference-backed Encoder controls, independently implemented and bounded."""
import asyncio
import subprocess
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from agent.modules import encoder
from agent.modules.encoder.options import VideoOptions, parse_options
from agent.platform.jobs import Job, JobQueue
from agent.ui.theme import Theme
from test_modules import FakeMessage


@pytest.mark.parametrize('args', [
    ['codec=av1'], ['crf=17'], ['crf=36'], ['crf=nan'], ['crf=١٨'],
    ['height=9999'], ['fps=inf'], ['fps=120'], ['fps=30;rm'],
    ['codec=h264', 'codec=h265'], ['crf=20', 'crf=21'], ['threads=999'],
    ['fast', 'extra'], ['quality', 'height=../../etc'], ['-i', 'file'],
])
def test_invalid_controls_rejected_before_download(args):
    async def scenario():
        request = FakeMessage('/encode ' + ' '.join(args))
        request.reply_to_message = SimpleNamespace(download=AsyncMock())
        ctx = SimpleNamespace(theme=Theme())
        await encoder.build(ctx)[1]['encode'](None, request)
        request.reply_to_message.download.assert_not_awaited()
        assert 'Check Encoder options' in request.replies[-1]
    asyncio.run(scenario())


def test_command_contains_only_bounded_filters_and_explicit_codec():
    preset, codec, options = parse_options(['quality', 'codec=h265', 'height=720', 'fps=23.976', 'crf=22'])
    cmd = encoder.build_command(encoder.Path('in.mp4'), encoder.Path('out.mp4'), preset=preset, codec=codec, options=options)
    assert cmd[cmd.index('-c:v') + 1] == 'libx265'
    assert cmd[cmd.index('-crf') + 1] == '22'
    assert cmd[cmd.index('-vf') + 1] == "scale=-2:'min(ih,720)',fps=23.976"
    assert '+faststart' in cmd


def test_legacy_defaults_remain_balanced_h264_without_filters():
    assert parse_options([]) == ('balanced', 'h264', VideoOptions())
    cmd = encoder.build_command(encoder.Path('in'), encoder.Path('out'))
    assert '-vf' not in cmd and 'libx264' in cmd
    assert cmd[cmd.index('-crf') + 1] == '23'


@pytest.mark.parametrize('settings', [{'crf': True}, {'crf': 0}, {'height': 'evil'}, {'fps': '500'}])
def test_programmatic_invalid_controls_are_also_refused(settings):
    with pytest.raises(ValueError):
        VideoOptions(**settings)


def test_encode_handler_passes_request_scoped_options(tmp_path, monkeypatch):
    async def scenario():
        source, output = tmp_path / 'source.mp4', tmp_path / 'out.mp4'
        source.write_bytes(b'original')
        output.write_bytes(b'converted')
        convert = AsyncMock(return_value=output)
        monkeypatch.setattr(encoder, 'encode_job', convert)
        ctx = SimpleNamespace(theme=Theme(), jobs=JobQueue())
        request = FakeMessage('/encode fast codec=h265 crf=25 height=480 fps=30')
        request.reply_to_message = SimpleNamespace(video=True, download=AsyncMock(return_value=str(source)))
        await encoder.build(ctx)[1]['encode'](None, request)
        call = convert.await_args.args
        assert call[3:] == ('fast', 'h265', VideoOptions(crf=25, height='480', fps='30'))
        assert source.read_bytes() == b'original'
    asyncio.run(scenario())


@pytest.mark.parametrize('source_height, expected', [(120, (160, 120)), (480, (320, 240))])
def test_real_ffmpeg_applies_height_and_framerate(tmp_path, source_height, expected):
    source, output = tmp_path / 'source.mp4', tmp_path / 'scaled.mp4'
    subprocess.run([encoder.ffmpeg_path(), '-hide_banner', '-loglevel', 'error', '-y',
                    '-f', 'lavfi', '-i', f'testsrc=duration=1:size={source_height * 4 // 3}x{source_height}:rate=10',
                    '-c:v', 'libx264', '-pix_fmt', 'yuv420p', str(source)], check=True, timeout=30)
    # Scale larger input down; never upscale input below the selected cap.
    options = VideoOptions(crf=26, height='240', fps='25')
    asyncio.run(encoder.run_ffmpeg(Job('controls', 'encoder', 1), source, output,
                                 preset='fast', codec='h264', duration=1, options=options))
    info = asyncio.run(encoder.probe(output))
    assert (info['width'], info['height']) == expected
    assert asyncio.run(encoder.validate_output(output))
    result = subprocess.run([encoder.ffmpeg_path(), '-hide_banner', '-i', str(output)], capture_output=True, timeout=30)
    assert '25 fps' in result.stderr.decode()
