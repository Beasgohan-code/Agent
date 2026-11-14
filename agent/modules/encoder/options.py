"""Original bounded controls for the reference Encoder's video settings workflow.

Functional reference: ENCODING-BOT/VideoEncoder/utils/settings.py. No upstream
implementation is imported; all values become validated argv, never shell text.
"""
from dataclasses import dataclass

PRESET_NAMES = ('fast', 'balanced', 'quality')
FPS = ('source', '23.976', '24', '25', '29.97', '30', '50', '59.94', '60')
HEIGHTS = ('source', '240', '360', '480', '576', '720', '1080', '1440', '2160')
USAGE = ('Use /encode [fast|balanced|quality] [codec=h264|h265] '
         '[crf=18..35] [height=source|240|360|480|576|720|1080|1440|2160] '
         '[fps=source|23.976|24|25|29.97|30|50|59.94|60].')


@dataclass(frozen=True)
class VideoOptions:
    crf: int | None = None
    height: str = 'source'
    fps: str = 'source'

    def __post_init__(self):
        if self.crf is not None and (type(self.crf) is not int or not 18 <= self.crf <= 35):
            raise ValueError(USAGE)
        if self.height not in HEIGHTS or self.fps not in FPS:
            raise ValueError(USAGE)

    def filters(self):
        filters = []
        if self.height != 'source':
            # Bound height without upscaling; -2 gives an even aspect-ratio width.
            filters.append(f"scale=-2:'min(ih,{self.height})'")
        if self.fps != 'source':
            filters.append(f'fps={self.fps}')
        return filters


def parse_options(args):
    args = list(args)
    if len(args) > 5 or any(len(arg) > 32 for arg in args):
        raise ValueError(USAGE)
    preset = 'balanced'
    if args and '=' not in args[0]:
        preset = args.pop(0).lower()
    if preset not in PRESET_NAMES:
        raise ValueError(USAGE)
    values = {}
    for arg in args:
        key, sep, value = arg.lower().partition('=')
        if not sep or key not in ('codec', 'crf', 'height', 'fps') or key in values:
            raise ValueError(USAGE)
        values[key] = value
    codec = values.pop('codec', 'h264')
    if codec not in ('h264', 'h265'):
        raise ValueError(USAGE)
    if 'crf' in values:
        raw = values['crf']
        if not raw.isascii() or not raw.isdecimal():
            raise ValueError(USAGE)
        values['crf'] = int(raw)
    return preset, codec, VideoOptions(**values)


def audio_options(args):
    """Container and bitrate are a closed set, never arbitrary FFmpeg flags."""
    args = list(args)
    if len(args) > 2:
        raise ValueError('Use /toaudio [mp3|m4a|flac] [bitrate=128|192|256|320].')
    kind, bitrate = 'mp3', 192
    if args and '=' not in args[0]:
        kind = args.pop(0).lower()
    if kind not in ('mp3', 'm4a', 'flac'):
        raise ValueError('Choose mp3, m4a or flac.')
    if args:
        if len(args) != 1 or args[0] not in ('bitrate=128', 'bitrate=192', 'bitrate=256', 'bitrate=320') or kind == 'flac':
            raise ValueError('Choose bitrate=128|192|256|320 for MP3/M4A; FLAC is lossless and has no bitrate option.')
        bitrate = int(args[0].split('=')[1])
    return kind, bitrate


def screen_count(args):
    if not args:
        return 9
    if len(args) != 1 or args[0] not in ('4', '9', '16'):
        raise ValueError('Use /screens [4|9|16].')
    return int(args[0])
