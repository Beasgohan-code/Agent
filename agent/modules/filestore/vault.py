"""Media and quota helpers for the vault.

Nothing here touches Telegram state: these are the small conversions between a
replied message, a Telegram media object and the numbers a quota panel shows.
Keeping them apart from the handlers is what lets them be tested on their own.
"""

MAX_BOT_DOWNLOAD = 20 * 1024 * 1024


PAGE_SIZE = 10


def human_bytes(count: float) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if count < 1024 or unit == "GB":
            return f"{count:.0f} {unit}" if unit == "B" else f"{count:.1f} {unit}"
        count /= 1024
    return f"{count:.1f} GB"  # pragma: no cover - unreachable


def media_of(message):
    """The single media object a reply carries, if any."""
    replied = getattr(message, "reply_to_message", None)
    if replied is None:
        return None
    for attribute in ("document", "video", "audio", "voice", "animation", "photo"):
        media = getattr(replied, attribute, None)
        if media is not None:
            return replied, media
    return None


def media_size(media) -> int:
    size = getattr(media, "file_size", None)
    if size:
        return int(size)
    # Photos arrive as a list of sizes; the last one is the largest.
    if isinstance(media, list) and media:
        return int(getattr(media[-1], "file_size", 0) or 0)
    return 0


def media_name(media) -> str:
    name = getattr(media, "file_name", None)
    if name:
        return name
    if isinstance(media, list):
        return "photo.jpg"
    kind = getattr(media, "mime_type", None) or "file"
    return str(kind).replace("/", ".")


def _args(message) -> list[str]:
    return (getattr(message, "text", "") or "").split()
