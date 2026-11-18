"""Core — the commands that explain the bot to whoever is using it.

``/menu`` redraws the start screen, ``/about`` says what is loaded and how much
each module adds, ``/status`` reads this process's live counters, ``/cancel``
stops the caller's own jobs, and ``/owner`` is the owner's panel.

Two of them are stricter than a placeholder would be: ``/cancel`` reports only
what it actually stopped, and ``/status`` reads the health monitor instead of
quoting numbers nobody measured. ``/owner`` needs ``OWNER_ID`` and says so
rather than guessing.
"""

from __future__ import annotations

import logging
import re

from ... import __version__
from ...platform.manifest import PluginManifest
from ...ui.keyboards import nav_keyboard
from ...ui.screens import format_uptime, welcome_screen
from ...ui.tables import Table, kv_table, panel
from ...utils.rich import reply

logger = logging.getLogger(__name__)

MANIFEST = PluginManifest(
    group_compatible=True,
    clone_compatible=False,
    slug="core",
    name="Core extras",
    version="1.0.0",
    description="Menu, about, runtime status, job cancellation and the owner panel.",
    commands=("lang", "menu", "about", "status", "alive", "uptime", "cancel", "jobs", "owner"),
    permissions=("messages.read",),
    scope="all",
)

OWNER_ONLY = "This command is reserved for the bot owner."


def _human_bytes(count: float) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if count < 1024 or unit == "GB":
            return f"{count:.0f} {unit}" if unit == "B" else f"{count:.1f} {unit}"
        count /= 1024
    return f"{count:.1f} GB"  # pragma: no cover - unreachable


def build(ctx):
    """Wire the core-extras commands to the shared context."""

    def _registry_summary() -> tuple[str, int]:
        registry = ctx.registry
        if registry is None:  # pragma: no cover - always set by the bot
            return "unknown", 0
        manifests = registry.manifests()
        enabled = [m.name for m in manifests if registry.is_enabled(m.slug)]
        return ", ".join(enabled) or "none", len(registry.active_commands())

    async def menu(_client, message):
        user = getattr(message, "from_user", None)
        active = (
            set(ctx.registry.active_commands()) if ctx.registry is not None else None
        )
        from ...ui.bot_identity import bot_username
        username = await bot_username(_client) if ctx.theme.worker_plugins is None else None
        await ctx.sender.send_hero(
            message.chat.id, welcome_screen(user, ctx.theme, active=active, bot_username=username), ctx.settings.start_image
        )

    def _module_rows() -> tuple[tuple[str, str], ...]:
        """What is actually loaded, and how much each module adds."""
        registry = getattr(ctx, "registry", None)
        if registry is None:  # pragma: no cover - always set by the bot
            return ()
        return tuple(
            (manifest.name, str(len(manifest.commands)))
            for manifest in registry.manifests()
            if manifest.commands and registry.is_enabled(manifest.slug)
        )

    async def about(_client, message):
        from ...platform.policy import is_worker
        if is_worker(ctx.settings):
            from ...ui.workers import about_screen
            active = set(ctx.registry.active_commands())
            await ctx.sender.send(message.chat.id, about_screen(message.from_user, ctx.theme, active=active))
            return
        modules, commands = _registry_summary()
        await reply(
            message,
            panel(
                "About Agent",
                icon=ctx.theme.emoji("sparkles"),
                subtitle=f"Version <b>{__version__}</b> · {commands} commands",
                lines=[
                    f"Modules: {modules}",
                    "One job queue, one file store, one link signer — modules share "
                    "them instead of running their own.",
                ],
                table=Table(
                    headers=("Module", "Commands"),
                    rows=_module_rows(),
                ),
                note=(
                    "Every module shares the same queue, store and link signer, so "
                    "a file saved in one can be fetched by another."
                ),
                footer="<code>/help</code> shows this bot's registered tools.",
            ),
            reply_markup=nav_keyboard(),
        )

    async def status(_client, message):
        modules, commands = _registry_summary()
        rows: list[tuple[str, str]] = [("Version", __version__)]
        if ctx.monitor is not None:
            snapshot = ctx.monitor.snapshot()
            rows.extend(
                [
                    ("State", snapshot.state),
                    ("Uptime", format_uptime(snapshot.uptime_seconds)),
                    ("Probes", f"{snapshot.probes} ({snapshot.failures} failed)"),
                    (
                        "Latency",
                        f"{snapshot.latency_ms} ms"
                        if snapshot.latency_ms is not None
                        else "no probe yet",
                    ),
                ]
            )
        if ctx.jobs is not None:
            rows.append(("Jobs running", str(len(ctx.jobs.active()))))
        database = getattr(ctx, "db", None)
        rows.append(
            ("State store", "postgres" if database is not None and database.connected else "json files")
        )
        rows.append(("Modules", modules))
        rows.append(("Commands", str(commands)))
        user = getattr(message, "from_user", None)
        if user is not None and ctx.storage is not None:
            rows.append(("Your storage", _human_bytes(ctx.storage.usage(user.id))))
        await reply(message,
            panel(
                "Runtime status",
                icon=ctx.theme.emoji("stats"),
                subtitle="Read from this process, not from a cache.",
                table=kv_table(rows),
                footer="<code>/ping</code> checks the link, <code>/owner</code> shows the owner panel.",
            ),
            reply_markup=nav_keyboard(),
        )

    async def uptime(_client, message):
        if ctx.monitor is None:
            await reply(message, "Uptime is unavailable; no process health monitor is attached.")
            return
        snapshot = ctx.monitor.snapshot()
        await reply(message, panel(
            "Agent uptime", icon=ctx.theme.emoji("stats"),
            table=kv_table([
                ("Process uptime", format_uptime(snapshot.uptime_seconds)),
                ("Telegram state", snapshot.state),
                ("Probe latency", "pending" if snapshot.latency_ms is None else f"{snapshot.latency_ms} ms"),
                ("Consecutive failures", str(snapshot.consecutive_failures)),
                ("Last successful probe", "not yet" if snapshot.seconds_since_ok is None else f"{snapshot.seconds_since_ok:.0f}s ago"),
                ("Successful probes", str(snapshot.probes - snapshot.failures)),
                ("Failed probes", str(snapshot.failures)),
            ]),
            note="Measured since this process started; restarts reset uptime. Not a 24/7 availability percentage.",
        ))

    async def cancel(_client, message):
        user = getattr(message, "from_user", None)
        if user is None or ctx.jobs is None:
            await reply(message, "Nothing to cancel.")
            return
        parts = (getattr(message, "text", None) or "").split()
        if len(parts) > 1:
            if len(parts) != 2:
                await reply(message, "Use /cancel for all your active jobs, or /cancel <job-id> for one.")
                return
            job_id = parts[1]
            job = ctx.jobs.get(job_id)
            if job is None or job.owner_id != user.id:
                await reply(message, "No matching job belongs to you. Open /jobs privately to check your IDs.")
                return
            if not ctx.jobs.cancel(job_id, owner_id=user.id):
                await reply(message, "That job has already finished. Nothing was cancelled.")
                return
            await reply(message, "Cancelled the selected job. Your other jobs are unchanged.")
            return
        setup = getattr(ctx, "clone_setup", None)
        if setup is not None and setup.active(user.id) is not None and message.chat.id == user.id:
            await setup.receive(_client, message)
            return
        stopped = 0
        for job in ctx.jobs.active():
            if job.owner_id != user.id:
                continue
            stopped += bool(ctx.jobs.cancel(job.id, owner_id=user.id))
        if stopped:
            await reply(message, f"Cancelled {stopped} job(s).")
        else:
            await reply(message, "Nothing was running, so nothing was cancelled.")

    async def owner(_client, message):
        owner_id = ctx.settings.owner_id
        if owner_id is None:
            await reply(message,
                "No owner is configured. Set <code>OWNER_ID</code> to your Telegram "
                "user id and restart to enable this command."
            )
            return
        user = getattr(message, "from_user", None)
        if user is None or int(user.id) != int(owner_id):
            await reply(message, OWNER_ONLY)
            return
        modules, commands = _registry_summary()
        rows: list[tuple[str, str]] = [("Version", __version__)]
        if ctx.monitor is not None:
            snapshot = ctx.monitor.snapshot()
            rows.append(("Uptime", format_uptime(snapshot.uptime_seconds)))
            rows.append(("State", snapshot.state))
            if snapshot.last_error:
                rows.append(("Last error", snapshot.last_error[:120]))
        if ctx.jobs is not None:
            rows.append(("Jobs running", str(len(ctx.jobs.active()))))
        rows.append(("Modules", modules))
        rows.append(("Commands", str(commands)))
        rows.append(("Data dir", str(ctx.settings.data_dir)))
        await reply(message,
            panel(
                "Owner panel",
                icon=ctx.theme.emoji("bot"),
                subtitle="Controls that only the bot owner may use.",
                table=kv_table(rows),
                note=(
                    "<code>/plugins</code> · <code>/plugin &lt;slug&gt; on|off</code> · "
                    "<code>/events</code> · <code>/watchdog</code> · <code>/restart</code>"
                ),
                footer="Owner only.",
            ),
            reply_markup=nav_keyboard(),
        )

    async def jobs(_client, message):
        user = getattr(message, "from_user", None)
        uid = getattr(user, "id", None)
        if type(uid) is not int or uid <= 0 or getattr(message.chat, "id", None) != uid:
            await reply(message, "Open /jobs privately with your personal Telegram account.")
            return
        if ctx.jobs is None:
            await reply(message, "The job queue is unavailable.")
            return
        args = (getattr(message, "text", None) or "").split()[1:]
        if len(args) > 1 or (args and not re.fullmatch(r"[a-z][a-z0-9_]{0,31}", args[0])):
            await reply(message, "Use /jobs or /jobs <module>, for example /jobs encoder or /jobs leech.")
            return
        module = args[0] if args else None
        owned = ctx.jobs.for_owner(uid)
        recent = sorted((job for job in owned if module is None or job.module == module),
                        key=lambda job: job.created_at, reverse=True)[:20]
        await reply(message, panel("Your recent jobs" + (f" · {module}" if module else ""), icon=ctx.theme.emoji("gear"),
            table=Table(headers=("Job", "Module", "State", "Progress"), rows=tuple(
                (job.id, job.module, job.state.value, f"{max(0, min(100, int(job.progress * 100)))}%") for job in recent)),
            lines=[] if recent else ["No matching jobs are recorded for you in this process session."],
            note="Latest 20 jobs in this bot only. Source links, local paths and raw error details are hidden. /cancel &lt;job-id&gt; stops one job; /cancel stops all your active jobs.",
            footer="Process memory only; history does not survive restart."))

    language_handler = build_language_picker(ctx)
    handlers = {
        "lang": language_handler,
        "menu": menu,
        "about": about,
        "status": status,
        "alive": status,
        "uptime": uptime,
        "cancel": cancel,
        "jobs": jobs,
        "owner": owner,
    }

    from dataclasses import replace
    from ...platform.policy import is_worker, worker_job_tools
    if is_worker(ctx.settings):
        allowed = {'menu', 'about', 'lang'}
        if worker_job_tools(ctx.settings.plugins):
            allowed.update(('jobs', 'cancel'))
        handlers = {name: handler for name, handler in handlers.items() if name in allowed}
        return replace(MANIFEST, name='Worker navigation', clone_compatible=True,
                       commands=tuple(handlers)), handlers
    return MANIFEST, handlers


def build_language_picker(ctx):
    """Private self-service or current-admin group preference, not full-bot translation."""
    import asyncio
    from types import SimpleNamespace
    from pyrogram.enums import ChatType
    from pyrogram.types import InlineKeyboardButton as Button, InlineKeyboardMarkup as Keyboard
    from ...platform.languages import LANGUAGES, NAMES, PICKER, preference, LanguageError, UnsupportedLanguage
    from ...utils.rich import edit
    from ..moderation import is_moderator

    async def authorize(client, message, user):
        chat = getattr(message, 'chat', None)
        uid = getattr(user, 'id', None)
        if (type(uid) is not int or not 0 < uid < 2**63 or getattr(user, 'is_bot', False)
                or getattr(message, 'sender_chat', None) is not None):
            raise LanguageError('Use your personal account.')
        if getattr(chat, 'type', None) == ChatType.PRIVATE and chat.id == uid:
            return chat.id
        if getattr(chat, 'type', None) in (ChatType.GROUP, ChatType.SUPERGROUP):
            request = SimpleNamespace(chat=chat, from_user=user)
            if await asyncio.wait_for(is_moderator(client, request, need='can_manage_chat'), 5):
                return chat.id
        raise LanguageError('Group language: Manage chat permission required. Use /lang in private for yourself.')

    def card(uid, scope, code, page=0, saved=False):
        if type(page) is not int or not 0 <= page < (len(LANGUAGES)+11)//12:
            raise LanguageError('Invalid language page. Open /lang again.')
        rows = []
        choices = LANGUAGES[page*12:(page+1)*12]
        for index in range(0, len(choices), 2):
            rows.append([Button(('✓ ' if key == code else '')+name,
                callback_data=f'lang:{uid}:{scope}:set:{key}') for key, name in choices[index:index+2]])
        nav = []
        if page:
            nav.append(Button('‹', callback_data=f'lang:{uid}:{scope}:page:{page-1}'))
        if (page+1)*12 < len(LANGUAGES):
            nav.append(Button('›', callback_data=f'lang:{uid}:{scope}:page:{page+1}'))
        if nav:
            rows.append(nav)
        title = PICKER[code][1 if saved else 0] if code is not None else 'Choose language'
        return panel(title, lines=[NAMES[code]] if code is not None else ['Previous language is unavailable. Choose a supported language.'],
            footer=f'Page {page+1}/{(len(LANGUAGES)+11)//12}',
            note='Only complete languages are listed. More languages will appear after full translation and checks.'), Keyboard(rows)

    async def lang(client, message):
        try:
            uid = getattr(getattr(message, 'from_user', None), 'id', None)
            scope = await authorize(client, message, getattr(message, 'from_user', None))
            if len((getattr(message, 'text', '') or '').split()) != 1:
                raise LanguageError('Use /lang, then choose a language.')
            try:
                code = await preference(ctx, scope)
            except UnsupportedLanguage:
                code = None
            await authorize(client, message, message.from_user)
            text, keyboard = card(uid, scope, code)
            await reply(message, text, reply_markup=keyboard)
        except LanguageError as error:
            await reply(message, str(error))
        except Exception as error:
            logger.warning('#Errors Language picker unavailable (%s)', type(error).__name__)
            await reply(message, 'Language settings unavailable. Try /lang again later.')

    async def press(client, query, rest):
        saved = False
        try:
            parts = rest.split(':')
            if len(parts) != 4:
                raise LanguageError('Invalid language control.')
            owner, scope, action, value = parts
            if owner != str(getattr(getattr(query, 'from_user', None), 'id', None)):
                raise LanguageError('Open your own picker with /lang.')
            actual = await authorize(client, query.message, query.from_user)
            if str(actual) != scope:
                raise LanguageError('This picker belongs to another chat.')
            page = 0
            if action == 'set' and value in NAMES:
                await authorize(client, query.message, query.from_user)
                code = await preference(ctx, actual, code=value, actor=query.from_user.id)
                saved = True
                page = next(i for i, row in enumerate(LANGUAGES) if row[0] == code)//12
            elif action == 'page' and value.isascii() and value.isdecimal() and len(value) <= 2 and int(value) < (len(LANGUAGES)+11)//12:
                page = int(value)
                try:
                    code = await preference(ctx, actual)
                except UnsupportedLanguage:
                    code = None
            else:
                raise LanguageError('Invalid language choice or page.')
            await authorize(client, query.message, query.from_user)
            text, keyboard = card(query.from_user.id, actual, code, page, saved)
            await edit(query, text, reply_markup=keyboard)
            await query.answer()
        except LanguageError as error:
            await query.answer(('Language saved; details unavailable.' if saved else str(error)), show_alert=True)
        except Exception as error:
            logger.warning('#Errors Language selection unavailable (%s)', type(error).__name__)
            await query.answer('Language saved; display unconfirmed.' if saved else 'Language change unconfirmed. Open /lang again.', show_alert=True)

    router = getattr(ctx, 'actions', None)
    if router is not None and not router.handles('lang:x'):
        router.register('lang', press)
    return lang
