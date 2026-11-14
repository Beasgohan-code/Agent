"""Linkshare module — signed, expiring, revocable share links.

Behaviour studied in ``abhinai2244/LINK-SHAREBOT`` (no licence file at the
repository root, so no code may be reused). Commands keep that project's
names where they do not clash with something already registered here:
``/genlink`` and ``/batch`` are theirs; ``/links`` and ``/revoke`` are ours
because upstream has no equivalent.

It reuses the platform's shared storage and link signer rather than keeping a
private store, and never exposes storage identifiers to the user.
"""

from __future__ import annotations

import logging

from ..platform.links import LinkError
from ..platform.manifest import PluginManifest

logger = logging.getLogger(__name__)

MANIFEST = PluginManifest(
    slug="linkshare",
    name="Linkshare",
    version="1.0.0",
    description="Create, list and revoke signed links for files you own.",
    commands=("genlink", "links", "revoke"),
    permissions=("messages.read", "storage.read", "storage.write"),
)


def build(ctx):
    """Wire commands → handlers for this module."""

    async def genlink(_client, message):
        replied = getattr(message, "reply_to_message", None)
        media = replied and (getattr(replied, "document", None) or getattr(replied, "video", None))
        if not media:
            await message.reply(
                "Reply to a file with /genlink (optional TTL in hours: /genlink 48)."
            )
            return

        parts = (getattr(message, "text", "") or "").split()
        ttl_hours = None
        if len(parts) > 1:
            if not parts[1].isdigit():
                await message.reply("TTL must be a whole number of hours.")
                return
            ttl_hours = max(1, min(24 * 30, int(parts[1])))

        owner = message.from_user.id
        try:
            source = await replied.download()
            stored = ctx.storage.save_path(owner, source, name=media.file_name or "file.bin")
        except Exception as exc:  # noqa: BLE001 - quota and IO errors reach the user
            logger.exception("genlink failed")
            await message.reply(f"Could not store that file: {type(exc).__name__}: {exc}")
            return

        record = ctx.links.create(stored.id, owner, ttl_hours=ttl_hours)
        hours = (record.expires_at - record.created_at) / 3600
        await message.reply(
            f"<b>Link created</b>\n"
            f"file: <code>{stored.name}</code> ({stored.size} bytes)\n"
            f"expires in: {hours:.0f}h\n\n"
            f"<code>{record.token}</code>"
        )

    async def links(_client, message):
        owner = message.from_user.id
        records = ctx.links.owned(owner)
        if not records:
            await message.reply("You have no links yet. Reply to a file with /genlink.")
            return

        lines = []
        for record in records[:15]:
            state = "revoked" if record.revoked else ("expired" if record.expired else "active")
            file = ctx.storage.get(record.file_id)
            name = file.name if file else record.file_id
            lines.append(f"{state} · {name} · uses {record.uses} · <code>{record.token[:24]}…</code>")
        await message.reply("<b>Your links</b>\n" + "\n".join(lines))

    async def revoke(_client, message):
        parts = (getattr(message, "text", "") or "").split(maxsplit=1)
        if len(parts) < 2:
            await message.reply("Usage: /revoke &lt;token&gt;")
            return
        owner = message.from_user.id
        try:
            record = ctx.links.resolve(parts[1].strip())
        except LinkError as exc:
            # A revoked token must still be revocable-by-owner idempotently;
            # anything else is a genuine failure.
            if str(exc) == "link revoked":
                await message.reply("That link is already revoked.")
            else:
                await message.reply(f"Invalid link: {exc}")
            return

        if ctx.links.revoke(record.token, owner_id=owner):
            await message.reply("Link revoked.")
        else:
            await message.reply("That link does not belong to you.")

    return MANIFEST, {"genlink": genlink, "links": links, "revoke": revoke}
