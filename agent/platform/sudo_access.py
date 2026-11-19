"""Owner-issued, bounded capabilities with transactional PostgreSQL audit.

Only implemented delegation boundaries are grantable. Legacy sudo ID documents
are retained but do not confer capabilities, Premium, or Telegram admin rights.
Schema statements are additive and idempotent startup migrations.
"""

import logging

logger = logging.getLogger(__name__)
CAPABILITY_DESCRIPTIONS = {
    "diagnostics.read": "Sanitized database connection status via /db",
    "health.read": "Read-only process health via /watchdog (no arguments)",
    "plugins.inspect": "Read-only plugin inventory via /plugins",
}
CAPABILITIES = frozenset(CAPABILITY_DESCRIPTIONS)
OWNER_ONLY_CAPABILITIES = frozenset(
    {
        "sudo.manage",
        "premium.manage",
        "plugins.approve",
        "plugins.manage",
        "clones.manage_others",
        "system.restart",
        "system.cleanup",
        "secrets.manage",
    }
)
SCHEMA = (
    """CREATE TABLE IF NOT EXISTS agent_sudo_grants (
        tenant TEXT NOT NULL, user_id BIGINT NOT NULL CHECK(user_id>0),
        capability TEXT NOT NULL, group_id BIGINT NOT NULL DEFAULT 0 CHECK(group_id<=0),
        expires_at TIMESTAMPTZ NOT NULL, reason TEXT NOT NULL,
        granted_by BIGINT NOT NULL, granted_at TIMESTAMPTZ NOT NULL DEFAULT now(),
        PRIMARY KEY(tenant,user_id,capability,group_id))""",
    """CREATE TABLE IF NOT EXISTS agent_sudo_audit (
        id BIGSERIAL PRIMARY KEY, tenant TEXT NOT NULL, actor_id BIGINT NOT NULL,
        user_id BIGINT NOT NULL, capability TEXT NOT NULL, group_id BIGINT NOT NULL,
        action TEXT NOT NULL CHECK(action IN ('grant','revoke')), reason TEXT NOT NULL,
        expires_at TIMESTAMPTZ, changed BOOLEAN NOT NULL,
        created_at TIMESTAMPTZ NOT NULL DEFAULT now())""",
    """CREATE INDEX IF NOT EXISTS agent_sudo_audit_tenant_id
        ON agent_sudo_audit(tenant,id DESC)""",
)


class SudoError(RuntimeError):
    """Authorization or an awaited persistence operation failed."""


class SudoAccess:
    def __init__(self, db, *, owner_id):
        self.db, self.owner_id = db, owner_id

    def _owner(self, actor):
        if type(actor) is not int or not self.owner_id or actor != self.owner_id:
            raise SudoError("Only the bot Owner may manage sudo permissions.")

    @staticmethod
    def _validate(user_id, capability, group_id):
        if type(user_id) is not int or not 0 < user_id < 2**63:
            raise SudoError("Use a positive Telegram user id.")
        if (
            not isinstance(capability, str)
            or capability in OWNER_ONLY_CAPABILITIES
            or capability not in CAPABILITIES
        ):
            raise SudoError(
                "Unknown or Owner-only capability. Available: "
                + ", ".join(sorted(CAPABILITIES))
            )
        if type(group_id) is not int or not -(2**63) < group_id <= 0:
            raise SudoError("Scope must be global or a negative group id.")

    def _pool(self):
        if (
            self.db is None
            or not self.db.connected
            or getattr(self.db, "_pool", None) is None
        ):
            raise SudoError("Database sudo state is unavailable; access denied.")
        return self.db._pool

    async def allowed(self, user_id, capability, group_id=0):
        try:
            self._validate(user_id, capability, group_id)
            async with self._pool().acquire(timeout=5) as conn:
                return bool(
                    await conn.fetchval(
                        """SELECT 1 FROM agent_sudo_grants
                    WHERE tenant=$1 AND user_id=$2 AND capability=$3
                    AND group_id IN (0,$4) AND expires_at>now() LIMIT 1""",
                        self.db.scope,
                        user_id,
                        capability,
                        group_id,
                        timeout=5,
                    )
                )
        except Exception:
            logger.warning("Sudo capability check denied or unavailable")
            return False

    async def grant(self, actor, user_id, capability, *, group_id=0, hours=24, reason):
        return await self._change(actor, user_id, capability, group_id, reason, hours)

    async def revoke(self, actor, user_id, capability, *, group_id=0, reason):
        return await self._change(actor, user_id, capability, group_id, reason, None)

    async def _change(self, actor, user_id, capability, group_id, reason, hours):
        self._owner(actor)
        self._validate(user_id, capability, group_id)
        if not isinstance(reason, str) or not reason.strip() or len(reason) > 300:
            raise SudoError("A reason of 1–300 characters is required.")
        if hours is not None and (type(hours) is not int or not 1 <= hours <= 8760):
            raise SudoError("Expiry must be 1–8760 hours.")
        try:
            async with self._pool().acquire(timeout=5) as conn:
                async with conn.transaction():
                    await conn.execute(
                        "SELECT pg_advisory_xact_lock(hashtextextended($1,0))",
                        self.db.name_for("sudo-capabilities"),
                        timeout=5,
                    )
                    expires = None
                    if hours is not None:
                        expires = await conn.fetchval(
                            """INSERT INTO agent_sudo_grants
                            (tenant,user_id,capability,group_id,expires_at,reason,granted_by)
                            VALUES($1,$2,$3,$4,now()+$5*interval '1 hour',$6,$7)
                            ON CONFLICT(tenant,user_id,capability,group_id) DO UPDATE
                            SET expires_at=EXCLUDED.expires_at,reason=EXCLUDED.reason,
                            granted_by=EXCLUDED.granted_by,granted_at=now() RETURNING expires_at""",
                            self.db.scope,
                            user_id,
                            capability,
                            group_id,
                            hours,
                            reason.strip(),
                            actor,
                            timeout=5,
                        )
                        changed = True
                    else:
                        expires = await conn.fetchval(
                            """DELETE FROM agent_sudo_grants
                            WHERE tenant=$1 AND user_id=$2 AND capability=$3 AND group_id=$4 RETURNING expires_at""",
                            self.db.scope,
                            user_id,
                            capability,
                            group_id,
                            timeout=5,
                        )
                        changed = expires is not None
                    await conn.execute(
                        """INSERT INTO agent_sudo_audit
                        (tenant,actor_id,user_id,capability,group_id,action,reason,expires_at,changed)
                        VALUES($1,$2,$3,$4,$5,$6,$7,$8,$9)""",
                        self.db.scope,
                        actor,
                        user_id,
                        capability,
                        group_id,
                        "grant" if hours is not None else "revoke",
                        reason.strip(),
                        expires,
                        changed,
                        timeout=5,
                    )
            return changed
        except SudoError:
            raise
        except Exception:
            raise SudoError(
                "Sudo change not confirmed; inspect grants before retrying."
            ) from None

    async def listing(self, actor, *, page=0, user_id=None, page_size=50):
        return await self._read(actor, "grants", page, user_id, page_size)

    async def history(self, actor, *, page=0, page_size=50):
        return await self._read(actor, "audit", page, None, page_size)

    async def _read(self, actor, kind, page, user_id, page_size):
        self._owner(actor)
        if type(page) is not int or not 0 <= page <= 10000:
            raise SudoError("Page is out of range.")
        if type(page_size) is not int or not 1 <= page_size <= 50:
            raise SudoError("Page size must be 1–50.")
        if user_id is not None and (
            type(user_id) is not int or not 0 < user_id < 2**63
        ):
            raise SudoError("Use a positive Telegram user id.")
        try:
            async with self._pool().acquire(timeout=5) as conn:
                if kind == "audit":
                    rows = await conn.fetch(
                        "SELECT * FROM agent_sudo_audit WHERE tenant=$1 ORDER BY id DESC LIMIT $3 OFFSET $2",
                        self.db.scope,
                        page * page_size,
                        page_size,
                        timeout=5,
                    )
                else:
                    rows = await conn.fetch(
                        """SELECT *,expires_at>now() AS active FROM agent_sudo_grants WHERE tenant=$1
                        AND ($3::bigint IS NULL OR user_id=$3) ORDER BY user_id,capability,group_id
                        LIMIT $4 OFFSET $2""",
                        self.db.scope,
                        page * page_size,
                        user_id,
                        page_size,
                        timeout=5,
                    )
            return [dict(row) for row in rows]
        except SudoError:
            raise
        except Exception:
            raise SudoError("Sudo records unavailable.") from None
