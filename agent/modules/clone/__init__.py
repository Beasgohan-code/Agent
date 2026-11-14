"""Clone — this bot answering on other bot tokens, managed by button.

``/clone <token>`` adds a clone and starts it immediately: a second
:class:`agent.bot.AgentBot` on its own token, session and data directory, so it
answers exactly like this one instead of a cut-down copy. ``/mybots`` is the
control panel — every clone with a start, stop and delete button — and
``/delclone`` is the same thing for scripts.

Three facts are stated rather than hidden:

* a clone has its **own vault and its own premium ledger**, because it has its
  own data directory; sharing one would let one bot's members read another's
  files;
* ``OWNER_ID`` is **not** inherited, so the person who added a clone cannot use
  it to reach owner commands;
* the deployment caps the total with ``CLONE_LIMIT``, and the member's own
  allowance comes from :mod:`agent.modules.clone.limits`.
"""

from __future__ import annotations

import logging
import time

from pyrogram.enums import ButtonStyle
from pyrogram.types import InlineKeyboardButton as Button
from pyrogram.types import InlineKeyboardMarkup as Keyboard

from ...platform.manifest import PluginManifest
from ...ui.keyboards import nav_keyboard
from ...ui.tables import Table, kv_table, panel
from ...utils.rich import reply
from .limits import PREMIUM, allowance, pitch
from .manager import CloneError, CloneManager
from .store import Clone, CloneStore, parse_token

logger = logging.getLogger(__name__)

MANIFEST = PluginManifest(
    slug="clone",
    name="Clone",
    version="1.0.0",
    description="Run this bot on other bot tokens, and control them by button.",
    commands=("clone", "mybots", "delclone", "clonestats"),
    permissions=("messages.read", "messages.send", "process.spawn"),
    scope="all",
)

#: Callback prefix for the clone buttons.
PREFIX = "clone"


def build(ctx):
    """Wire the clone commands and their buttons to the shared context."""
    store = CloneStore(ctx.settings.data_dir, db=getattr(ctx, "db", None))
    # A deployment (or a test) may hand in its own bot factory; the default
    # builds a real AgentBot for the clone's token.
    manager = CloneManager(ctx.settings, store, getattr(ctx, "clone_factory", None))
    events = getattr(ctx, "events", None)
    ctx.clones = manager

    def _when(seconds: float) -> str:
        return time.strftime("%Y-%m-%d", time.gmtime(seconds or 0))

    def _panel(owner_id: int) -> tuple[str, Keyboard]:
        """The control panel: one row of buttons per clone."""
        mine = store.by_owner(owner_id)
        if not mine:
            body = panel(
                "Your clones",
                icon=ctx.theme.emoji("bot"),
                lines=[
                    "You have not cloned this bot yet.",
                    "Send <code>/clone &lt;bot token&gt;</code> with a token from @BotFather.",
                ],
                note=pitch(),
            )
            return str(body.classic), nav_keyboard()
        rows = tuple(
            (
                clone.handle,
                "running" if manager.is_running(clone.bot_id) else "stopped",
                _when(clone.created_at),
            )
            for clone in mine
        )
        running = sum(1 for clone in mine if manager.is_running(clone.bot_id))
        body = panel(
            "Your clones",
            icon=ctx.theme.emoji("bot"),
            subtitle=(
                f"<b>{len(mine)}</b> clone(s), <b>{running}</b> running. "
                "A clone is a full copy of this bot on its own token."
            ),
            table=Table(headers=("Bot", "State", "Since"), rows=rows),
            note=pitch(),
            footer="Stopping a clone detaches it from Telegram; the record stays here.",
        )
        buttons: list[list[Button]] = []
        for clone in mine:
            live = manager.is_running(clone.bot_id)
            buttons.append(
                [
                    Button(
                        "\u23f8 Stop" if live else "\u25b6\ufe0f Start",
                        callback_data=f"{PREFIX}:{clone.bot_id}:{'stop' if live else 'start'}",
                        style=ButtonStyle.PRIMARY if not live else ButtonStyle.DEFAULT,
                    ),
                    Button(
                        "\U0001f5d1 Delete",
                        callback_data=f"{PREFIX}:{clone.bot_id}:delete",
                        style=ButtonStyle.DANGER,
                    ),
                ]
            )
        buttons.append(
            [
                Button("\u21a9\ufe0f Menu", callback_data="menu:home", style=ButtonStyle.PRIMARY),
                Button("\U0001f4a1 Help", callback_data="menu:help"),
            ]
        )
        return str(body.classic), Keyboard(buttons)

    def _may_manage(user_id: int | None, clone: Clone) -> bool:
        if user_id is None:
            return False
        owner = ctx.settings.owner_id
        return clone.owner_id == int(user_id) or (owner is not None and int(user_id) == int(owner))

    def _find(argument: str) -> Clone | None:
        """A clone by id, ``@username`` or token — whatever the owner pasted."""
        text = (argument or "").strip().lstrip("@")
        if not text:
            return None
        if text.isdigit():
            return store.get(int(text))
        for clone in store.all():
            if clone.username.lower() == text.lower():
                return clone
        ok, _reason, bot_id = parse_token(text)
        return store.get(bot_id) if ok else None

    # -- /clone ------------------------------------------------------------
    async def clone(_client, message):
        user = getattr(message, "from_user", None)
        if user is None:
            return
        parts = (getattr(message, "text", "") or "").split(maxsplit=1)
        if len(parts) < 2:
            await reply(
                message,
                "Send <code>/clone &lt;bot token&gt;</code>. Get the token from "
                "@BotFather; the clone starts as soon as it is accepted.",
            )
            return
        ok, reason, bot_id = parse_token(parts[1])
        if not ok:
            await reply(message, f"<b>Cannot use that token</b>\n{reason}")
            return
        existing = store.get(bot_id)
        if existing is not None:
            await reply(
                message,
                f"That bot is already cloned here ({existing.handle}). "
                "<code>/mybots</code> shows its state.",
            )
            return
        allowed, tier = allowance(ctx.premium, user.id)
        mine = store.by_owner(user.id)
        if len(mine) >= allowed:
            await reply(
                message,
                panel(
                    "Clone limit reached",
                    icon=ctx.theme.emoji("ban"),
                    subtitle=f"You run <b>{len(mine)}</b> clone(s) on <b>{tier}</b>.",
                    lines=[pitch()],
                    footer=f"Premium runs {PREMIUM} clones; <code>/delclone</code> frees a slot.",
                ),
            )
            return
        if store.count() >= ctx.settings.clone_limit:
            await reply(
                message,
                f"<b>This deployment is full</b>\nIt is running <b>{store.count()}</b> "
                f"clones, its limit is <b>{ctx.settings.clone_limit}</b>.",
            )
            return

        record = store.add(Clone(bot_id=bot_id, owner_id=user.id, token=parts[1].strip()))
        try:
            username = await manager.start(record)
        except CloneError as exc:
            store.remove(bot_id)
            await reply(message, f"<b>Could not start that clone</b>\n{exc}")
            return
        store.update(bot_id, username=username)
        if events is not None:
            events.emit("clone:add", bot_id=bot_id, by=user.id)
        logger.info("clone %s added by %s as @%s", bot_id, user.id, username or "?")
        await reply(
            message,
            panel(
                "Clone started",
                icon=ctx.theme.emoji("check"),
                subtitle=f"<b>{bot_id}</b> is answering as {('@' + username) if username else 'itself'}.",
                table=kv_table(
                    [
                        ("Owner", f"<code>{user.id}</code>"),
                        ("Token", f"<code>{record.masked}</code>"),
                        ("Data", f"<code>data/clones/{bot_id}</code>"),
                    ]
                ),
                note=(
                    "It has its own vault and its own premium ledger, and it does "
                    "<b>not</b> inherit <code>OWNER_ID</code>."
                ),
                footer="<code>/mybots</code> controls it; <code>/delclone</code> removes it.",
            ),
            reply_markup=nav_keyboard(),
        )

    # -- /mybots -----------------------------------------------------------
    async def mybots(_client, message):
        user = getattr(message, "from_user", None)
        if user is None:
            return
        text, keyboard = _panel(user.id)
        await reply(message, text, reply_markup=keyboard)

    # -- /delclone ---------------------------------------------------------
    async def delclone(_client, message):
        user = getattr(message, "from_user", None)
        if user is None:
            return
        parts = (getattr(message, "text", "") or "").split(maxsplit=1)
        if len(parts) < 2:
            await reply(message, "Send <code>/delclone &lt;bot id | @username&gt;</code>.")
            return
        target = _find(parts[1])
        if target is None:
            await reply(message, "No clone here matches that.")
            return
        if not _may_manage(user.id, target):
            await reply(message, "That clone belongs to somebody else.")
            return
        await manager.stop(target.bot_id)
        store.remove(target.bot_id)
        if events is not None:
            events.emit("clone:delete", bot_id=target.bot_id, by=user.id)
        await reply(message, f"Deleted the clone <b>{target.handle}</b> and stopped it.")

    # -- /clonestats -------------------------------------------------------
    async def clonestats(_client, message):
        owner = ctx.settings.owner_id
        user = getattr(message, "from_user", None)
        if owner is None or user is None or int(user.id) != int(owner):
            await reply(message, "This command is reserved for the bot owner.")
            return
        all_clones = store.all()
        per_owner: dict[int, int] = {}
        for clone in all_clones:
            per_owner[clone.owner_id] = per_owner.get(clone.owner_id, 0) + 1
        rows = tuple(
            (f"<code>{oid}</code>", str(count)) for oid, count in sorted(per_owner.items())
        ) or (("nobody", "0"),)
        await reply(
            message,
            panel(
                "Clone statistics",
                icon=ctx.theme.emoji("stats"),
                subtitle=(
                    f"<b>{len(all_clones)}</b> clone(s), "
                    f"<b>{len(manager.running())}</b> running, "
                    f"limit <b>{ctx.settings.clone_limit}</b>."
                ),
                table=Table(headers=("Owner", "Clones"), rows=rows, aligns=("left", "right")),
                footer="Running clones hold a polling loop each; the limit is a real ceiling.",
            ),
            reply_markup=nav_keyboard(),
        )

    # -- the panel buttons -------------------------------------------------
    async def on_clone_press(client, query, rest: str):
        """``<bot_id>:<start|stop|delete>`` from the /mybots panel."""
        parts = (rest or "").split(":")
        if len(parts) != 2 or not parts[0].isdigit():
            await query.answer("That button is stale.", show_alert=True)
            return
        bot_id, action = int(parts[0]), parts[1].strip().lower()
        target = store.get(bot_id)
        presser = getattr(getattr(query, "from_user", None), "id", None)
        if target is None:
            await query.answer("That clone is gone.", show_alert=True)
            return
        if not _may_manage(presser, target):
            await query.answer("Only its owner can control this clone.", show_alert=True)
            return
        if action == "start":
            try:
                username = await manager.start(target)
            except CloneError as exc:
                await query.answer(str(exc), show_alert=True)
                return
            store.update(bot_id, username=username or target.username, disabled=False)
            said = f"{target.handle} is running."
        elif action == "stop":
            if not await manager.stop(bot_id):
                await query.answer("It was already stopped.", show_alert=True)
                return
            store.update(bot_id, disabled=True)
            said = f"{target.handle} is stopped."
        elif action == "delete":
            await manager.stop(bot_id)
            store.remove(bot_id)
            said = f"{target.handle} was deleted."
            if events is not None:
                events.emit("clone:delete", bot_id=bot_id, by=presser)
        else:
            await query.answer("That button is stale.", show_alert=True)
            return
        if events is not None and action != "delete":
            events.emit(f"clone:{action}", bot_id=bot_id, by=presser)
        logger.info("clone %s %s by %s from the panel", bot_id, action, presser)
        text, keyboard = _panel(target.owner_id)
        try:
            await query.message.edit_text(text=text, reply_markup=keyboard)
        except Exception:  # noqa: BLE001 - a stale panel is not a failed control
            chat_id = getattr(getattr(query.message, "chat", None), "id", None)
            if chat_id is not None:
                await client.send_message(chat_id, text, reply_markup=keyboard)
        await query.answer(said)

    router = getattr(ctx, "actions", None)
    if router is not None and not router.handles(f"{PREFIX}:x"):
        router.register(PREFIX, on_clone_press)

    logger.info("Clone plugin wired (%d recorded, %d running)", store.count(), len(manager.running()))
    return MANIFEST, {
        "clone": clone,
        "mybots": mybots,
        "delclone": delclone,
        "clonestats": clonestats,
    }
