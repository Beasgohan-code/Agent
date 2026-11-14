"""Post templates: the default layout, the substitution and its escaping.

The template is the group's own text and is trusted; the title and body are what
a member typed and are escaped. Reversing those two would turn a post into an
injection vector, which is why the substitution lives in one place.
"""

from __future__ import annotations

import html

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


def _post_text(template: str, title: str, body: str) -> str:
    """Render and wrap in the screen normaliser, so rich-only tags still work."""
    from ..utils.sender import to_safe_html

    return to_safe_html(render(template, title, body))
