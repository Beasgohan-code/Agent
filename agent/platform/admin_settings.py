"""Group administrator options; no configured-database fallback."""

SCHEMA = (
    """CREATE TABLE IF NOT EXISTS agent_admin_settings (
    tenant TEXT NOT NULL, group_id BIGINT NOT NULL CHECK(group_id<0),
    anonadmin BOOLEAN NOT NULL DEFAULT false, adminerror BOOLEAN NOT NULL DEFAULT true,
    PRIMARY KEY(tenant,group_id))""",
    """CREATE TABLE IF NOT EXISTS agent_admin_setting_history (
    id BIGSERIAL PRIMARY KEY, tenant TEXT NOT NULL, group_id BIGINT NOT NULL,
    setting TEXT NOT NULL, enabled BOOLEAN NOT NULL, actor_id BIGINT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now())""",
)


class AdminStateError(RuntimeError):
    """Administrator settings unavailable."""


async def options(ctx, group_id, *, setting=None, enabled=None, actor=None):
    if type(group_id) is not int or not -(2**63) < group_id < 0:
        raise AdminStateError("Use these options inside a group.")
    if setting is not None and (
        setting not in ("anonadmin", "adminerror")
        or type(enabled) is not bool
        or type(actor) is not int
        or not 0 < actor < 2**63
    ):
        raise AdminStateError(
            "A personal administrator identity and valid option are required."
        )
    db = getattr(ctx, "db", None)
    if db is None:
        current = {
            "anonadmin": ctx.chats.get(group_id, "anonadmin", False),
            "adminerror": ctx.chats.get(group_id, "adminerror", True),
        }
        if setting is not None:
            ctx.chats.put(group_id, setting, enabled)
            current[setting] = enabled
        return current
    if not db.connected or getattr(db, "_pool", None) is None:
        raise AdminStateError(
            "Administrator settings unavailable. No change confirmed."
        )
    try:
        async with db._pool.acquire(timeout=5) as conn:
            async with conn.transaction():
                await conn.execute(
                    "INSERT INTO agent_admin_settings(tenant,group_id) VALUES($1,$2) ON CONFLICT DO NOTHING",
                    db.scope,
                    group_id,
                    timeout=5,
                )
                if setting is not None:
                    await conn.execute(
                        f"UPDATE agent_admin_settings SET {setting}=$3 WHERE tenant=$1 AND group_id=$2",
                        db.scope,
                        group_id,
                        enabled,
                        timeout=5,
                    )
                    await conn.execute(
                        "INSERT INTO agent_admin_setting_history(tenant,group_id,setting,enabled,actor_id) VALUES($1,$2,$3,$4,$5)",
                        db.scope,
                        group_id,
                        setting,
                        enabled,
                        actor,
                        timeout=5,
                    )
                return dict(
                    await conn.fetchrow(
                        "SELECT anonadmin,adminerror FROM agent_admin_settings WHERE tenant=$1 AND group_id=$2",
                        db.scope,
                        group_id,
                        timeout=5,
                    )
                )
    except Exception:
        raise AdminStateError(
            "Administrator settings unavailable or result unconfirmed. Refresh before retrying."
        ) from None


async def denied(ctx, message, text):
    from ..utils.rich import reply

    try:
        if not (await options(ctx, message.chat.id))["adminerror"]:
            return
    except AdminStateError:
        pass
    await reply(message, text)
