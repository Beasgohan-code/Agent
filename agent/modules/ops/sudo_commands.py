"""Private Owner-facing command adapters for the capability authority."""

import html

from ...platform.sudo_access import (
    SudoError,
    CAPABILITY_DESCRIPTIONS,
    OWNER_ONLY_CAPABILITIES,
)
from ...ui.tables import Table, panel
from ...utils.rich import reply

PAGE_SIZE = 4


def build(service, owner_gate):
    async def sudo(_client, message):
        if not await owner_gate(message):
            return
        if message.chat.id != message.from_user.id:
            await reply(message, "Manage sudo permissions privately with this bot.")
            return
        parts = (getattr(message, "text", "") or "").split()
        command = parts[0].split("@")[0].lstrip("/!.#$%&?").lower()
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
            if command == "sudoperms" and not args:
                await reply(
                    message,
                    panel(
                        "Sudo capability catalog",
                        table=Table(
                            headers=("Capability", "Access"),
                            rows=tuple(CAPABILITY_DESCRIPTIONS.items()),
                        ),
                        lines=[
                            "<b>Owner-only · never delegated</b>",
                            ", ".join(sorted(OWNER_ONLY_CAPABILITIES)),
                        ],
                        note="Grants are additive, scoped and expiring. Sudo never substitutes for Premium or Telegram group-admin rights.",
                        footer="Use /sudoperms &lt;user id&gt; [page] to inspect grants.",
                    ),
                )
                return
            if command in ("sudolist", "sudoperms"):
                user_id = None
                history = bool(args and args[0] == "history" and command == "sudolist")
                if history:
                    args.pop(0)
                if command == "sudoperms":
                    user_id = int(args.pop(0))
                if len(args) > 1:
                    raise ValueError("Supply at most one page number.")
                page = int(args[0]) - 1 if args else 0
                rows = (
                    await service.history(actor, page=page, page_size=PAGE_SIZE)
                    if history
                    else await service.listing(
                        actor, page=page, user_id=user_id, page_size=PAGE_SIZE
                    )
                )
                data, details = [], []
                for row in rows:
                    scope = str(row["group_id"]) if row["group_id"] else "global"
                    expiry = str(row.get("expires_at") or "—")
                    data.append(
                        (
                            str(row["user_id"]),
                            row["capability"],
                            scope,
                            row["action"]
                            if history
                            else "Active"
                            if row.get("active")
                            else "Expired",
                        )
                    )
                    granting_actor = (
                        row.get("actor_id") if history else row.get("granted_by")
                    )
                    when = str(
                        row.get("created_at" if history else "granted_at")
                        or "not recorded"
                    )
                    details.append(
                        f"<b>{row['user_id']}</b> · <code>{html.escape(row['capability'])}</code> · {scope}\n"
                        + f"by <code>{granting_actor}</code> · {html.escape(when)}\n"
                        + "Expires: "
                        + html.escape(expiry)
                        + "\n"
                        + html.escape(str(row.get("reason") or "No reason recorded."))
                    )
                next_command = (
                    f"/sudolist history {page + 2}"
                    if history
                    else f"/sudoperms {user_id} {page + 2}"
                    if user_id
                    else f"/sudolist {page + 2}"
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
                                "Action" if history else "State",
                            ),
                            rows=tuple(data),
                        ),
                        lines=details if data else ["No records on this page."],
                        footer=f"Page {page + 1} · {PAGE_SIZE} per page. Next: {next_command}. Removing one grant does not remove other applicable grants.",
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
                    "Matching sudo grant revoked. Other scoped or global grants may still apply."
                    if changed
                    else "No matching grant. Revocation attempt recorded.",
                )
                return
            raise ValueError(
                "Use /addsudo <id> <capability> <global|group_id> <hours> <reason>; /delsudo <id> <capability> <global|group_id> <reason>; /sudolist [page]; /sudolist history [page]; /sudoperms <id> [page]."
            )
        except (ValueError, SudoError) as exc:
            await reply(message, html.escape(str(exc)))

    return {
        name: sudo for name in ("sudo", "addsudo", "delsudo", "sudolist", "sudoperms")
    }
