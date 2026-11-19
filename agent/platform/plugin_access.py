"""Transactional plugin-use permission, distinct from code installation.

This service deliberately requires PostgreSQL. It is not yet a replacement for
runtime routing: callers must check eligibility at every execution boundary and
attach resource teardown before exposing activation to users.
"""
from __future__ import annotations

import json
from contextlib import asynccontextmanager

from .policy import PROTECTED_PLUGINS, OPTIONAL_SLOTS, PRIMARY_FEATURES

OPTIONAL = frozenset({
    "music", "filestore", "encoder", "leech", "linkshare", "postmaker",
    "renamer", "clone", "utilities", "premium", "ai_agent",
})

SCHEMA = (
    """CREATE TABLE IF NOT EXISTS agent_plugin_catalog (
        tenant TEXT NOT NULL, slug TEXT NOT NULL, approved BOOLEAN NOT NULL DEFAULT FALSE,
        updated_by BIGINT NOT NULL, updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
        PRIMARY KEY (tenant, slug))""",
    """CREATE TABLE IF NOT EXISTS agent_group_plugins (
        tenant TEXT NOT NULL, group_id BIGINT NOT NULL CHECK (group_id < 0),
        slug TEXT NOT NULL, activated_by BIGINT NOT NULL,
        activated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
        PRIMARY KEY (tenant, group_id, slug),
        FOREIGN KEY (tenant, slug) REFERENCES agent_plugin_catalog (tenant, slug))""",
    """CREATE TABLE IF NOT EXISTS agent_plugin_config (
        tenant TEXT NOT NULL, group_id BIGINT NOT NULL CHECK (group_id < 0),
        slug TEXT NOT NULL, value JSONB NOT NULL DEFAULT '{}'::jsonb,
        updated_by BIGINT NOT NULL, updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
        PRIMARY KEY (tenant, group_id, slug),
        FOREIGN KEY (tenant, slug) REFERENCES agent_plugin_catalog (tenant, slug))""",
    """CREATE TABLE IF NOT EXISTS agent_plugin_history (
        id BIGSERIAL PRIMARY KEY, tenant TEXT NOT NULL, group_id BIGINT,
        slug TEXT NOT NULL, action TEXT NOT NULL, actor_id BIGINT NOT NULL,
        created_at TIMESTAMPTZ NOT NULL DEFAULT now())""",
    """CREATE TABLE IF NOT EXISTS agent_plugin_resources (
        tenant TEXT NOT NULL, group_id BIGINT NOT NULL, slug TEXT NOT NULL,
        kind TEXT NOT NULL, resource_id TEXT NOT NULL,
        state TEXT NOT NULL DEFAULT 'active' CHECK (state IN ('active', 'cleanup_pending')),
        PRIMARY KEY (tenant, group_id, slug, kind, resource_id),
        FOREIGN KEY (tenant, slug) REFERENCES agent_plugin_catalog (tenant, slug))""",
)


class AccessError(RuntimeError):
    """A plugin access change was refused; no successful change was recorded."""


class PluginAccess:
    def __init__(self, db, *, owner_id: int | None):
        self.db = db
        self.owner_id = owner_id
        self.cleanup_callback = None

    @property
    def tenant(self):
        return self.db.scope

    @staticmethod
    def _slug(slug):
        if slug in PROTECTED_PLUGINS:
            raise AccessError("Mandatory core never uses optional slots.")
        if slug not in OPTIONAL:
            raise AccessError("Unknown optional plugin.")

    @staticmethod
    def _group(group_id):
        if type(group_id) is not int or group_id >= 0:
            raise AccessError("A Telegram group id is required.")

    def _owner(self, actor_id):
        if type(actor_id) is not int or actor_id <= 0 or not self.owner_id or actor_id != self.owner_id:
            raise AccessError("Only the bot Owner may change global approval.")

    async def _admin(self, client, message):
        from ..modules.moderation import is_moderator
        from pyrogram.enums import ChatType
        chat = getattr(message, "chat", None)
        self._group(getattr(chat, "id", None))
        if getattr(chat, "type", None) not in (ChatType.GROUP, ChatType.SUPERGROUP):
            raise AccessError("Plugin activation is group-only.")
        # Bot ownership is not a substitute for group administrator rights.
        if not await is_moderator(client, message, need="can_manage_chat"):
            raise AccessError("Group management permission is required.")
        user = getattr(message, "from_user", None)
        if type(getattr(user, "id", None)) is not int or user.id <= 0:
            raise AccessError("An identified administrator is required.")
        return chat.id, user.id

    @asynccontextmanager
    async def _transaction(self):
        pool = getattr(self.db, "_pool", None)
        if not getattr(self.db, "connected", False) or pool is None:
            raise AccessError("Database is required; no local fallback is permitted.")
        async with pool.acquire() as conn:
            async with conn.transaction():
                yield conn

    async def _history(self, conn, slug, action, actor_id, group_id=None):
        await conn.execute(
            "INSERT INTO agent_plugin_history (tenant, group_id, slug, action, actor_id) VALUES ($1,$2,$3,$4,$5)",
            self.tenant, group_id, slug, action, actor_id,
        )

    async def _catalog_lock(self, conn, slug):
        approved = await conn.fetchval(
            "SELECT approved FROM agent_plugin_catalog WHERE tenant=$1 AND slug=$2 FOR SHARE",
            self.tenant, slug,
        )
        if approved is not True:
            raise AccessError("The Owner has not approved this plugin.")

    async def _group_lock(self, conn, group_id):
        await conn.execute(
            "SELECT pg_advisory_xact_lock(hashtextextended($1, 0))",
            f"agent:plugins:{self.tenant}:{group_id}",
        )

    async def approve(self, slug, *, actor_id):
        self._owner(actor_id)
        self._slug(slug)
        async with self._transaction() as conn:
            await conn.execute(
                """INSERT INTO agent_plugin_catalog (tenant,slug,approved,updated_by)
                VALUES ($1,$2,TRUE,$3) ON CONFLICT (tenant,slug) DO UPDATE
                SET approved=TRUE, updated_by=$3, updated_at=now()""",
                self.tenant, slug, actor_id,
            )
            await self._history(conn, slug, "approved", actor_id)

    async def revoke(self, slug, *, actor_id):
        self._owner(actor_id)
        self._slug(slug)
        async with self._transaction() as conn:
            # UPDATE takes an exclusive row lock, serializing with activations'
            # FOR SHARE approval locks. New activation must recheck after revoke.
            await conn.execute(
                """UPDATE agent_plugin_catalog SET approved=FALSE,updated_by=$3,updated_at=now()
                WHERE tenant=$1 AND slug=$2""", self.tenant, slug, actor_id,
            )
            affected = await conn.fetch(
                "DELETE FROM agent_group_plugins WHERE tenant=$1 AND slug=$2 RETURNING group_id",
                self.tenant, slug,
            )
            await conn.execute(
                "UPDATE agent_plugin_resources SET state='cleanup_pending' WHERE tenant=$1 AND slug=$2",
                self.tenant, slug,
            )
            for row in affected:
                await self._history(conn, slug, "revoked", actor_id, row["group_id"])
            await self._history(conn, slug, "blocked", actor_id)
        groups = [row["group_id"] for row in affected]
        if self.cleanup_callback:
            for group_id in groups:
                await self.cleanup_callback(group_id, slug)
        return groups

    async def activate(self, client, message, slug):
        self._slug(slug)
        group_id, actor_id = await self._admin(client, message)
        async with self._transaction() as conn:
            await self._catalog_lock(conn, slug)
            await self._group_lock(conn, group_id)
            existing = await conn.fetchval(
                "SELECT 1 FROM agent_group_plugins WHERE tenant=$1 AND group_id=$2 AND slug=$3",
                self.tenant, group_id, slug,
            )
            if existing:
                return False
            count = await conn.fetchval(
                "SELECT count(*) FROM agent_group_plugins WHERE tenant=$1 AND group_id=$2",
                self.tenant, group_id,
            )
            if count >= OPTIONAL_SLOTS:
                raise AccessError("All three optional plugin slots are in use.")
            await conn.execute(
                "INSERT INTO agent_group_plugins (tenant,group_id,slug,activated_by) VALUES ($1,$2,$3,$4)",
                self.tenant, group_id, slug, actor_id,
            )
            await self._history(conn, slug, "activated", actor_id, group_id)
        return True

    async def deactivate(self, client, message, slug):
        self._slug(slug)
        group_id, actor_id = await self._admin(client, message)
        async with self._transaction() as conn:
            await self._group_lock(conn, group_id)
            removed = await conn.fetchval(
                "DELETE FROM agent_group_plugins WHERE tenant=$1 AND group_id=$2 AND slug=$3 RETURNING 1",
                self.tenant, group_id, slug,
            )
            await conn.execute(
                "UPDATE agent_plugin_resources SET state='cleanup_pending' WHERE tenant=$1 AND group_id=$2 AND slug=$3",
                self.tenant, group_id, slug,
            )
            if removed:
                await self._history(conn, slug, "deactivated", actor_id, group_id)
        if self.cleanup_callback:
            await self.cleanup_callback(group_id, slug)
        return bool(removed)

    async def status(self, client, message):
        group_id, _ = await self._admin(client, message)
        async with self._transaction() as conn:
            rows = await conn.fetch(
                """SELECT c.slug,c.approved,(p.slug IS NOT NULL) AS active
                FROM agent_plugin_catalog c LEFT JOIN agent_group_plugins p
                ON c.tenant=p.tenant AND c.slug=p.slug AND p.group_id=$2
                WHERE c.tenant=$1 ORDER BY c.slug""", self.tenant, group_id,
            )
        state = {row["slug"]: dict(row) for row in rows}
        return [state.get(slug, {"slug": slug, "approved": False, "active": False})
                for slug in sorted(OPTIONAL, key=lambda slug: (PRIMARY_FEATURES.index(slug) if slug in PRIMARY_FEATURES else len(PRIMARY_FEATURES), slug))]

    async def eligible(self, group_id, slug):
        self._group(group_id)
        if slug in PROTECTED_PLUGINS:
            return True
        self._slug(slug)
        async with self._transaction() as conn:
            return bool(await conn.fetchval(
                """SELECT 1 FROM agent_group_plugins p JOIN agent_plugin_catalog c
                USING (tenant,slug) WHERE p.tenant=$1 AND p.group_id=$2 AND p.slug=$3 AND c.approved""",
                self.tenant, group_id, slug,
            ))

    async def configure(self, client, message, slug, value):
        self._slug(slug)
        group_id, actor_id = await self._admin(client, message)
        if not isinstance(value, dict):
            raise AccessError("Plugin configuration must be an object.")
        encoded = json.dumps(value, allow_nan=False)
        if len(encoded.encode()) > 16384:
            raise AccessError("Plugin configuration exceeds 16 KiB.")
        async with self._transaction() as conn:
            await self._catalog_lock(conn, slug)
            await self._group_lock(conn, group_id)
            active = await conn.fetchval(
                "SELECT 1 FROM agent_group_plugins WHERE tenant=$1 AND group_id=$2 AND slug=$3",
                self.tenant, group_id, slug,
            )
            if not active:
                raise AccessError("Activate the approved plugin before configuring it.")
            await conn.execute(
                """INSERT INTO agent_plugin_config (tenant,group_id,slug,value,updated_by)
                VALUES ($1,$2,$3,$4::jsonb,$5) ON CONFLICT (tenant,group_id,slug)
                DO UPDATE SET value=$4::jsonb,updated_by=$5,updated_at=now()""",
                self.tenant, group_id, slug, encoded, actor_id,
            )
            await self._history(conn, slug, "configured", actor_id, group_id)
