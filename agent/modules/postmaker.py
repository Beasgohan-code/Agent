"""Post Maker — Meikoagent's ``post_maker`` without the scheduler.

``/posttemplate`` stores a per-chat layout, ``/postpreview`` renders it, and
``/post`` publishes it. The template is trusted input (an administrator writes
it, and it is the only place formatting can come from); the *values* substituted
into it are escaped, so a title containing ``<b>`` cannot break the post.

Meikoagent also schedules posts. That needs a queue that survives a restart and a
tick that fires on time; this module does not ship one, and it does not pretend
to — there is no ``/schedule`` command until there is a scheduler behind it.
"""

from __future__ import annotations

import html
import logging

from ..platform.manifest import PluginManifest
from ..ui.tables import kv_table, panel
from .moderation import is_moderator
from ..utils.rich import reply

logger = logging.getLogger(__name__)

MANIFEST = PluginManifest(
    slug="postmaker",
    name="Post maker",
    version="1.0.0",
    description="Compose and publish formatted posts from a per-chat template.",
    commands=("post", "postpreview", "posttemplate"),
    permissions=("messages.read", "messages.send"),
    scope="group",
)

TEMPLATE_KEY = "post_template"
DEFAULT_TEMPLATE = "<b>{title}</b>\n\n{body}"
MAX_BODY = 3000
MAX_TEMPLATE = 600


def _args(message) -> list[str]:
    return (getattr(message, "text", "") or "").split(maxsplit=1)


def split_title_body(message) -> tuple[str, str]:
    """``/post Title | body``, or ``/post Title`` with the body replied to."""
    rest = _args(message)
    payload = rest[1].strip() if len(rest) > 1 else ""
    replied = getattr(message, "reply_to_message", None)
    replied_text = (getattr(replied, "text", "") or "").strip() if replied else ""
    if "|" in payload:
        title, body = payload.split("|", 1)
        return title.strip(), body.strip()
    if payload and replied_text:
        return payload, replied_text
    if payload and not replied_text:
        return payload, ""
    return "", replied_text


def render(template: str, title: str, body: str) -> str:
    """Substitute escaped values into the (trusted) template."""
    rendered = (template or DEFAULT_TEMPLATE)
    rendered = rendered.replace("{title}", html.escape(title))
    rendered = rendered.replace("{body}", html.escape(body))
    return rendered[:MAX_BODY]


def build(ctx):
    async def _guard(client, message) -> bool:
        if await is_moderator(client, message, owner_id=ctx.settings.owner_id):
            return True
        await reply(message, "Only moderators can publish posts.")
        return False

    async def posttemplate(client, message):
        if not await _guard(client, message):
            return
        rest = _args(message)
        candidate = rest[1].strip() if len(rest) > 1 else ""
        if not candidate:
            current = ctx.chats.get(message.chat.id, TEMPLATE_KEY, DEFAULT_TEMPLATE)
            await reply(message, 
                panel(
                    "Post template",
                    icon=ctx.theme.emoji("gear"),
                    table=kv_table([("Current", current)]),
                    note=(
                        "Change it with <code>/posttemplate &lt;text&gt;</code>. "
                        "Use <code>{title}</code> and <code>{body}</code>; HTML is allowed here."
                    ),
                    footer="Stored per chat.",
                )
            )
            return
        if len(candidate) > MAX_TEMPLATE:
            await reply(message, 
                f"That template is too long ({len(candidate)} characters, limit {MAX_TEMPLATE})."
            )
            return
        ctx.chats.put(message.chat.id, TEMPLATE_KEY, candidate)
        await reply(message, 
            "Template saved.\nPreview:\n"
            + render(candidate, "Example title", "Example body")
        )

    async def postpreview(client, message):
        if not await _guard(client, message):
            return
        title, body = split_title_body(message)
        if not title and not body:
            await reply(message, 
                "Usage: <code>/postpreview Title | body</code>, or reply to a message."
            )
            return
        template = ctx.chats.get(message.chat.id, TEMPLATE_KEY, DEFAULT_TEMPLATE)
        await reply(message, "Preview:\n" + render(template, title, body))

    async def post(client, message):
        if not await _guard(client, message):
            return
        title, body = split_title_body(message)
        if not title and not body:
            await reply(message, 
                "Usage: <code>/post Title | body</code>, or reply to a message with "
                "<code>/post Title</code>."
            )
            return
        if len(body) > MAX_BODY:
            await reply(message, 
                f"That body is too long ({len(body)} characters, limit {MAX_BODY})."
            )
            return
        template = ctx.chats.get(message.chat.id, TEMPLATE_KEY, DEFAULT_TEMPLATE)
        text = _post_text(template, title, body)
        await reply(message, "Publishing…")
        try:
            await client.send_message(message.chat.id, text)
        except Exception as exc:  # noqa: BLE001 - reported, never claimed
            logger.exception("post failed")
            await reply(message, 
                f"Could not publish that post: {type(exc).__name__}. "
                "Check that I can send messages here."
            )
            return
        ctx.chats.log(message.chat.id, "post", actor_id=message.from_user.id, reason=title[:80])

    return MANIFEST, {
        "posttemplate": posttemplate,
        "postpreview": postpreview,
        "post": post,
    }


def _post_text(template: str, title: str, body: str) -> str:
    """Render and wrap in the screen normaliser, so rich-only tags still work."""
    from ..utils.sender import to_safe_html

    return to_safe_html(render(template, title, body))


