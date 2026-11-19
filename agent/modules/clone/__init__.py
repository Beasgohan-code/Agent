"""Private, premium-gated clones with guided setup and lifecycle controls.

Reviewed single-feature and combined suites support guided setup. Bot token identity is verified; the setup
user becomes that clone tenant's Owner. Legacy profiles remain supported. No
clone inherits parent assistant credentials or permits recursive cloning.
"""

from __future__ import annotations

import html
import hashlib
import logging
import time

from pyrogram.errors import MessageNotModified
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
    group_compatible=False,
    clone_compatible=False,
    slug="clone",
    name="Clone",
    version="1.0.0",
    description="Run this bot on other bot tokens, and control them by button.",
    commands=("clone", "panel", "mybots", "delclone", "clonestats"),
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
    from .control_centre import CloneControlCentre
    control_centre = CloneControlCentre(ctx, manager)
    if ctx.actions is not None and not ctx.actions.handles('cc:x'):
        ctx.actions.register('cc', control_centre.press)
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
                "Clone controller",
                icon=ctx.theme.emoji("bot"),
                lines=[
                    "You have not cloned this bot yet.",
                    "Open this bot privately and send <code>/clone</code> for guided setup.",
                    "The studio checks encryption before requesting any credentials.",
                ],
                note=pitch(),
            )
            return body, Keyboard([
                [Button("↻ Refresh all", callback_data="clone:refresh")],
                [Button("Menu", callback_data="menu:home")],
            ])
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
            "Clone controller",
            icon=ctx.theme.emoji("bot"),
            subtitle=(
                f"<b>{len(mine)}</b> clone(s), <b>{running}</b> running. "
                "A clone runs the plugins its profile names, not always the whole bot."
            ),
            table=Table(headers=("Bot", "Profile", "State"), rows=rows),
            lines=tuple(
                f"<b>{html.escape(clone.handle)}</b> — worker failed; open its dashboard diagnostics. Raw errors are hidden."
                for clone in mine
                if manager.state(clone.bot_id).state is lifecycle.State.FAILED
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
                        f"⏸ {clone.handle} · Stop" if live else f"▶ {clone.handle} · Start",
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
            buttons.append([ctx.theme.button(f'{clone.handle} · Dashboard', icon='bot',
                            callback_data=f'cc:{clone.bot_id}:home', style=ButtonStyle.PRIMARY)])
            buttons.append([Button(f"ℹ {clone.handle} · Details", callback_data=f"{PREFIX}:{clone.bot_id}:details"),
                            Button("↻ Restart", callback_data=f"{PREFIX}:{clone.bot_id}:restart")])
        buttons.append([ctx.theme.button('Browse My Bots', icon='search', callback_data='cc:list:all:0')])
        buttons.append([Button("↻ Refresh all", callback_data="clone:refresh")])
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
            footer=("Changes save a pending desired revision; workers are not reconciled by this panel." if store._db is not None else "Choosing a profile replaces any guided selection and restarts a running clone."),
        )
        buttons: list[list[Button]] = []
        for name in profiles.ORDER:
            mark = "\u2705" if name == current else "\u25cb"
            buttons.append(
                [
                    Button(
                        f"{mark} {name}",
                        callback_data=f"{PREFIX}:{clone.bot_id}:p:{name}" + (f"~{clone.configuration_revision}" if store._db is not None else ""),
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
            await reply(message, panel('Premium required', icon=ctx.theme.emoji('bot'),
                lines=['Cloning requires bot premium, including for Owner and sudo users.',
                       f'Your Telegram user ID: <code>{user.id}</code>.',
                       f'The configured bot Owner can grant one test day: <code>/addpremium {user.id} 1</code>.',
                       'Then check /premium and retry /clone. Premium belongs to this bot; another bot’s subscription does not transfer.'],
                note='If /premium or /addpremium gives no reply, check that premium is included in deployment PLUGINS and enabled with /plugin premium on. Adding a missing module requires an authorized restart; the runtime switch cannot install it.'))
            return
        parts = (getattr(message, "text", "") or "").split()
        if len(parts) >= 2 and parts[1].lower() == 'managed':
            if len(parts) != 3 or not parts[2].isascii() or not parts[2].isdigit() or len(parts[2]) > 20:
                await reply(message, 'Use /clone managed BOT_ID from your recent private managed-bot notice. This imports a credential for review; it does not start a clone.')
                return
            await setup.import_managed(_client, message, int(parts[2]))
            return
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
        user = getattr(message, "from_user", None)
        if user is None:
            return
        if getattr(getattr(message, "chat", None), "id", None) != user.id:
            await reply(message, "Open /mybots privately to manage your bots and storage destinations.")
            return
        try:
            await store.aall()
            argument = (getattr(message, 'text', '') or '').split(maxsplit=1)
            if len(argument) == 2:
                try:
                    search = control_centre.search_text(argument[1])
                except ValueError:
                    await reply(message, 'Search by name, @username or bot ID using at most 24 UTF-8 bytes without control characters.')
                    return
                text, keyboard = await control_centre.render_directory(user.id, 'all', 0, search)
            else:
                text, keyboard = _panel(user.id)
        except Exception:
            logger.warning('#Errors Clone panel state could not be loaded')
            await reply(message, panel('Clone controller unavailable',
                lines=['Your saved clone state could not be read safely. No clone was created, started or deleted.',
                       'Bot Owner: check /errors and Database availability, then retry /mybots.'],
                note='Premium is required to create/start clones, not to view your saved bots. This error is separate from your subscription.'))
            return
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
        if store._db is not None:
            if type(user.id) is not int or target.owner_id != user.id or getattr(getattr(message, 'chat', None), 'id', None) != user.id:
                await reply(message, 'Open /mybots privately as the saved clone owner.')
                return
            if target.configuration_revision <= 0:
                await reply(message, 'Revision-tracked configuration is required. Open the dashboard to inspect this legacy record; no deletion was performed.')
                return
            text, keyboard = control_centre.confirmation(target, 'delete', target.configuration_revision, target.lifecycle_generation)
            await reply(message, text, reply_markup=keyboard)
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
        if action not in ("p", "pc") or not extra:
            text, keyboard = _profile_panel(target)
            await _redraw(query, client, text, keyboard)
            await query.answer("Choose a profile.")
            return
        expected_revision = None
        versioned_extra = extra
        if store._db is not None:
            extra, separator, version = extra.partition('~')
            if not separator or not version.isascii() or not version.isdecimal() or len(version) > 12:
                text, keyboard = _profile_panel(target)
                await _redraw(query, client, text, keyboard)
                await query.answer("Reopen the profile picker; this control has no current revision.", show_alert=True)
                return
            expected_revision = int(version)
        if profiles.clean(extra) != extra or extra not in profiles.ORDER:
            await query.answer("That profile does not exist.", show_alert=True)
            return
        if target.selected_plugins and action == "p":
            await _redraw(query, client, panel("Replace guided clone setup?", icon=ctx.theme.emoji("shield"),
                table=kv_table([("Current features", selection_label(target.selected_plugins)),
                                ("Replacement profile", profiles.label(extra))]),
                lines=["This replaces the guided feature selection and removes this clone’s stored Music assistant session and AI key/model.",
                       "Changes await worker reconciliation; no running worker is restarted here. Re-adding credential-bearing features requires guided setup."],
                note="The bot token, owned files and configured channels are not deleted."),
                Keyboard([[Button("Confirm replacement", callback_data=f"{PREFIX}:{target.bot_id}:pc:{versioned_extra}", style=ButtonStyle.DANGER)],
                          [Button("Keep current setup", callback_data=f"{PREFIX}:{target.bot_id}:profile")]]))
            await query.answer("Review before replacing the guided setup.")
            return
        if store._db is not None:
            from .configuration import ConfigurationWriteError
            from .revisions import RevisionConflict
            request_id = hashlib.sha256(str(getattr(query, 'id', '')).encode()).hexdigest()
            if not getattr(query, 'id', None):
                await query.answer("Request identity missing; reopen the profile picker.", show_alert=True)
                return
            try:
                result = await manager.configuration.write(target.bot_id, actor_id=presser,
                    expected_revision=expected_revision, request_id=request_id,
                    changes=dict(profile=extra, selected_plugins=(), ai_api_key=None, ai_model=None, assistant_session=None))
            except (ConfigurationWriteError, RevisionConflict):
                await query.answer("Configuration not confirmed or control stale. Refresh before retrying.", show_alert=True)
                return
            text, keyboard = _profile_panel(store.get(target.bot_id) or target)
            await _redraw(query, client, text, keyboard)
            await query.answer(f"Desired revision {result['desired_revision']} saved; awaiting reconciliation.")
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
        except MessageNotModified:
            return  # Repeated refresh must not send duplicate controller messages.
        except Exception:  # noqa: BLE001 - a stale panel is not a failed control
            chat_id = getattr(getattr(query.message, "chat", None), "id", None)
            if chat_id is not None:
                await rich_ui.send(client, chat_id, text, reply_markup=keyboard)

    async def on_clone_press(client, query, rest: str):
        await store.aall()
        """``<bot_id>:<start|stop|delete|profile|p|back>[:<profile>]``."""
        if rest == "refresh":
            user_id = getattr(getattr(query, "from_user", None), "id", None)
            if not user_id or getattr(getattr(query.message, "chat", None), "id", None) != user_id:
                await query.answer("Open /panel privately.", show_alert=True)
                return
            text, keyboard = _panel(user_id)
            await _redraw(query, client, text, keyboard)
            await query.answer("Controller refreshed.")
            return
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
        if store._db is not None and action in ('start', 'stop', 'restart', 'delete', 'delete_confirm'):
            if len(parts) != 2:
                await query.answer('That lifecycle button is stale. Refresh My Bots.', show_alert=True)
                return
            # Saved unversioned buttons may browse a fresh confirmation, never
            # synthesize a current assignment and execute it in the same press.
            requested = 'delete' if action == 'delete_confirm' else action
            await control_centre.press(client, query,
                f'{bot_id}:ask:{requested}:{target.configuration_revision}:{target.lifecycle_generation}')
            return
        if action == "details":
            if getattr(getattr(query.message, "chat", None), "id", None) != presser:
                await query.answer("Open /mybots privately to view storage details.", show_alert=True)
                return
            features = selection_label(target.selected_plugins) if target.selected_plugins else profiles.describe(target.profile)
            text = panel("Clone details", icon=ctx.theme.emoji("bot"),
                table=kv_table([
                    ("Bot ID", str(target.bot_id)),
                    ("Features", features),
                    ("Group Management", "Included · always available"),
                    ("Runtime", "Running in this process" if manager.is_running(bot_id) else "Not running in this process"),
                    ("Archive channel", str(target.storage_channel) if target.storage_channel else "Not configured"),
                    ("Log channel", str(target.log_channel) if target.log_channel else "Not configured"),
                    ("Credential encryption", "Enabled" if store.encrypted() else "Unavailable"),
                ]),
                note="A file-processing clone uses its own token, storage metadata and jobs. It never inherits the parent’s archive channel.",
                footer="An archive channel is required for durable remote copies. Without one, local files can be lost on restart or redeploy.")
            await _redraw(query, client, text, Keyboard([[Button("Back to clones", callback_data=f"{PREFIX}:{bot_id}:back")]]))
            await query.answer()
            return
        if action == "delete":
            await _redraw(query, client, panel("Delete this clone?", lines=[
                f"Stop and remove bot <code>{bot_id}</code> from this manager?",
                "This does not delete messages or files already sent to Telegram."
            ]), Keyboard([
                [Button("Confirm delete", callback_data=f"{PREFIX}:{bot_id}:delete_confirm", style=ButtonStyle.DANGER)],
                [Button("Keep clone", callback_data=f"{PREFIX}:{bot_id}:back")],
            ]))
            await query.answer()
            return
        if action in ("start", "restart", "profile", "p", "pc") and not await entitled(presser):
            await query.answer("Starting or reconfiguring clones requires bot premium, including for Owner and sudo users.", show_alert=True)
            return
        if action in ("profile", "p", "pc", "back"):
            await _profile_press(client, query, target, action, extra, presser)
            return
        if action in ("start", "restart"):
            try:
                username = await manager.restart(target) if action == "restart" else await manager.start(target)
            except CloneError as exc:
                await query.answer(str(exc), show_alert=True)
                return
            await store.aupdate(bot_id, username=username or target.username,
                **({"disabled": False} if store._db is None else {}))
            said = f"{target.handle} is running."
        elif action == "stop":
            if not await manager.stop(bot_id):
                await query.answer("It was already stopped.", show_alert=True)
                return
            if store._db is None:
                await store.aupdate(bot_id, disabled=True)
            said = f"{target.handle} is stopped."
        elif action == "delete_confirm":
            await manager.stop(bot_id)
            await store.aremove(bot_id)
            said = f"{target.handle} was deleted."
            if events is not None:
                events.emit("clone:delete", bot_id=bot_id, by=presser)
        else:
            await query.answer("That button is stale.", show_alert=True)
            return
        if events is not None and action != "delete_confirm":
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
        "panel": mybots,
        "delclone": delclone,
        "clonestats": clonestats,
    }


def extra_handlers(ctx):
    """Only private setup messages reach the guided clone workflow."""
    from pyrogram import filters
    from pyrogram.handlers import MessageHandler
    return [MessageHandler(ctx.clone_setup.receive, filters.private & filters.text)]
