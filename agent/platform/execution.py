"""Execution boundaries for built-in optional modules; not a Python sandbox."""
from __future__ import annotations

import asyncio
import logging
from contextvars import ContextVar
from functools import wraps

from .policy import PROTECTED_PLUGINS
from .plugin_access import OPTIONAL

logger = logging.getLogger(__name__)
# Registration ownership, then execution ownership inherited by child tasks.
REGISTERING = ContextVar('registering_plugin', default=None)
GROUP_EXECUTION = ContextVar('group_plugin_execution', default=None)


class PluginGate:
    def __init__(self, access, runtime, jobs):
        self.access = access
        self.runtime = runtime
        self.jobs = jobs
        self._seen = set()
        self._cleanups = {}
        self._running = {}
        jobs.eligibility_check = self.allowed

    def cleanup_hook(self, slug, callback):
        """callback(group_id) must release only this module's group resources."""
        self._cleanups[slug] = callback

    async def allowed(self, group_id, slug):
        if slug in PROTECTED_PLUGINS:
            return True
        if slug not in OPTIONAL:
            return False
        try:
            if self.runtime.wants_disabled(slug) or not self.runtime.registry.is_enabled(slug):
                return False
            return await self.access.eligible(group_id, slug)
        except Exception:
            logger.warning('Optional plugin eligibility unavailable: %s', slug)
            return False

    async def cleanup(self, group_id, slug):
        children = [task for task in self._running.get((group_id, slug), ())
                    if task is not asyncio.current_task()]
        for task in children:
            task.cancel()
        if children:
            await asyncio.gather(*children, return_exceptions=True)
        await self.jobs.cancel_group(group_id, slug)
        callback = self._cleanups.get(slug)
        if callback:
            try:
                await callback(group_id)
            except Exception:
                logger.exception('Plugin cleanup failed: %s group=%s', slug, group_id)
                return  # retain scope so the next reconciliation retries
        self._seen.discard((group_id, slug))

    def wrap(self, slug, handler, *, callback=False, silent=False):
        if slug in PROTECTED_PLUGINS:
            return handler

        @wraps(handler)
        async def guarded(client, update, *args):
            message = getattr(update, 'message', None) if callback else update
            chat = getattr(message, 'chat', None)
            group_id = getattr(chat, 'id', None)
            # Private tools retain their existing deployment-scoped behavior.
            # Missing callback origin is not evidence of a private conversation.
            if type(group_id) is not int:
                if callback:
                    await update.answer('This control has no verifiable chat context.', show_alert=True)
                return
            is_group = group_id < 0
            try:
                runtime_enabled = (not self.runtime.wants_disabled(slug)
                                   and self.runtime.registry.is_enabled(slug))
            except Exception:
                runtime_enabled = False
            if not runtime_enabled or (is_group and not await self.allowed(group_id, slug)):
                if is_group:
                    await self.cleanup(group_id, slug)
                if callback:
                    await update.answer('Plugin not active or approved for this group.', show_alert=True)
                elif not silent:
                    from ..utils.rich import reply
                    await reply(message, 'This optional plugin is not active or Owner-approved for this group. Ask an administrator to check the plugin settings.')
                return
            token = GROUP_EXECUTION.set((group_id, slug) if is_group else None)
            if is_group:
                self._seen.add((group_id, slug))
            child = None
            try:
                if not is_group:
                    return await handler(client, update, *args)
                # Own a child task, never cancel a shared dispatcher worker.
                child = asyncio.create_task(handler(client, update, *args))
                self._running.setdefault((group_id, slug), set()).add(child)
                return await child
            except asyncio.CancelledError:
                if asyncio.current_task().cancelling():
                    raise
                return None  # group cleanup cancelled the owned child only
            except Exception as exc:
                logger.error('Optional plugin execution failed: %s (%s)', slug, type(exc).__name__)
                if callback:
                    await update.answer('Plugin action failed; moderation remains available.', show_alert=True)
                elif not silent:
                    from ..utils.rich import reply
                    await reply(message, 'This plugin action failed; moderation remains available.')
            finally:
                if child is not None:
                    running = self._running.get((group_id, slug), set())
                    running.discard(child)
                    if not running:
                        self._running.pop((group_id, slug), None)
                GROUP_EXECUTION.reset(token)
        return guarded

    async def reconcile(self):
        """Cross-process revocation fallback; no cached approval for new calls."""
        for group_id, slug in tuple(self._seen):
            if not await self.allowed(group_id, slug):
                await self.cleanup(group_id, slug)

    async def watch(self, stop_event, interval=2.0):
        while not stop_event.is_set():
            try:
                await self.reconcile()
            except Exception:
                logger.exception('Plugin reconciliation failed; retrying without affecting core.')
            try:
                await asyncio.wait_for(stop_event.wait(), timeout=interval)
            except asyncio.TimeoutError:
                pass
