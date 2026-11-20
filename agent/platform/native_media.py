"""Offline-only native decoding policy; remote egress mediation is not available.

A public-URL preflight cannot constrain a native decoder's redirect/DNS stack.
Even local files can be playlists, so both protocols and demuxers are restricted.
This is an egress restriction, not an OS sandbox for hostile media parsers.
"""
import asyncio
import re
from pathlib import Path

POLICY = '-protocol_whitelist file,pipe -format_whitelist wav,mp3,flac,ogg,mov,matroska,aac'
PROBE_TIMEOUT = 5
REQUIRED_OPTIONS = {'-protocol_whitelist', '-format_whitelist'}


class NativeMediaError(RuntimeError):
    """The native media boundary cannot be enforced."""


def local_source(source):
    if (not isinstance(source, str) or not source or ':' in source
            or source.startswith('//') or '\\' in source
            or any(ord(char) < 32 or ord(char) == 127 for char in source)):
        raise NativeMediaError('Remote music playback is disabled until safe fetching is available. Reply to a downloaded audio file instead.')
    try:
        path = Path(source).resolve(strict=True)
        if not path.is_file():
            raise ValueError('not a file')
        return str(path)
    except (OSError, ValueError, RuntimeError):
        raise NativeMediaError('Playback requires an available local audio file. Remote music playback is disabled until safe fetching is available.') from None


async def require_offline_options():
    """Fail closed if installed tools would discard the required input options.

    py-tgcalls cleanup_commands filters flags using the same help-line grammar.
    Bound and reap help subprocesses, including on cancellation. Check each use
    rather than caching a result across native binary replacement.
    """
    for binary in ('ffmpeg', 'ffprobe'):
        process = None
        try:
            process = await asyncio.create_subprocess_exec(
                binary, '-h', 'full', stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.DEVNULL)
            output, _ = await asyncio.wait_for(process.communicate(), timeout=PROBE_TIMEOUT)
            supported = set(re.findall(r'(?m)^ *(-\w+).*?\s+', output.decode('utf-8', errors='replace')))
            if process.returncode or not REQUIRED_OPTIONS <= supported:
                raise NativeMediaError('Native media tools do not support the required offline decoding policy.')
        except (OSError, asyncio.TimeoutError):
            raise NativeMediaError('Native media tools are unavailable or their offline policy could not be verified.') from None
        finally:
            if process is not None and process.returncode is None:
                try:
                    process.kill()
                except ProcessLookupError:
                    pass
                await process.wait()
