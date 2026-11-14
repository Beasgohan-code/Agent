"""Renamer — predictable filenames for media.

``/rename`` renames a replied file with the chat's template, ``/testrename``
shows the result without touching anything, ``/autorename`` applies it to a
batch and ``/clean`` tidies a name in place.

``/renamemode`` is deliberately absent: it would switch automatic renaming on a
pipeline this bot does not have, and a switch with nothing behind it is worse
than no switch.
"""

from __future__ import annotations

import html
import re

from ...platform.manifest import PluginManifest
from ...platform.media_rules import transform
from ...platform.attachments import attachment_kwargs
from .rules import COMMANDS as RULE_COMMANDS, build_rules
from ..moderation import is_moderator
from ...ui.tables import kv_table, panel
from ...utils.rich import reply
from ...platform.attachments import CAPTION_KEY, MAX_CAPTION, THUMB_KEY, caption_for

MANIFEST = PluginManifest(
    slug="renamer",
    name="Renamer",
    version="1.0.0",
    description="Template-driven filenames: preview, rename and clean.",
    commands=(
        "autorename",
        "rename",
        "testrename",
        "clean",
        "setthumb",
        "delthumb",
        "viewthumb",
        "setcaption",
        "viewcaption",
        *RULE_COMMANDS,
    ),
    permissions=("messages.read", "messages.send"),
    scope="all",
)

DEFAULT_TEMPLATE = "{title} S{season:02d}E{episode:02d} [{quality}]"
MAX_NAME = 120
#: Chat setting holding this group's template.
TEMPLATE_KEY = "rename_template"

QUALITY_RE = re.compile(r"\b(2160p|1440p|1080p|720p|576p|480p|360p|4k|2k)\b", re.I)
SEASON_EPISODE_RE = re.compile(r"\bS(?P<season>\d{1,2})[ ._-]?E(?P<episode>\d{1,4})\b", re.I)
EPISODE_ONLY_RE = re.compile(r"\bE(?:P)?(?P<episode>\d{1,4})\b", re.I)
SEASON_ONLY_RE = re.compile(r"\b(?:S|Season[ .]?)(?P<season>\d{1,2})\b", re.I)
YEAR_RE = re.compile(r"\b(19|20)\d{2}\b")
AUDIO_RE = re.compile(
    r"\b(dual audio|multi audio|hindi|english|tamil|telugu|japanese|korean|dubbed)\b", re.I
)
SOURCE_RE = re.compile(
    r"\b(web[- .]?dl|webrip|bluray|blu[- ]ray|hdtv|dvdrip|brrip|amzn|nf|dsnp)\b", re.I
)
BRACKET_RE = re.compile(r"\[[^\]]{1,40}\]|\([^)]{1,40}\)")
#: Trailing scene group, e.g. ``-GROUP``, ``-RARBG``, ``-[YTS.MX]``.
GROUP_RE = re.compile(r"\s*-\s*[A-Za-z0-9][A-Za-z0-9._]{1,20}$")
JUNK_RE = re.compile(
    r"\b(x264|x265|h\.?264|h\.?265|hevc|avc|aac|ac3|eac3|dts|ddp?5\.?1|10bit|8bit|"
    r"proper|repack|extended|remux|yify|yts|rarbg|galaxyrg|psa|evo|ntb)\b",
    re.I,
)
UNSAFE_RE = re.compile(r'[<>:"/\\|?*\x00-\x1f]')
SPACES_RE = re.compile(r"\s{2,}")


def split_extension(name: str) -> tuple[str, str]:
    stem, dot, ext = name.rpartition(".")
    if not dot or len(ext) > 5 or not ext.isalnum():
        return name, ""
    return stem, f".{ext.lower()}"


def clean_title(name: str) -> str:
    """Strip release noise, keeping the words a human would keep."""
    stem, _ext = split_extension(name)
    text = stem.replace(".", " ").replace("_", " ")
    text = BRACKET_RE.sub(" ", text)
    text = JUNK_RE.sub(" ", text)
    text = SEASON_EPISODE_RE.sub(" ", text)
    text = EPISODE_ONLY_RE.sub(" ", text)
    text = SEASON_ONLY_RE.sub(" ", text)
    text = QUALITY_RE.sub(" ", text)
    text = AUDIO_RE.sub(" ", text)
    text = SOURCE_RE.sub(" ", text)
    text = GROUP_RE.sub(" ", text)
    # The year is kept in the title on purpose: "Movie 2023" is a better
    # filename than "Movie", and it is exposed separately as {year}.
    text = re.sub(r"\s+", " ", text).strip(" -_.")
    return text.title() if text.islower() or text.isupper() else text


def parse_filename(name: str) -> dict:
    """Pull the fields a template can use out of one filename."""
    stem, ext = split_extension(name)
    flat = stem.replace(".", " ").replace("_", " ")
    season = episode = quality = audio = source = None
    year_match = YEAR_RE.search(flat)

    match = SEASON_EPISODE_RE.search(flat)
    if match:
        season, episode = int(match["season"]), int(match["episode"])
    else:
        match = EPISODE_ONLY_RE.search(flat)
        if match:
            episode = int(match["episode"])
        match = SEASON_ONLY_RE.search(flat)
        if match:
            season = int(match["season"])

    match = QUALITY_RE.search(flat)
    if match:
        quality = match.group(1).lower()
    match = AUDIO_RE.search(flat)
    if match:
        audio = match.group(1).title()
    match = SOURCE_RE.search(flat)
    if match:
        source = match.group(1).upper().replace(" ", "")

    return {
        "title": clean_title(name) or stem.strip() or "file",
        "season": season,
        "episode": episode,
        "quality": quality or "Unknown",
        "audio": audio or "",
        "source": source or "",
        "year": year_match.group(0) if year_match else "",
        "ext": ext,
    }


def plan_name(filename: str, template: str | None = None) -> tuple[str, list[str]]:
    """Render the template for *filename*. Returns (name, warnings)."""
    fields = parse_filename(filename)
    warnings: list[str] = []
    template = (template or DEFAULT_TEMPLATE).strip() or DEFAULT_TEMPLATE
    data = {
        **fields,
        "season": fields["season"] if fields["season"] is not None else 0,
        "episode": fields["episode"] if fields["episode"] is not None else 0,
    }
    try:
        rendered = template.format_map(_SafeDict(data))
    except (ValueError, IndexError):
        rendered = DEFAULT_TEMPLATE.format_map(_SafeDict(data))
        warnings.append("template was invalid; used the default")

    rendered = UNSAFE_RE.sub("_", rendered)
    rendered = SPACES_RE.sub(" ", rendered).strip(" ._-")
    if fields["ext"] and not rendered.lower().endswith(fields["ext"]):
        rendered = f"{rendered}{fields['ext']}"
    if len(rendered) > MAX_NAME:
        stem, ext = split_extension(rendered)
        rendered = f"{stem[: max(8, MAX_NAME - len(ext))].rstrip(' ._-')}{ext}"
        warnings.append(f"truncated to {MAX_NAME} characters")
    if not rendered:
        rendered = f"file{fields['ext']}"
        warnings.append("template produced an empty name")
    return rendered, warnings


class _SafeDict(dict):
    """Leave unknown placeholders visible instead of raising."""

    def __missing__(self, key):  # noqa: D105
        return "{" + key + "}"


def clean_filename(name: str) -> str:
    """A tidier version of *name*, extension intact."""
    _stem, ext = split_extension(name)
    return f"{clean_title(name)}{ext}"


def _media(message):
    replied = getattr(message, "reply_to_message", None)
    if replied is None:
        return None
    return (
        getattr(replied, "document", None)
        or getattr(replied, "video", None)
        or getattr(replied, "audio", None)
    )


def build(ctx):
    async def autorename(_client, message):
        args = (getattr(message, "text", "") or "").split(maxsplit=1)
        if len(args) < 2:
            current = ctx.chats.get(message.chat.id, TEMPLATE_KEY, DEFAULT_TEMPLATE)
            await reply(message, 
                "<b>Auto-rename template</b>\n"
                f"Current: <code>{html.escape(current)}</code>\n\n"
                "Set one with <code>/autorename {title} S{season:02d}E{episode:02d} [{quality}]</code>.\n"
                "Fields: {title} {season} {episode} {quality} {audio} {source} {ext}"
            )
            return
        template = args[1].strip()
        if "{" not in template:
            await reply(message, 
                "A template needs at least one field, e.g. "
                "<code>{title} S{season:02d}E{episode:02d} [{quality}]</code>."
            )
            return
        ctx.chats.put(message.chat.id, TEMPLATE_KEY, template)
        preview, _warnings = plan_name("Show.Name.S02E05.1080p.WEB-DL.mkv", template)
        await reply(message, 
            f"Template saved.\nPreview: <code>{html.escape(preview)}</code>"
        )

    async def testrename(_client, message):
        args = (getattr(message, "text", "") or "").split(maxsplit=1)
        media = _media(message)
        filename = args[1].strip() if len(args) > 1 else getattr(media, "file_name", None)
        if not filename:
            await reply(message, 
                "Usage: <code>/testrename Movie.2023.1080p.mkv</code> "
                "or reply to a file with <code>/testrename</code>."
            )
            return
        template = ctx.chats.get(message.chat.id, TEMPLATE_KEY, DEFAULT_TEMPLATE)
        planned, warnings = plan_name(filename, template)
        planned = UNSAFE_RE.sub("_", transform(ctx.chats, message.chat.id, planned)).strip(" .")[:MAX_NAME] or "file.bin"
        body = (
            "<b>Rename preview</b>\n"
            f"From: <code>{html.escape(filename)}</code>\n"
            f"To: <code>{html.escape(planned)}</code>"
        )
        if warnings:
            body += "\n" + "\n".join(f"· {html.escape(w)}" for w in warnings)
        await reply(message, body)

    async def rename(client, message):
        media = _media(message)
        if media is None:
            await reply(message, "Reply to a file with <code>/rename</code>.")
            return
        original = getattr(media, "file_name", None) or "file"
        template = ctx.chats.get(message.chat.id, TEMPLATE_KEY, DEFAULT_TEMPLATE)
        planned, warnings = plan_name(original, template)
        planned = UNSAFE_RE.sub("_", transform(ctx.chats, message.chat.id, planned)).strip(" .")[:MAX_NAME] or "file.bin"
        file_id = getattr(media, "file_id", None)
        if not file_id:
            await reply(message, "Telegram did not send a file id for that file.")
            return
        try:
            await client.send_document(
                message.chat.id,
                file_id,
                file_name=planned,
                **({"caption": getattr(media, "caption", None) or ""} |
                   attachment_kwargs(ctx.chats, message.chat.id, name=planned,
                                     size=str(getattr(media, "file_size", 0) or 0) + " bytes", apply_rules=False)),
            )
        except Exception as exc:  # noqa: BLE001 - reported to the user
            await reply(message, f"Rename failed: {type(exc).__name__}")
            return
        body = (
            "<b>Renamed</b>\n"
            f"From: <code>{html.escape(original)}</code>\n"
            f"To: <code>{html.escape(planned)}</code>"
        )
        if warnings:
            body += "\n" + "\n".join(f"· {html.escape(w)}" for w in warnings)
        await reply(message, body)

    async def clean(_client, message):
        args = (getattr(message, "text", "") or "").split(maxsplit=1)
        media = _media(message)
        filename = args[1].strip() if len(args) > 1 else getattr(media, "file_name", None)
        if not filename:
            await reply(message, 
                "Usage: <code>/clean Some.Release.1080p.x264.mkv</code>"
            )
            return
        await reply(message, 
            f"<b>Cleaned</b>\n<code>{html.escape(clean_filename(filename))}</code>"
        )

    # -- thumbnails and captions ------------------------------------------
    chats = getattr(ctx, "chats", None)

    def _unavailable() -> str:
        return "This deployment has no per-chat store, so thumbnails and captions cannot be saved."

    def _thumb_id(message):
        """The file id of the replied image, or None with a reason."""
        replied = getattr(message, "reply_to_message", None)
        if replied is None:
            return None, "Reply to a photo or an image file."
        photo = getattr(replied, "photo", None)
        if photo is not None:
            file_id = getattr(photo, "file_id", None)
            if file_id is None and isinstance(photo, list) and photo:
                file_id = getattr(photo[-1], "file_id", None)
            return (file_id, "") if file_id else (None, "That photo has no file id I can reuse.")
        document = getattr(replied, "document", None)
        if document is not None:
            mime = str(getattr(document, "mime_type", "") or "")
            if not mime.startswith("image/"):
                return None, "That document is not an image."
            return getattr(document, "file_id", None), ""
        return None, "Reply to a photo or an image file."

    async def setthumb(_client, message):
        if chats is None:
            await reply(message, _unavailable())
            return
        file_id, reason = _thumb_id(message)
        if file_id is None:
            await reply(message, reason)
            return
        chats.put(message.chat.id, THUMB_KEY, file_id)
        await reply(
            message,
            panel(
                "Thumbnail saved",
                icon=ctx.theme.emoji("check"),
                table=kv_table([("Applies to", "this chat"), ("Files", "sent by /get, /leech, /rename")]),
                footer="Replace it by replying to another image; <code>/delthumb</code> clears it.",
            ),
        )

    async def delthumb(_client, message):
        if chats is None:
            await reply(message, _unavailable())
            return
        had = chats.get(message.chat.id, THUMB_KEY)
        chats.put(message.chat.id, THUMB_KEY, None)
        await reply(message, "Thumbnail cleared." if had else "There was no thumbnail to clear.")

    async def viewthumb(client, message):
        if chats is None:
            await reply(message, _unavailable())
            return
        file_id = chats.get(message.chat.id, THUMB_KEY)
        if not file_id:
            await reply(message, "No thumbnail is set here. Reply to an image with <code>/setthumb</code>.")
            return
        try:
            await client.send_photo(message.chat.id, file_id, caption="This is the thumbnail this chat uses.")
        except Exception as exc:  # noqa: BLE001 - a stale file id is a real answer
            await reply(message, f"Telegram could not confirm that thumbnail ({type(exc).__name__}). No raw file references are displayed.")

    async def setcaption(_client, message):
        if chats is None:
            await reply(message, _unavailable())
            return
        parts = (getattr(message, "text", "") or "").split(maxsplit=1)
        if len(parts) < 2 or not parts[1].strip():
            await reply(
                message,
                "Usage: <code>/setcaption 📁 {name} — {size}</code>. "
                "Fields: <code>{name}</code> / <code>{filename}</code> / <code>{file_name}</code>, "
                "<code>{stem}</code>, <code>{size}</code>, <code>{quality}</code>, "
                "<code>{season}</code>, <code>{episode}</code>, <code>{format}</code>. "
                "Metadata comes from the filename; unavailable values show unknown.",
            )
            return
        template = parts[1].strip()
        if len(template) > MAX_CAPTION:
            await reply(message, f"That caption is longer than Telegram's {MAX_CAPTION}-character cap.")
            return
        chats.put(message.chat.id, CAPTION_KEY, template)
        example = caption_for(chats, message.chat.id, name="Show.S01E01.1080p.x265.mkv", size="1.2 GB")
        await reply(
            message,
            panel(
                "Caption saved",
                icon=ctx.theme.emoji("check"),
                table=kv_table([("Template", html.escape(template)), ("Example", html.escape(example or ""))]),
                footer="It is attached to files this chat receives from /get, /leech and /rename.",
            ),
        )


    async def viewcaption(_client, message):
        if chats is None:
            await reply(message, _unavailable())
            return
        template = chats.get(message.chat.id, CAPTION_KEY)
        if not template:
            await reply(message, "No caption is set here. Set one with <code>/setcaption</code>.")
            return
        example = caption_for(chats, message.chat.id, name="Show.S01E01.1080p.x265.mkv", size="1.2 GB")
        await reply(
            message,
            panel(
                "Caption for this chat",
                icon=ctx.theme.emoji("info"),
                table=kv_table([("Template", html.escape(template)), ("Example", html.escape(example or ""))]),
                footer="Use <code>/setcaption</code> to change this layout.",
            ),
        )

    def guarded(name, handler):
        async def wrapped(client, message):
            user_id = getattr(getattr(message, "from_user", None), "id", None)
            if type(user_id) is not int or user_id <= 0:
                await reply(message, "Use your personal Telegram user identity for media commands.")
                return
            chat_id = message.chat.id
            mutates = name in ("setcaption", "setthumb", "delthumb") or (
                name == "autorename" and len((getattr(message, "text", "") or "").split(maxsplit=1)) > 1)
            if chat_id < 0 and mutates and not await is_moderator(client, message, owner_id=ctx.settings.owner_id):
                await reply(message, "Only group administrators can change shared media settings.")
                return
            if chats is None and name in ("autorename", "rename", "testrename"):
                await reply(message, _unavailable())
                return
            return await handler(client, message)
        return wrapped

    handlers = {
        **build_rules(ctx),
        "setthumb": setthumb,
        "delthumb": delthumb,
        "viewthumb": viewthumb,
        "setcaption": setcaption,

        "viewcaption": viewcaption,
        "autorename": autorename,
        "rename": rename,
        "testrename": testrename,
        "clean": clean,
    }
    return MANIFEST, {name: guarded(name, handler) for name, handler in handlers.items()}
