"""TypeTube public-cluster adapter; existing Meiko HTTP downloader owns bytes.

SDK: https://github.com/playeon/typetube (MIT, licenses/typetube-MIT.txt).
No private API key or parent credentials are passed to the helper.
"""
import asyncio
import json
import re
import shutil
from pathlib import Path
from urllib.parse import urlsplit, parse_qs

from ...platform.net import LinkError, check_target, parse_url

BRIDGE = Path(__file__).resolve().parents[3] / 'tools' / 'typetube' / 'resolve.mjs'
TIMEOUT = 25


def youtube_url(url):
    parts = urlsplit(url)
    host = (parts.hostname or '').lower()
    if host not in ('youtube.com', 'www.youtube.com', 'm.youtube.com', 'music.youtube.com', 'youtu.be'):
        return None
    if parts.port not in (None, 443) or parts.scheme != 'https':
        raise LinkError('Use a standard HTTPS YouTube video link.')
    if host == 'youtu.be':
        video = parts.path.strip('/')
    elif parts.path == '/watch':
        video = parse_qs(parts.query).get('v', [''])[0]
    else:
        match = re.fullmatch(r'/(?:shorts|live)/([A-Za-z0-9_-]{11})/?', parts.path)
        video = match[1] if match else ''
    if not re.fullmatch(r'[A-Za-z0-9_-]{11}', video):
        raise LinkError('Use one YouTube video link, not a channel or playlist.')
    return 'https://www.youtube.com/watch?v=' + video


def available():
    return bool(shutil.which('node') and (BRIDGE.parent / 'node_modules' / 'typetube' / 'package.json').is_file())


async def resolve_audio(url):
    canonical = youtube_url(url)
    if not canonical:
        raise LinkError('TypeTube accepts YouTube video links only.')
    if not available():
        raise LinkError('TypeTube is not installed. The deployment needs Node.js 18+ and npm ci in tools/typetube.')
    process = await asyncio.create_subprocess_exec(shutil.which('node'), str(BRIDGE),
        stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL)
    try:
        stdout, _ = await asyncio.wait_for(process.communicate(json.dumps({'url': canonical}).encode()), timeout=TIMEOUT)
        if process.returncode or len(stdout) > 16384:
            raise ValueError('resolver failed')
        data = json.loads(stdout)
        source = parse_url(data['url'])
        host = (urlsplit(source).hostname or '').lower()
        if urlsplit(source).scheme != 'https' or not host.endswith('.googlevideo.com'):
            raise ValueError('unexpected media host')
        await check_target(source)
        title = data.get('title')
        if not isinstance(title, str) or not title.strip():
            raise ValueError('missing title')
        mime = str(data.get('mime', '')).split(';')[0].strip()
        extension = {'audio/mp4': '.m4a', 'audio/webm': '.webm', 'audio/ogg': '.ogg'}.get(mime)
        if extension is None:
            raise ValueError('unsupported audio container')
        return source, title[:160] + extension
    except asyncio.CancelledError:
        raise
    except Exception:
        raise LinkError('TypeTube could not resolve this audio. The service may be unavailable, rate-limited or region-restricted.') from None
    finally:
        if process.returncode is None:
            process.kill()
            await process.wait()
