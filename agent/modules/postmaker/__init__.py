"""Post maker — group-local layouts and bounded, escaped composition."""
from __future__ import annotations

import html
import logging

from pyrogram.enums import ParseMode

from ...platform.post_templates import PostTemplates
from ...platform.manifest import PluginManifest
from ...ui.tables import panel
from ..moderation import is_moderator
from ...utils.rich import reply
from .templates import (
    DEFAULT_TEMPLATE, TEMPLATE_KEY,
    PostError, _post_text, render as render, split_title_body,
)

__all__ = ["MANIFEST", "build", "render"]

logger = logging.getLogger(__name__)
MANIFEST = PluginManifest(
    group_compatible=True,
    clone_compatible=True,
    slug="postmaker", name="Post maker", version="1.1.0",
    description="Compose and publish formatted posts from a per-chat template.",
    commands=("post",),
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
                     footer='/post Title | body · /help post')

    async def guard(client, message):
        if await is_moderator(client, message, owner_id=ctx.settings.owner_id):
            return True
        await reply(message, feedback('Post studio locked', 'Only moderators can publish posts.', 'lock'))
        return False


    async def post(client, message):
        if not await guard(client, message):
            return
        title, body = split_title_body(message)
        if not title and not body:
            command = 'post'
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
                raise PostError('The stored layout produced an empty post. Ask the deployment Owner to review the layout.')
        except PostError as error:
            await reply(message, feedback('Check post', html.escape(str(error)), 'warn'))
            return
        try:
            await client.send_message(message.chat.id, text, parse_mode=ParseMode.HTML)
        except Exception as error:
            logger.warning('post delivery unconfirmed (%s)', type(error).__name__)
            await reply(message, feedback('Delivery unconfirmed',
                f'The post delivery was not confirmed ({type(error).__name__}). Check the chat before retrying to avoid duplicates. '
                'Verify HTML and sending permissions.', 'warn'))
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


    return MANIFEST, {'post': post}
