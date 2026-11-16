"""Federation metadata and chat enrollment; ban delivery is a separate phase."""

import html
from pyrogram.enums import ChatType, ChatMemberStatus
from .roles import COMMANDS as ROLE_COMMANDS, build as build_roles
from ...platform.federations import operate, fed_id, FederationError
from ...platform.manifest import PluginManifest
from ...ui.tables import panel, Table, kv_table
from ...utils.rich import reply

COMMANDS = (
    "newfed",
    "renamefed",
    "delfed",
    "myfeds",
    "fedinfo",
    "fedadmins",
    "joinfed",
    "leavefed",
    "chatfed",
    "fedreason",
    "fednotif",
    "quietfed",
    *ROLE_COMMANDS,
)
MANIFEST = PluginManifest(
    group_compatible=True,
    clone_compatible=True,
    slug="federations",
    name="Federations",
    version="1.0.0",
    description="Federation ownership, information and chat membership. Ban synchronization is not yet available.",
    commands=COMMANDS,
    scope="all",
)


def build(ctx):
    async def chat_owner(client, message):
        if getattr(message.chat, "type", None) not in (
            ChatType.GROUP,
            ChatType.SUPERGROUP,
        ):
            raise FederationError("Use this command inside the group.")
        try:
            member = await client.get_chat_member(message.chat.id, message.from_user.id)
        except Exception:
            raise FederationError("Chat ownership could not be verified.") from None
        if getattr(member, "status", None) != ChatMemberStatus.OWNER:
            raise FederationError(
                "Only the current Telegram chat owner can join or leave a federation."
            )

    def handler(command):
        async def call(client, message):
            user = getattr(message, "from_user", None)
            if (
                type(getattr(user, "id", None)) is not int
                or user.id <= 0
                or getattr(message, "sender_chat", None) is not None
            ):
                await reply(
                    message,
                    "Use your personal Telegram identity for federation commands.",
                )
                return
            args = (getattr(message, "text", "") or "").split()[1:]
            try:
                if command in ("fedreason", "fednotif", "quietfed"):
                    if len(args) > (1 if command == "quietfed" else 2):
                        raise FederationError(
                            f"Usage: /{command} [on|off]"
                            + (" [federation-ID]" if command != "quietfed" else "")
                        )
                    enabled = None
                    if args:
                        if args[0].lower() not in ("yes", "no", "on", "off"):
                            raise FederationError("Choose yes, no, on or off.")
                        enabled = args[0].lower() in ("yes", "on")
                    if command == "quietfed":
                        await chat_owner(client, message)
                        state = await operate(
                            ctx,
                            "chat" if enabled is None else "quiet",
                            user.id,
                            chat=message.chat.id,
                            enabled=enabled,
                            client=client,
                        )
                        # Read authoritative committed chat preferences, not a stale federation row.
                        if enabled is not None:
                            state = await operate(
                                ctx, "chat", user.id, chat=message.chat.id
                            )
                        key = "quiet"
                    else:
                        state = await operate(
                            ctx,
                            "info"
                            if enabled is None
                            else ("reason" if command == "fedreason" else "notify"),
                            user.id,
                            **({} if enabled is None else {"enabled": enabled}),
                            federation=args[1] if len(args) == 2 else None,
                        )
                        if state["owner_id"] != user.id:
                            raise FederationError(
                                "Only the federation owner can manage these preferences."
                            )
                        key = (
                            "require_reason"
                            if command == "fedreason"
                            else "notify_owner"
                        )
                    await reply(
                        message,
                        panel(
                            "Federation preference",
                            table=kv_table(
                                [
                                    ("Federation", state["name"]),
                                    ("ID", str(state["id"])),
                                    (command, "On" if state[key] else "Off"),
                                ]
                            ),
                            note="Stored preference only: federation ban enforcement and notification delivery are not available yet. No Telegram bans, unbans or notifications were attempted.",
                        ),
                    )
                    return
                if command in ("newfed", "renamefed"):
                    name = (message.text or "").split(maxsplit=1)
                    if len(name) != 2:
                        raise FederationError(f"Usage: /{command} federation name")
                    state = await operate(
                        ctx,
                        "new" if command == "newfed" else "rename",
                        user.id,
                        name=name[1],
                    )
                elif command == "myfeds":
                    if len(args) > 1 or (
                        args
                        and (
                            not args[0].isascii()
                            or not args[0].isdecimal()
                            or len(args[0]) > 3
                            or int(args[0]) < 1
                        )
                    ):
                        raise FederationError("Usage: /myfeds [page]")
                    rows = await operate(ctx, "mine", user.id)
                    page = int(args[0]) if args else 1
                    pages = max(1, (len(rows) + 9) // 10)
                    if page > pages:
                        raise FederationError(
                            f"Choose a federation page from 1 to {pages}."
                        )
                    await reply(
                        message,
                        panel(
                            "Your federations",
                            table=Table(
                                headers=("Name", "ID", "Role"),
                                rows=tuple(
                                    (
                                        row["name"],
                                        str(row["id"]),
                                        "Owner"
                                        if row["owner_id"] == user.id
                                        else "Admin",
                                    )
                                    for row in rows[(page - 1) * 10 : page * 10]
                                ),
                            ),
                            lines=[]
                            if rows
                            else ["You do not own or administer a federation."],
                            footer=f"Page {page}/{pages} · showing at most 101 federations",
                        ),
                    )
                    return
                elif command == "delfed":
                    if not args:
                        state = await operate(ctx, "info", user.id)
                        if state["owner_id"] != user.id:
                            raise FederationError(
                                "Only the federation owner can delete it."
                            )
                        await reply(
                            message,
                            f"Delete <b>{html.escape(state['name'])}</b> and its federation metadata? This cannot be undone. Telegram bans will not be lifted.\nConfirm: <code>/delfed confirm {state['id']}</code>",
                        )
                        return
                    if len(args) != 2 or args[0].lower() != "confirm":
                        raise FederationError(
                            "Use /delfed first, then its explicit confirmation command."
                        )
                    state = await operate(ctx, "delete", user.id, federation=args[1])
                    await reply(
                        message,
                        "Federation deleted. No Telegram unbans were attempted.",
                    )
                    return
                elif command in ("joinfed", "leavefed"):
                    if len(args) != (1 if command == "joinfed" else 0):
                        raise FederationError(
                            "Usage: /joinfed federation-ID or /leavefed"
                        )
                    await chat_owner(client, message)
                    state = await operate(
                        ctx,
                        "join" if command == "joinfed" else "leave",
                        user.id,
                        federation=args[0] if args else None,
                        chat=message.chat.id,
                        client=client,
                    )
                    await reply(
                        message,
                        "Chat joined the federation. Ban synchronization is not available yet."
                        if command == "joinfed"
                        else "Chat left the federation. No Telegram unbans were attempted.",
                    )
                    return
                elif command == "chatfed":
                    if args or getattr(message.chat, "type", None) not in (
                        ChatType.GROUP,
                        ChatType.SUPERGROUP,
                    ):
                        raise FederationError(
                            "Use /chatfed without arguments inside a group."
                        )
                    state = await operate(ctx, "chat", user.id, chat=message.chat.id)
                elif command in ("fedinfo", "fedadmins"):
                    if len(args) != 1:
                        raise FederationError(f"Usage: /{command} federation-ID")
                    identity = fed_id(args[0])
                    state = await operate(
                        ctx,
                        "info" if command == "fedinfo" else "admins",
                        user.id,
                        federation=identity,
                    )
                    if command == "fedadmins":
                        await reply(
                            message,
                            panel(
                                "Federation administrators",
                                table=Table(
                                    headers=("ID", "Role"),
                                    rows=((str(state["owner"]), "Owner"),)
                                    + tuple(
                                        (str(uid), "Admin")
                                        for uid in state["admins"][:100]
                                    ),
                                ),
                                note="At most 100 additional administrators shown. Federation roles do not grant Telegram group-admin rights.",
                            ),
                        )
                        return
                else:
                    return
                await reply(
                    message,
                    panel(
                        "Federation",
                        table=kv_table(
                            [
                                ("Name", state["name"]),
                                ("ID", str(state["id"])),
                                ("Owner", str(state["owner_id"])),
                                *(
                                    [("Chats", str(state["chats"]))]
                                    if "chats" in state
                                    else []
                                ),
                            ]
                        ),
                        note="Cross-chat ban delivery is not available yet. Federation admin invitations and ownership transfer require private confirmation.",
                    ),
                )
            except FederationError as error:
                await reply(message, html.escape(str(error)))
            except Exception:
                await reply(
                    message,
                    "Federation operation could not be confirmed. Refresh before retrying.",
                )

        return call

    return MANIFEST, {
        **{
            command: handler(command)
            for command in COMMANDS
            if command not in ROLE_COMMANDS
        },
        **build_roles(ctx),
    }
