"""Private, premium-gated clones with guided setup and lifecycle controls.

Reviewed single-feature templates support guided setup. Bot token identity is verified; the setup
user becomes that clone tenant's Owner. Legacy profiles remain supported. No
clone inherits parent assistant credentials or permits recursive cloning.
"""

from __future__ import annotations

import logging
import time

from pyrogram.enums import ButtonStyle
from pyrogram.types import InlineKeyboardButton as Button
from pyrogram.types import InlineKeyboardMarkup as Keyboard

from ...platform.manifest import PluginManifest
from ...platform.secrets import SecretError, box_from
from . import lifecycle, profiles
from .catalog import selection_label
from ...ui.keyboards import nav_keyboard
from ...ui.tables import Table, kv_table, panel
from ...utils import rich as rich_ui
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
    scope="private",
)

#: Callback prefix for the clone buttons.
PREFIX = "clone"


def _state_summary(manager) -> str:
    """``2 running, 1 failed`` — only the states that exist, never a zero list."""
    counts = manager.counts()
    if not counts:
        return "nothing started yet"
    order = (
        lifecycle.State.RUNNING,
        lifecycle.State.DEGRADED,
        lifecycle.State.STARTING,
        lifecycle.State.FAILED,
        lifecycle.State.STOPPED,
    )
    parts = [
        f"{counts[state]} {state.value}"
        for state in order
        if counts.get(state)
    ]
    return ", ".join(parts) or "nothing started yet"


def build(ctx):
    """Wire the clone commands and their buttons to the shared context."""
    try:
        box = box_from(ctx.settings)
    except SecretError as exc:
        # A key that cannot be used is a deployment error, and the clone module
        # says so instead of quietly writing tokens in plaintext.
        logger.error("Clone tokens will not be stored: %s", exc)
        box = None
    store = CloneStore(ctx.settings.data_dir, db=getattr(ctx, "db", None), box=box)
    # A deployment (or a test) may hand in its own bot factory; the default
    # builds a real AgentBot for the clone's token.
    manager = CloneManager(ctx.settings, store, getattr(ctx, "clone_factory", None))
    events = getattr(ctx, "events", None)
    ctx.clones = manager
    from ...platform.roles import SudoStore
    from .setup import CloneSetup
    if getattr(ctx, "sudo", None) is None:
        ctx.sudo = SudoStore(ctx.settings.data_dir, owner_id=ctx.settings.owner_id, db=getattr(ctx, "db", None))

    def quota(user_id):
        return allowance(ctx.premium, user_id)[0]

    async def entitled(user_id):
        premium = ctx.premium
        if premium is None or user_id is None:
            return False
        if hasattr(premium, "ais_premium"):
            return await premium.ais_premium(user_id)
        return quota(user_id) > 0

    manager.eligible = entitled
    setup = CloneSetup(ctx, store, manager, entitled, quota)
    ctx.clone_setup = setup
    if ctx.actions is not None and not ctx.actions.handles("csetup:x"):
        ctx.actions.register("csetup", setup.press)

    def _when(seconds: float) -> str:
        return time.strftime("%Y-%m-%d", time.gmtime(seconds or 0))

    def _panel(owner_id: int) -> tuple[object, Keyboard]:
        """The control panel: one row of buttons per clone."""
        mine = store.by_owner(owner_id)
        if not mine:
            body = panel(
                "Your clones",
                icon=ctx.theme.emoji("bot"),
                lines=[
                    "You have not cloned this bot yet.",
                    "Open this bot privately and send <code>/clone</code> for guided setup.",
                    "The studio checks encryption before requesting any credentials.",
                ],
                note=pitch(),
            )
            return body, nav_keyboard()
        rows = tuple(
            (
                clone.handle,
                selection_label(clone.selected_plugins) if clone.selected_plugins else profiles.label(clone.profile),
                manager.state(clone.bot_id).label,
            )
            for clone in mine
        )
        running = sum(1 for clone in mine if manager.is_running(clone.bot_id))
        body = panel(
            "Your clones",
            icon=ctx.theme.emoji("bot"),
            subtitle=(
                f"<b>{len(mine)}</b> clone(s), <b>{running}</b> running. "
                "A clone runs the plugins its profile names, not always the whole bot."
            ),
            table=Table(headers=("Bot", "Profile", "State"), rows=rows),
            lines=tuple(
                f"<b>{clone.handle}</b> — {state.last_error[:160]}"
                for clone in mine
                if (state := manager.state(clone.bot_id)).state is lifecycle.State.FAILED
            ),
            note=pitch(),
            footer=(
                "<b>Profile</b> chooses how much of this bot a clone runs; stopping "
                "detaches it from Telegram and keeps the record."
            ),
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
                        "\U0001f9ed Profile",
                        callback_data=f"{PREFIX}:{clone.bot_id}:profile",
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
        return body, Keyboard(buttons)

    def _profile_panel(clone: Clone) -> tuple[object, Keyboard]:
        """What a clone may run, and the two clicks that change it."""
        current = None if clone.selected_plugins else profiles.clean(clone.profile)
        active_label = selection_label(clone.selected_plugins) if clone.selected_plugins else profiles.label(current)
        active_size = "guided selection + group core" if clone.selected_plugins else profiles.summary(current, ctx.settings)
        rows = tuple(
            (
                name,
                "on" if name == current else "",
                profiles.summary(name, ctx.settings),
                profiles.describe(name),
            )
            for name in profiles.ORDER
        )
        body = panel(
            f"Profile · {clone.handle}",
            icon=ctx.theme.emoji("gear"),
            subtitle=(
                f"Configured <b>{active_label}</b> "
                f"({active_size}), "
                + ("started." if manager.is_running(clone.bot_id) else "stopped.")
            ),
            table=Table(
                headers=("Profile", "On", "Size", "What it runs"),
                rows=rows,
                aligns=("left", "left", "left", "left"),
                max_column=28,
                total_width=56,
            ),
            note=(
                "A restricted profile never gets <code>ops</code> or "
                "<code>clone</code>: no deployment controls, and no clone of a clone."
            ),
            footer="Choosing a profile replaces any guided selection and restarts a running clone.",
        )
        buttons: list[list[Button]] = []
        for name in profiles.ORDER:
            mark = "\u2705" if name == current else "\u25cb"
            buttons.append(
                [
                    Button(
                        f"{mark} {name}",
                        callback_data=f"{PREFIX}:{clone.bot_id}:p:{name}",
                        style=ButtonStyle.SUCCESS
                        if name == current
                        else ButtonStyle.DEFAULT,
                    )
                ]
            )
        buttons.append(
            [Button("\u21a9\ufe0f Clones", callback_data=f"{PREFIX}:{clone.bot_id}:back")]
        )
        return body, Keyboard(buttons)

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
        if getattr(getattr(message, "chat", None), "id", None) != user.id:
            await reply(message, "Use /clone privately. Never send bot tokens or session strings in groups; revoke any token you already posted publicly.")
            return
        if not await entitled(user.id):
            await reply(message, "Cloning requires bot premium, including for Owner and sudo users.")
            return
        parts = (getattr(message, "text", "") or "").split()
        if len(parts) < 2:
            await setup.begin(message)
            return
        if not store.encrypted():
            await reply(message, "Configure TOKEN_KEY before adding clone credentials.")
            return
        profile = profiles.STANDARD
        if len(parts) > 2:
            if profiles.clean(parts[2]) != parts[2].strip().lower():
                await reply(
                    message,
                    "Unknown profile. Pick one of: "
                    + ", ".join(f"<code>{name}</code>" for name in profiles.ORDER)
                    + ".",
                )
                return
            profile = profiles.clean(parts[2])
        try:
            await message.delete()
        except Exception:
            pass
        ok, reason, bot_id = parse_token(parts[1])
        if not ok:
            await reply(message, f"<b>Cannot use that token</b>\n{reason}")
            return
        if bot_id == ctx.settings.bot_id:
            await reply(message, "The main bot cannot clone itself.")
            return
        await store.aall()
        existing = store.get(bot_id)
        if existing is not None:
            await reply(
                message,
                f"That bot is already cloned here ({existing.handle}). "
                "<code>/mybots</code> shows its state.",
            )
            return
        allowed, tier = quota(user.id), "premium"
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

        try:
            record = await store.aadd(
                Clone(
                    bot_id=bot_id,
                    owner_id=user.id,
                    managed_owner=True,
                    token=parts[1].strip(),
                    profile=profile,
                ),
                owner_limit=allowed,
                total_limit=ctx.settings.clone_limit,
            )
        except RuntimeError:
            await reply(message, "Clone capacity or persistence was not confirmed. Check /mybots before retrying.")
            return
        try:
            username = await manager.start(record)
        except CloneError:
            await store.aremove(bot_id)
            await reply(message, "<b>Could not start that clone</b>\nTelegram or deployment startup failed. Check bot credentials and try again.")
            return
        await store.aupdate(bot_id, username=username)
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
                        ("Profile", profiles.label(profile)),
                        ("Runs", profiles.summary(profile, ctx.settings)),
                        ("Data", f"<code>data/clones/{bot_id}</code>"),
                    ]
                ),
                note=(
                    "It has its own vault, its own premium ledger and its own "
                    "database rows, and it does <b>not</b> inherit "
                    "<code>OWNER_ID</code>."
                ),
                footer="<code>/mybots</code> controls it; <code>/delclone</code> removes it.",
            ),
            reply_markup=nav_keyboard(),
        )

    # -- /mybots -----------------------------------------------------------
    async def mybots(_client, message):
        await store.aall()
        user = getattr(message, "from_user", None)
        if user is None:
            return
        text, keyboard = _panel(user.id)
        await reply(message, text, reply_markup=keyboard)

    # -- /delclone ---------------------------------------------------------
    async def delclone(_client, message):
        await store.aall()
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
        await store.aremove(target.bot_id)
        if events is not None:
            events.emit("clone:delete", bot_id=target.bot_id, by=user.id)
        await reply(message, f"Deleted the clone <b>{target.handle}</b> and stopped it.")

    # -- /clonestats -------------------------------------------------------
    async def clonestats(_client, message):
        await store.aall()
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
                footer=(
                    "Running clones hold a polling loop each; the limit is a real "
                    "ceiling. States: " + _state_summary(manager) + "."
                ),
            ),
            reply_markup=nav_keyboard(),
        )

    # -- the panel buttons -------------------------------------------------
    async def _profile_press(client, query, target: Clone, action: str, extra: str, presser) -> None:
        """Pick a profile; a running clone is restarted so it takes effect."""
        if action == "back":
            text, keyboard = _panel(target.owner_id)
            await _redraw(query, client, text, keyboard)
            await query.answer("Back to your clones.")
            return
        if action != "p" or not extra:
            text, keyboard = _profile_panel(target)
            await _redraw(query, client, text, keyboard)
            await query.answer("Choose a profile.")
            return
        if profiles.clean(extra) != extra or extra not in profiles.ORDER:
            await query.answer("That profile does not exist.", show_alert=True)
            return
        await store.aupdate(target.bot_id, profile=extra, selected_plugins=(), ai_api_key=None, ai_model=None, assistant_session=None)
        said = f"{target.handle} is on {extra}."
        if manager.is_running(target.bot_id):
            try:
                username = await manager.restart(store.get(target.bot_id) or target)
            except CloneError as exc:
                await query.answer(str(exc), show_alert=True)
                return
            await store.aupdate(target.bot_id, username=username or target.username)
            said = f"{target.handle} restarted on {extra}."
        if events is not None:
            events.emit("clone:profile", bot_id=target.bot_id, by=presser)
        logger.info(
            "clone %s profile set to %s by %s (plugins: %s)",
            target.bot_id, extra, presser,
            ",".join(profiles.plugins_for(extra, ctx.settings)) or "shell only",
        )
        text, keyboard = _profile_panel(store.get(target.bot_id) or target)
        await _redraw(query, client, text, keyboard)
        await query.answer(said)

    async def _redraw(query, client, text, keyboard) -> None:
        """Draw a panel in place; a message that is gone is not a failed click."""
        try:
            await rich_ui.edit(query, text, reply_markup=keyboard)
        except Exception:  # noqa: BLE001 - a stale panel is not a failed control
            chat_id = getattr(getattr(query.message, "chat", None), "id", None)
            if chat_id is not None:
                await rich_ui.send(client, chat_id, text, reply_markup=keyboard)

    async def on_clone_press(client, query, rest: str):
        await store.aall()
        """``<bot_id>:<start|stop|delete|profile|p|back>[:<profile>]``."""
        parts = (rest or "").split(":")
        if len(parts) < 2 or not parts[0].isdigit():
            await query.answer("That button is stale.", show_alert=True)
            return
        bot_id, action = int(parts[0]), parts[1].strip().lower()
        extra = parts[2].strip().lower() if len(parts) > 2 else ""
        target = store.get(bot_id)
        presser = getattr(getattr(query, "from_user", None), "id", None)
        if target is None:
            await query.answer("That clone is gone.", show_alert=True)
            return
        if not _may_manage(presser, target):
            await query.answer("Only its owner can control this clone.", show_alert=True)
            return
        if action in ("start", "profile", "p") and not await entitled(presser):
            await query.answer("Starting or reconfiguring clones requires bot premium, including for Owner and sudo users.", show_alert=True)
            return
        if action in ("profile", "p", "back"):
            await _profile_press(client, query, target, action, extra, presser)
            return
        if action == "start":
            try:
                username = await manager.start(target)
            except CloneError as exc:
                await query.answer(str(exc), show_alert=True)
                return
            await store.aupdate(bot_id, username=username or target.username, disabled=False)
            said = f"{target.handle} is running."
        elif action == "stop":
            if not await manager.stop(bot_id):
                await query.answer("It was already stopped.", show_alert=True)
                return
            await store.aupdate(bot_id, disabled=True)
            said = f"{target.handle} is stopped."
        elif action == "delete":
            await manager.stop(bot_id)
            await store.aremove(bot_id)
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
        await _redraw(query, client, text, keyboard)
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


def extra_handlers(ctx):
    """Only private setup messages reach the guided clone workflow."""
    from pyrogram import filters
    from pyrogram.handlers import MessageHandler
    return [MessageHandler(ctx.clone_setup.receive, filters.private & filters.text)]
