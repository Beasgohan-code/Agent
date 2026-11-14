"""Reports and appeals — a queue a moderator can close by number.

``/report`` records a member's complaint about a message, ``/reports`` is the
moderator queue, and ``/appeal`` is the member's way to contest a moderation
action. Everything is stored per chat in the shared chat store, numbered so a
moderator can close one by number.

Two things are deliberately explicit:

* an appeal is **forwarded to the owner's DM** when ``OWNER_ID`` is set, and the
  reply says whether that actually worked — a "sent" that never left the box
  would be worse than no answer;
* there is no inline resolve button. Resolving is ``/reports close <n>``, which
  is a real command with a real effect rather than a callback that edits a
  message and forgets the state.
"""

from __future__ import annotations

import logging
import time

from ...platform.manifest import PluginManifest
from ...ui.tables import Table, panel
from ..moderation import is_moderator
from ...utils.rich import reply
from .queue import _args, _reason, _notify_owner, replicated

logger = logging.getLogger(__name__)

MANIFEST = PluginManifest(
    slug="reports",
    name="Reports & appeals",
    version="1.0.0",
    description="Members report messages, moderators work a numbered queue, appeals reach the owner.",
    commands=("report", "reports", "appeal"),
    permissions=("messages.read", "messages.send"),
    scope="all",
)


def build(ctx):
    events = getattr(ctx, "events", None)

    # -- /report -----------------------------------------------------------

    async def report(client, message):
        replied = getattr(message, "reply_to_message", None)
        if replied is None:
            await reply(message, 
                "Reply to the message you are reporting with <code>/report [reason]</code>."
            )
            return
        target = getattr(replied, "from_user", None)
        number = ctx.chats.add_report(
            message.chat.id,
            reporter_id=message.from_user.id,
            target_id=getattr(target, "id", None),
            message_id=getattr(replied, "id", None),
            reason=_reason(message) or "no reason given",
        )
        ctx.chats.log(
            message.chat.id,
            "report",
            actor_id=message.from_user.id,
            target_id=getattr(target, "id", None),
            reason=f"#{number}",
        )
        logger.info(
            "report filed chat=%s number=%s reporter=%s target=%s",
            message.chat.id,
            number,
            message.from_user.id,
            getattr(target, "id", None),
        )
        if events is not None:
            events.emit(
                "report",
                chat=message.chat.id,
                number=number,
                reporter=message.from_user.id,
            )
        await reply(message, 
            panel(
                "Report recorded",
                icon=ctx.theme.emoji("shield"),
                lines=[
                    f"Report <b>#{number}</b> is in this chat's queue.",
                    "A moderator can read it with <code>/reports</code>.",
                ],
                footer="Reports are numbered per chat and kept in the chat store.",
            )
        )

    # -- /reports ----------------------------------------------------------

    async def reports(client, message):
        if not await is_moderator(client, message, owner_id=ctx.settings.owner_id):
            await reply(message, "Only moderators can read the report queue.")
            return
        parts = _args(message)
        rest = parts[1].split() if len(parts) > 1 else []
        if rest and rest[0].lower() == "close":
            if len(rest) < 2 or not rest[1].isdigit():
                await reply(message, "Usage: <code>/reports close &lt;number&gt;</code>")
                return
            number = int(rest[1])
            if not ctx.chats.close_report(message.chat.id, number, by=message.from_user.id):
                await reply(message, f"There is no open report #{number} in this chat.")
                return
            ctx.chats.log(
                message.chat.id, "report:close", actor_id=message.from_user.id,
                reason=f"#{number}",
            )
            logger.info(
                "report closed chat=%s number=%s by=%s",
                message.chat.id,
                number,
                message.from_user.id,
            )
            await reply(message, f"Report #{number} closed.")
            return

        open_reports = ctx.chats.reports(message.chat.id, state="open")
        if not open_reports:
            await reply(message, 
                panel(
                    "Reports",
                    icon=ctx.theme.emoji("shield"),
                    lines=["No open reports in this chat."],
                    footer="Members file them with <code>/report</code>.",
                )
            )
            return
        rows = tuple(
            (
                f"#{entry.get('id')}",
                entry.get("kind", "report"),
                str(entry.get("reporter") or "—"),
                entry.get("reason") or "—",
                time.strftime("%d %b %H:%M", time.gmtime(entry.get("at", 0))),
            )
            for entry in replicated(open_reports)
        )
        await reply(message, 
            panel(
                "Reports",
                icon=ctx.theme.emoji("shield"),
                subtitle=f"<b>{len(open_reports)}</b> open — newest last.",
                table=Table(
                    headers=("No", "Kind", "Reporter", "Reason", "When"),
                    rows=rows,
                    aligns=("left", "left", "right", "left", "left"),
                    total_width=56,
                ),
                note="Close one with <code>/reports close &lt;number&gt;</code>.",
                footer="Moderators only.",
            )
        )

    # -- /appeal -----------------------------------------------------------

    async def appeal(client, message):
        text = _reason(message)
        if not text:
            await reply(message, 
                "Usage: <code>/appeal &lt;what happened&gt;</code> — it goes to the owner."
            )
            return
        number = ctx.chats.add_report(
            message.chat.id,
            reporter_id=message.from_user.id,
            reason=text,
            kind="appeal",
        )
        delivered = await _notify_owner(client, ctx.settings.owner_id, message, number, text)
        logger.info(
            "appeal filed chat=%s number=%s reporter=%s delivered=%s",
            message.chat.id,
            number,
            message.from_user.id,
            delivered,
        )
        if events is not None:
            events.emit(
                "appeal", chat=message.chat.id, number=number, reporter=message.from_user.id
            )
        lines = [f"Appeal <b>#{number}</b> recorded."]
        lines.append(delivered)
        await reply(message, 
            panel(
                "Appeal",
                icon=ctx.theme.emoji("info"),
                lines=lines,
                footer="Appeals are kept with the reports of this chat.",
            )
        )

    return MANIFEST, {"report": report, "reports": reports, "appeal": appeal}


