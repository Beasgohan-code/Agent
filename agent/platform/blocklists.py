"""Bounded canonical blocklist policy with transactional revisions and safe globs."""

import copy
import json
import unicodedata
from functools import lru_cache

SCHEMA = (
    """CREATE TABLE IF NOT EXISTS agent_blocklists (
    tenant TEXT NOT NULL, group_id BIGINT NOT NULL CHECK(group_id<0),
    policy JSONB NOT NULL, version BIGINT NOT NULL DEFAULT 0, PRIMARY KEY(tenant,group_id))""",
    """CREATE TABLE IF NOT EXISTS agent_blocklist_revisions (
    tenant TEXT NOT NULL, group_id BIGINT NOT NULL, version BIGINT NOT NULL,
    actor_id BIGINT NOT NULL, operation TEXT NOT NULL, policy JSONB NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(), PRIMARY KEY(tenant,group_id,version),
    FOREIGN KEY(tenant,group_id) REFERENCES agent_blocklists(tenant,group_id))""",
)
DEFAULT = {"entries": [], "mode": "nothing", "seconds": 0, "delete": True, "reason": ""}


class BlocklistError(RuntimeError):
    """Blocklist policy could not be validated, read or committed."""


def normalize(text):
    return " ".join(
        "".join(
            c
            for c in unicodedata.normalize("NFKD", text.casefold())
            if not unicodedata.combining(c)
        ).split()
    )


@lru_cache(maxsize=512)
def compiled(pattern):
    """Bitset NFA: linear text scan, no backtracking and no arbitrary regex."""
    tokens = []
    i = 0
    while i < len(pattern):
        char = pattern[i]
        if char == "\\":
            i += 1
            if i == len(pattern):
                raise BlocklistError("A trigger cannot end with an unpaired escape.")
            tokens.append(("literal", pattern[i]))
        elif char == "*":
            end = i + 1
            while end < len(pattern) and pattern[end] == "*":
                end += 1
            tokens.append(("all" if end - i > 1 else "star", ""))
            i = end - 1
        elif char == "?":
            tokens.append(("one", ""))
        else:
            tokens.append(("literal", char))
        i += 1
    if not tokens or not any(kind == "literal" for kind, _ in tokens):
        raise BlocklistError(
            "Triggers need at least one literal character; wildcard-only triggers are refused."
        )
    literals = {}
    one = star = all_chars = 0
    for i, (kind, char) in enumerate(tokens):
        bit = 1 << i
        if kind == "literal":
            literals[char] = literals.get(char, 0) | bit
        elif kind == "one":
            one |= bit
        elif kind == "star":
            star |= bit
        else:
            all_chars |= bit
    return literals, one, star, all_chars, 1 << len(tokens), tokens


def word(char):
    return char.isalnum() or char == "_"


def matches(pattern, text, *, filename=False, prefix=False):
    if not isinstance(text, str) or len(text) > 8192:
        return False
    text = normalize(text)
    literals, one, star, all_chars, final, tokens = compiled(pattern)
    stars = star | all_chars
    state = 0
    start_word = tokens[0][0] == "literal" and word(tokens[0][1])
    end_word = tokens[-1][0] == "literal" and word(tokens[-1][1])
    for pos in range(len(text) + 1):
        if (
            not filename
            and not prefix
            and (not start_word or pos == 0 or not word(text[pos - 1]))
        ) or ((filename or prefix) and pos == 0):
            state |= 1
        state |= (state & stars) << 1  # adjacent star runs are collapsed when compiling
        if state & final and (
            pos == len(text) or (not filename and (not end_word or not word(text[pos])))
        ):
            return True
        if pos == len(text):
            break
        char = text[pos]
        allowed = literals.get(char, 0) | (one if not char.isspace() else 0)
        state = ((state & allowed) << 1) | (
            state & (all_chars | (star if not char.isspace() else 0))
        )
    return False


def trigger(value):
    if not isinstance(value, str) or not 1 <= len(value.strip()) <= 128:
        raise BlocklistError("Triggers must contain 1–128 characters.")
    value = normalize(value)
    if not value or len(value) > 256:
        raise BlocklistError("Normalized trigger is empty or too long.")
    selector, separator, tail = value.partition(":")
    pattern = (
        tail.strip()
        if separator and selector in ("file", "prefix", "exact", "name", "username")
        else value
    )
    if separator and selector in ("file", "prefix", "exact", "name", "username"):
        value = selector + ":" + pattern
    if value.startswith(
        (
            "stickerpack:",
            "forward:",
            "inline:",
            "lookalike:",
        )
    ):
        raise BlocklistError(
            "Supported selectors: file:, prefix:, exact:, name:, username:."
        )
    compiled(pattern)
    return value


def find_match(policy, message):
    text = "\n".join(
        str(getattr(message, key, None) or "") for key in ("text", "caption")
    ).strip()
    filenames = [
        getattr(getattr(message, kind, None), "file_name", None)
        for kind in ("document", "audio", "video", "animation")
    ]
    for entry in policy["entries"]:
        name = entry["trigger"]
        if name.startswith("file:"):
            hit = any(
                matches(name[5:], name_, filename=True) for name_ in filenames if name_
            )
        elif name.startswith("prefix:"):
            hit = bool(text) and matches(name[7:], text, prefix=True)
        elif name.startswith("exact:"):
            hit = bool(text) and matches(name[6:], text, filename=True)
        elif name.startswith("name:"):
            user = getattr(message, "from_user", None)
            display = " ".join(
                str(getattr(user, key, None) or "")
                for key in ("first_name", "last_name")
            ).strip()
            hit = bool(display) and matches(name[5:], display)
        elif name.startswith("username:"):
            username = getattr(getattr(message, "from_user", None), "username", None)
            hit = bool(username) and matches(name[9:], username, filename=True)
        else:
            hit = bool(text) and matches(name, text)
        if hit:
            return entry
    return None


def apply(policy, operation, value):
    work = copy.deepcopy(policy)
    if operation in ("add_many", "remove_many"):
        if not isinstance(value, (list, tuple)) or not 1 <= len(value) <= 20:
            raise BlocklistError("Bulk edits require 1–20 triggers.")
        single = "add" if operation == "add_many" else "remove"
        for item in value:
            work = apply(work, single, item)
        return work
    if operation == "add" and isinstance(value, (list, tuple)) and len(value) == 2:
        name = trigger(value[0])
        reason = value[1]
        if not isinstance(reason, str) or len(reason) > 500:
            raise BlocklistError("Blocklist reasons are limited to 500 characters.")
        existing = next(
            (entry for entry in work["entries"] if entry["trigger"] == name), None
        )
        if existing is None:
            if len(work["entries"]) >= 100:
                raise BlocklistError(
                    "This group has 100 blocklist triggers. Remove one before adding another."
                )
            work["entries"].append({"trigger": name, "reason": reason})
        else:
            existing["reason"] = reason
    elif operation == "remove":
        name = trigger(value)
        work["entries"] = [
            entry for entry in work["entries"] if entry["trigger"] != name
        ]
    elif operation == "clear":
        work["entries"] = []
    elif (
        operation == "mode"
        and isinstance(value, (list, tuple))
        and len(value) == 2
        and type(value[1]) is int
        and (
            (value[0] in ("nothing", "warn", "ban", "mute", "kick") and value[1] == 0)
            or (value[0] in ("tban", "tmute") and 60 <= value[1] <= 365 * 86400)
        )
    ):
        work["mode"], work["seconds"] = value
    elif operation == "delete" and type(value) is bool:
        work["delete"] = value
    elif operation == "reason" and isinstance(value, str) and len(value) <= 500:
        work["reason"] = value
    else:
        raise BlocklistError("Invalid blocklist operation or arguments.")
    return work


async def operate(
    ctx, group_id, operation=None, value=None, *, actor=None, client=None
):
    if type(group_id) is not int or not -(2**63) < group_id < 0:
        raise BlocklistError("Blocklists belong to a group.")
    if operation is not None and (type(actor) is not int or not 0 < actor < 2**63):
        raise BlocklistError("A personal administrator identity is required.")
    if operation == "clear":
        from pyrogram.enums import ChatMemberStatus

        try:
            member = await client.get_chat_member(group_id, actor)
        except Exception:
            raise BlocklistError("Chat ownership could not be verified.") from None
        if getattr(member, "status", None) != ChatMemberStatus.OWNER:
            raise BlocklistError(
                "Only the current chat owner can remove all blocklist triggers."
            )
    db = getattr(ctx, "db", None)
    if db is None:
        policy = copy.deepcopy(ctx.chats.get(group_id, "blocklist", DEFAULT))
        if operation is not None:
            policy = apply(policy, operation, value)
            ctx.chats.put(group_id, "blocklist", policy)
            ctx.chats.log(group_id, "blocklist:" + operation, actor_id=actor)
        return policy
    if not db.connected or getattr(db, "_pool", None) is None:
        raise BlocklistError("PostgreSQL blocklists unavailable. No changes confirmed.")
    try:
        async with db._pool.acquire(timeout=5) as conn:
            async with conn.transaction():
                await conn.execute(
                    "SELECT pg_advisory_xact_lock(hashtextextended($1,0))",
                    db.name_for(f"blocklist:{group_id}"),
                    timeout=5,
                )
                row = await conn.fetchrow(
                    "SELECT policy,version FROM agent_blocklists WHERE tenant=$1 AND group_id=$2",
                    db.scope,
                    group_id,
                    timeout=5,
                )
                if row is None:
                    await conn.execute(
                        "INSERT INTO agent_blocklists(tenant,group_id,policy) VALUES($1,$2,$3::jsonb)",
                        db.scope,
                        group_id,
                        json.dumps(DEFAULT),
                        timeout=5,
                    )
                    row = {"policy": copy.deepcopy(DEFAULT), "version": 0}
                policy = (
                    json.loads(row["policy"])
                    if isinstance(row["policy"], str)
                    else row["policy"]
                )
                if operation is not None:
                    policy = apply(policy, operation, value)
                    version = row["version"] + 1
                    await conn.execute(
                        "UPDATE agent_blocklists SET policy=$3::jsonb,version=$4 WHERE tenant=$1 AND group_id=$2",
                        db.scope,
                        group_id,
                        json.dumps(policy),
                        version,
                        timeout=5,
                    )
                    await conn.execute(
                        "INSERT INTO agent_blocklist_revisions(tenant,group_id,version,actor_id,operation,policy) VALUES($1,$2,$3,$4,$5,$6::jsonb)",
                        db.scope,
                        group_id,
                        version,
                        actor,
                        operation,
                        json.dumps(policy),
                        timeout=5,
                    )
        return policy
    except BlocklistError:
        raise
    except Exception:
        raise BlocklistError(
            "Blocklist result unconfirmed. Refresh before retrying."
        ) from None


SCHEMA += (
    """CREATE TABLE IF NOT EXISTS agent_blocklist_actions (
    tenant TEXT NOT NULL, group_id BIGINT NOT NULL CHECK(group_id<0), message_id BIGINT NOT NULL,
    target_id BIGINT NOT NULL, mode TEXT NOT NULL, reason TEXT NOT NULL,
    outcome TEXT NOT NULL DEFAULT 'pending' CHECK(outcome IN ('pending','applied','partial','unconfirmed')),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(), PRIMARY KEY(tenant,group_id,message_id))""",
)


async def event(ctx, group, message, target, mode, reason, *, outcome=None):
    if (
        any(type(v) is not int or not 0 < v < 2**63 for v in (message, target))
        or type(group) is not int
        or not -(2**63) < group < 0
    ):
        raise BlocklistError("Invalid blocklist action identity.")
    if (
        mode not in ("nothing", "warn", "ban", "mute", "kick", "tban", "tmute")
        or not isinstance(reason, str)
        or len(reason) > 500
    ):
        raise BlocklistError("Invalid blocklist action details.")
    if outcome not in (None, "applied", "partial", "unconfirmed"):
        raise BlocklistError("Invalid blocklist action outcome.")
    db = getattr(ctx, "db", None)
    if db is None:
        if outcome is not None:
            ctx.chats.log(
                group,
                "blocklist:" + mode + ":" + outcome,
                actor_id=None,
                target_id=target,
                reason=reason,
            )
        return True
    if not db.connected or getattr(db, "_pool", None) is None:
        raise BlocklistError("Blocklist action storage unavailable.")
    try:
        async with db._pool.acquire(timeout=5) as conn:
            if outcome is None:
                result = await conn.fetchval(
                    """INSERT INTO agent_blocklist_actions(tenant,group_id,message_id,target_id,mode,reason)
                    VALUES($1,$2,$3,$4,$5,$6) ON CONFLICT DO NOTHING RETURNING message_id""",
                    db.scope,
                    group,
                    message,
                    target,
                    mode,
                    reason,
                    timeout=5,
                )
            else:
                result = await conn.fetchval(
                    """UPDATE agent_blocklist_actions SET outcome=$4 WHERE tenant=$1 AND group_id=$2 AND message_id=$3
                    AND outcome='pending' RETURNING message_id""",
                    db.scope,
                    group,
                    message,
                    outcome,
                    timeout=5,
                )
        return result is not None
    except Exception:
        raise BlocklistError(
            "Blocklist action result unconfirmed; automatic retry was not attempted."
        ) from None


async def history(ctx, group):
    db = getattr(ctx, "db", None)
    if db is None:
        return []
    if not db.connected or getattr(db, "_pool", None) is None:
        raise BlocklistError("Blocklist history unavailable.")
    try:
        async with db._pool.acquire(timeout=5) as conn:
            rows = await conn.fetch(
                """SELECT mode,outcome,target_id,reason,extract(epoch from created_at) AS at
                FROM agent_blocklist_actions WHERE tenant=$1 AND group_id=$2 ORDER BY created_at DESC,message_id DESC LIMIT 10""",
                db.scope,
                group,
                timeout=5,
            )
            revisions = await conn.fetch(
                """SELECT version,operation,actor_id,extract(epoch from created_at) AS at
                FROM agent_blocklist_revisions WHERE tenant=$1 AND group_id=$2 ORDER BY version DESC LIMIT 10""",
                db.scope,
                group,
                timeout=5,
            )
        actions = [
            {
                "action": "blocklist:" + r["mode"] + ":" + r["outcome"],
                "actor": None,
                "target": r["target_id"],
                "reason": r["reason"][:100] + ("…" if len(r["reason"]) > 100 else ""),
                "at": float(r["at"]),
            }
            for r in rows
        ]
        changes = [
            {
                "action": "blocklist:" + r["operation"],
                "actor": r["actor_id"],
                "target": None,
                "reason": f"revision {r['version']} · by {r['actor_id']}",
                "at": float(r["at"]),
            }
            for r in revisions
        ]
        return sorted([*actions, *changes], key=lambda r: r["at"], reverse=True)[:10]
    except Exception:
        raise BlocklistError("Blocklist history unavailable.") from None
