"""Thumbnails and captions that are actually used when a file is sent.

Shared by every module that sends a file, so the rule lives in one place.

A saved thumbnail or caption is only worth storing if the next file this bot
sends carries it — otherwise the command is a form that goes nowhere. The
senders (filestore's ``/get``, leech's ``/leech``, renamer's ``/rename``) all ask
these two helpers, so there is one place where "what goes with the file" is
decided.

Storage is per chat. In a private chat the chat id *is* the user id, so a person
who sets these in a DM gets exactly the per-user behaviour they expect; in a
group the setting belongs to the group, which is what a caption on a shared file
should be.
"""

from __future__ import annotations

import html
import re

from .media_rules import transform

#: Chat setting: a Telegram file id of the thumbnail to attach.
THUMB_KEY = "thumb_file"

#: Chat setting: the caption template, with ``{name}``, ``{size}`` and ``{stem}``.
CAPTION_KEY = "caption_template"

#: Telegram's caption cap, in characters.
MAX_CAPTION = 1024


def render_caption(template: str | None, *, name: str, size: str) -> str | None:
    """The caption for one file, or ``None`` when the chat has no template.

    Substitution is literal: an unknown ``{field}`` is left visible instead of
    raising, because a caption that breaks a send is worse than a stray brace.
    """
    if not template:
        return None
    stem = name.rsplit(".", 1)[0] if "." in name else name
    quality = re.search(r"(?<![a-z0-9])(2160p|1440p|1080p|720p|576p|480p|360p|240p)(?![a-z0-9])", name, re.I)
    episode = re.search(r"(?<![a-z0-9])S([0-9]{1,2})[ ._-]?E([0-9]{1,4})(?![0-9])", name, re.I)
    codec = re.search(r"(?<![a-z0-9])(hevc|avc|x264|x265|h264|h265)(?![a-z0-9])", name, re.I)
    values = {"name": name, "filename": name, "file_name": name, "size": size, "stem": stem,
              "quality": quality.group(1).lower() if quality else "unknown",
              "season": str(int(episode.group(1))) if episode else "unknown",
              "episode": str(int(episode.group(2))) if episode else "unknown",
              "format": codec.group(1).lower() if codec else "unknown"}
    # One pass: a filename containing {size} is data, not another template.
    # Escape substituted data, while preserving the user's own HTML template.
    text = re.sub(r"\{([a-z_]+)\}",
                  lambda match: html.escape(str(values[match.group(1)]), quote=False)
                  if match.group(1) in values else match.group(0), template)
    visible = html.unescape(re.sub(r"<[^>]*>", "", text))
    if len(visible.encode("utf-16-le")) // 2 <= MAX_CAPTION:
        return text
    # If expansion exceeds Telegram's budget, degrade to escaped plain text
    # rather than slicing through a tag/entity or half an astral code point.
    kept, used = [], 0
    for char in visible:
        width = 2 if ord(char) > 0xFFFF else 1
        if used + width > MAX_CAPTION - 1:
            break
        kept.append(char)
        used += width
    return html.escape("".join(kept) + "…", quote=False)


def caption_for(chats, chat_id: int, *, name: str, size: str, apply_rules: bool = True) -> str | None:
    """The caption this chat wants on *name*, or ``None``."""
    if chats is None:
        return None
    return render_caption(chats.get(chat_id, CAPTION_KEY), name=transform(chats, chat_id, name) if apply_rules else name, size=size)


def thumb_for(chats, chat_id: int) -> str | None:
    """The stored thumbnail file id for this chat, or ``None``."""
    if chats is None:
        return None
    return chats.get(chat_id, THUMB_KEY) or None


def attachment_kwargs(chats, chat_id: int, *, name: str, size: str, apply_rules: bool = True) -> dict:
    """``{"caption": ..., "thumb": ...}`` for ``send_document``, minus the empties."""
    payload: dict = {}
    caption = caption_for(chats, chat_id, name=name, size=size, apply_rules=apply_rules)
    if caption:
        payload["caption"] = caption
    thumb = thumb_for(chats, chat_id)
    if thumb:
        payload["thumb"] = thumb
    return payload
