"""Private Owner-facing command adapters for the capability authority."""

import html

from ...platform.sudo_access import SudoError
from ...ui.tables import Table, panel
from ...utils.rich import reply


def build(service, owner_gate):
    async def sudo(_client, message):
        if not await owner_gate(message):
            return
        if message.chat.id != message.from_user.id:
            await reply(message, "Manage sudo permissions privately with this bot.")
            return
        parts = (getattr(message, "text", "") or "").split()
        command = parts[0].split("@")[0].lstrip("/")
        args = parts[1:]
        # Preserve the existing command without recreating unrestricted sudo.
        if command == "sudo":
            action = args.pop(0) if args else "list"
            command = {"add": "addsudo", "remove": "delsudo", "list": "sudolist"}.get(
                action, ""
            )
            if command == "addsudo" and len(args) == 1:
                args += [
                    "diagnostics.read",
                    "global",
                    "24",
                    "Legacy sudo command: diagnostic access only",
                ]
            elif command == "delsudo" and len(args) == 1:
                args += ["diagnostics.read", "global", "Legacy sudo removal"]
        try:
            actor = message.from_user.id
            if command in ("sudolist", "sudoperms"):
                user_id = None
                history = bool(args and args[0] == "history" and command == "sudolist")
                if history:
                    args.pop(0)
                if command == "sudoperms" and args:
                    user_id = int(args.pop(0))
                page = int(args[0]) - 1 if args else 0
                rows = (
                    await service.history(actor, page=page)
                    if history
                    else await service.listing(actor, page=page, user_id=user_id)
                )
                data = []
                for row in rows:
                    scope = str(row["group_id"]) if row["group_id"] else "global"
                    expiry = str(row.get("expires_at") or "—")
                    data.append(
                        (
                            str(row["user_id"]),
                            row["capability"],
                            scope,
                            row["action"] if history else expiry,
                        )
                    )
                await reply(
                    message,
                    panel(
                        "Sudo history" if history else "Sudo permissions",
                        table=Table(
                            headers=(
                                "User",
                                "Capability",
                                "Scope",
                                "Action" if history else "Expires (UTC)",
                            ),
                            rows=tuple(data),
                        ),
                        lines=[] if data else ["No records on this page."],
                        footer=f"Page {page + 1} · 50 per page. Sudo never grants Premium or Telegram administrator rights.",
                    ),
                )
                return
            if command == "addsudo" and len(args) >= 5:
                user_id, capability = int(args[0]), args[1]
                scope = 0 if args[2] == "global" else int(args[2])
                await service.grant(
                    actor,
                    user_id,
                    capability,
                    group_id=scope,
                    hours=int(args[3]),
                    reason=" ".join(args[4:]),
                )
                await reply(
                    message,
                    "Scoped sudo grant committed. It does not grant Premium, Owner access or Telegram administrator rights.",
                )
                return
            if command == "delsudo" and len(args) >= 4:
                scope = 0 if args[2] == "global" else int(args[2])
                changed = await service.revoke(
                    actor,
                    int(args[0]),
                    args[1],
                    group_id=scope,
                    reason=" ".join(args[3:]),
                )
                await reply(
                    message,
                    "Sudo grant revoked."
                    if changed
                    else "No matching grant. Revocation attempt recorded.",
                )
                return
            raise ValueError(
                "Use /addsudo <id> diagnostics.read <global|group_id> <hours> <reason>; /delsudo <id> diagnostics.read <global|group_id> <reason>; /sudolist [page]; /sudolist history [page]; /sudoperms <id> [page]."
            )
        except (ValueError, SudoError) as exc:
            await reply(message, html.escape(str(exc)))

    return {
        name: sudo for name in ("sudo", "addsudo", "delsudo", "sudolist", "sudoperms")
    }
