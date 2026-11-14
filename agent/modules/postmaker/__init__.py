"""Post maker — group-local layouts and bounded, escaped composition."""
from __future__ import annotations

import html
import logging

from pyrogram.enums import ParseMode

from ...platform.post_templates import PostTemplates
from ...platform.manifest import PluginManifest
from ...ui.tables import kv_table, panel
from ..moderation import is_moderator
from ...utils.rich import reply
from .templates import (
    DEFAULT_TEMPLATE, MAX_BODY, MAX_TEMPLATE, MAX_TITLE, TEMPLATE_KEY,
    PostError, _args, _post_text, render as render, split_title_body,
)

__all__ = ["MANIFEST", "build", "render"]

logger = logging.getLogger(__name__)
MANIFEST = PluginManifest(
    slug="postmaker", name="Post maker", version="1.1.0",
    description="Compose and publish formatted posts from a per-chat template.",
    commands=("post", "postpreview", "posttemplate"),
    permissions=("messages.read", "messages.send"), scope="group",
)


def build(ctx):
    database = getattr(ctx, 'db', None)
    templates = PostTemplates(database) if database is not None else None

    async def get_template(chat_id):
        legacy = ctx.chats.get(chat_id, TEMPLATE_KEY, DEFAULT_TEMPLATE)
        return await templates.get(chat_id, legacy) if templates is not None else legacy

    def feedback(title, text, icon='info'):
        return panel(title, icon=ctx.theme.emoji(icon), lines=[text],
                     footer='/postpreview Title | body · /posttemplate')

    async def guard(client, message):
        if await is_moderator(client, message, owner_id=ctx.settings.owner_id):
            return True
        await reply(message, feedback('Post studio locked', 'Only moderators can publish posts.', 'lock'))
        return False

    async def posttemplate(client, message):
        if not await guard(client, message):
            return
        rest = _args(message)
        candidate = rest[1].strip() if len(rest) > 1 else ''
        if not candidate:
            try:
                current = await get_template(message.chat.id)
            except Exception:
                await reply(message, feedback('Template unavailable', 'Could not read current PostgreSQL settings. No stale layout was displayed.', 'warn'))
                return
            await reply(message, panel('Post studio', icon=ctx.theme.emoji('diamond'),
                subtitle=f"{ctx.theme.emoji('gear')} This group's layout",
                table=kv_table([('Template limit', str(MAX_TEMPLATE)), ('Title limit', str(MAX_TITLE)), ('Body limit', str(MAX_BODY))]),
                lines=['<b>Current template</b>\n<code>' + html.escape(current) + '</code>'],
                note='Use <code>{title}</code> and <code>{body}</code>. HTML is trusted administrator input. '
                     '<code>/posttemplate reset</code> restores the default.',
                footer='Group-local settings · PostgreSQL reads' if templates is not None else 'Standalone settings compatibility mode'))
            return
        if candidate.lower() == 'reset':
            candidate = DEFAULT_TEMPLATE
        if len(candidate) > MAX_TEMPLATE:
            await reply(message, feedback('Template too long', f'That template is too long ({len(candidate)} characters, limit {MAX_TEMPLATE}).', 'warn'))
            return
        try:
            example = _post_text(candidate, 'Example title', 'Example body')
            if templates is not None:
                await templates.set(message.chat.id, candidate)
            else:
                ctx.chats.put(message.chat.id, TEMPLATE_KEY, candidate)
        except PostError as error:
            await reply(message, feedback('Check template', html.escape(str(error)), 'warn'))
            return
        except Exception:
            await reply(message, feedback('Template not confirmed', 'The settings write could not be confirmed. Check /posttemplate before retrying.', 'warn'))
            return
        await reply(message, feedback('Template updated',
            f"{ctx.theme.emoji('check')} " + ('PostgreSQL confirmed the template write.' if templates is not None else
                'Applied in standalone compatibility mode.') + '\n\nExample:\n' + example, 'gear'))

    async def compose(client, message, *, publish):
        if not await guard(client, message):
            return
        title, body = split_title_body(message)
        if not title and not body:
            command = 'post' if publish else 'postpreview'
            await reply(message, feedback('Compose a post',
                f'Usage: <code>/{command} Title | body</code>, or reply to a message. '
                'A title can be supplied while replying to text or a media caption.', 'sparkles'))
            return
        try:
            template = await get_template(message.chat.id)
        except Exception:
            await reply(message, feedback('Template unavailable', 'Could not read current PostgreSQL settings. No preview or post was sent.', 'warn'))
            return
        try:
            text = _post_text(template, title, body)
            if not text.strip():
                raise PostError('The template produced an empty post. Check /posttemplate.')
        except PostError as error:
            await reply(message, feedback('Check post', html.escape(str(error)), 'warn'))
            return
        if not publish:
            # Use the same payload/HTML path as publication, not a rich panel
            # whose heading or transformation can change the final layout.
            await reply(message, feedback('Post preview',
                f"{ctx.theme.emoji('eyes')} The next message is a group-visible preview using the publication payload. It is not private; no publish audit entry is created.", 'sparkles'))
        try:
            await client.send_message(message.chat.id, text, parse_mode=ParseMode.HTML)
        except Exception as error:
            logger.warning('post delivery unconfirmed (%s)', type(error).__name__)
            await reply(message, feedback('Delivery unconfirmed',
                f'The post delivery was not confirmed ({type(error).__name__}). Check the chat before retrying to avoid duplicates. '
                'Verify HTML and sending permissions.', 'warn'))
            return
        if not publish:
            return
        try:
            ctx.chats.log(message.chat.id, 'post', actor_id=message.from_user.id, reason='Published post')
        except Exception:
            logger.warning('published post audit write unconfirmed')
            await reply(message, feedback('Post delivered', 'Telegram acknowledged delivery, but the audit settings write was not confirmed. Do not republish.', 'warn'))
            return
        logger.info('post published chat=%s by=%s chars=%s', message.chat.id, message.from_user.id, len(text))
        await reply(message, feedback('Post delivered',
            f"{ctx.theme.emoji('check')} Telegram acknowledged publication in this group.", 'check'))

    async def postpreview(client, message):
        await compose(client, message, publish=False)

    async def post(client, message):
        await compose(client, message, publish=True)

    return MANIFEST, {'posttemplate': posttemplate, 'postpreview': postpreview, 'post': post}
