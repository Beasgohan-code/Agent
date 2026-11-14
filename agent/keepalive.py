"""Public web-service heartbeat, independent of Telegram readiness."""
import asyncio
import time
from urllib.parse import urlsplit

import aiohttp


def health_target(base):
    """Accept a deployment origin only; never credentials, queries or fragments."""
    if not base:
        return None
    parts = urlsplit(base.strip())
    if (parts.scheme not in ('http', 'https') or not parts.hostname
            or parts.username or parts.password or parts.query or parts.fragment
            or parts.path not in ('', '/')):
        raise ValueError('Keepalive requires a plain HTTP(S) deployment origin')
    return base.strip().rstrip('/') + '/health'


class KeepAlive:
    def __init__(self, origin=None):
        self.target = health_target(origin)
        self.attempts = self.successes = self.consecutive_failures = 0
        self.last_success = self.last_error = None

    def snapshot(self):
        return dict(enabled=bool(self.target), attempts=self.attempts,
                    successes=self.successes, consecutive_failures=self.consecutive_failures,
                    last_success=self.last_success, last_error=self.last_error,
                    interval_seconds=300)

    async def probe(self, session):
        self.attempts += 1
        try:
            async with session.get(self.target, allow_redirects=False) as response:
                if not 200 <= response.status < 300:
                    raise RuntimeError('Unhealthy HTTP response')
            self.successes += 1
            self.last_success = int(time.time())
            self.consecutive_failures = 0
            self.last_error = None
        except Exception as error:
            self.consecutive_failures += 1
            self.last_error = type(error).__name__  # never expose URL or response body

    async def run(self):
        if not self.target:
            return
        async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=10),
                                         trust_env=False) as session:
            while True:
                await self.probe(session)
                await asyncio.sleep(300)
