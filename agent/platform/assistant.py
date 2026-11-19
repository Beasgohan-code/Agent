"""Database-wide exclusivity for a verified Music assistant account.

A session-level advisory lock is held on a dedicated pool connection. Unlike bot
state it is deliberately not tenant scoped: different sessions for one Telegram
user must not drive two voice engines. No credentials or account IDs are logged.
"""
from __future__ import annotations

import asyncio


class AssistantBusy(RuntimeError):
    pass


class AssistantLease:
    def __init__(self, database, *, interval=5.0):
        self.database = database
        self.interval = interval
        self._connection = None
        self._pool = None
        self._key = None
        self._monitor = None
        self._lost = False

    @property
    def held(self):
        return self._connection is not None and not self._lost and not self._connection.is_closed()

    async def acquire(self, account_id):
        if self._connection is not None:
            raise AssistantBusy('Assistant ownership is already initialized.')
        if not isinstance(account_id, int) or isinstance(account_id, bool) or account_id <= 0:
            raise AssistantBusy('Telegram did not confirm a valid assistant account.')
        db = self.database
        if db is None or not db.connected or db._pool is None:
            raise AssistantBusy('Database is required for assistant exclusivity.')
        self._pool = db._pool
        connection = await self._pool.acquire(timeout=10)
        self._connection = connection
        self._key = f'agent:music:assistant:{account_id}'
        self._lost = False
        try:
            taken = await connection.fetchval(
                'SELECT pg_try_advisory_lock(hashtextextended($1, 0))', self._key)
            if not taken:
                raise AssistantBusy('This assistant account is already in use by another bot.')
        except BaseException:
            await self.release()
            raise

    def watch(self, on_loss):
        if self._monitor is not None:
            return
        async def monitor():
            try:
                while True:
                    await asyncio.sleep(self.interval)
                    if not self.held:
                        break
                    await self._connection.fetchval('SELECT 1', timeout=5)
            except asyncio.CancelledError:
                raise
            except Exception:
                pass
            self._lost = True
            self._monitor = None  # shutdown must not cancel the task awaiting it
            await on_loss()
        self._monitor = asyncio.create_task(monitor(), name='music-assistant-lease')

    async def release(self):
        monitor, self._monitor = self._monitor, None
        if monitor is not None and monitor is not asyncio.current_task():
            monitor.cancel()
            await asyncio.gather(monitor, return_exceptions=True)
        connection, self._connection = self._connection, None
        pool, self._pool = self._pool, None
        key, self._key = self._key, None
        if connection is not None:
            try:
                if not connection.is_closed():
                    await connection.fetchval('SELECT pg_advisory_unlock(hashtextextended($1, 0))', key, timeout=5)
            finally:
                await pool.release(connection, timeout=10)
