"""Bounded output-name option for Leech, never shell arguments."""

import shlex


def parse_request(text):
    try:
        parts = shlex.split(text)
    except ValueError:
        raise ValueError("Unclosed quote in transfer request.") from None
    args = parts[1:]
    if len(args) == 1:
        return args[0], None
    if len(args) != 3 or args[1] != "-n":
        raise ValueError(
            'Supply one public URL, optionally followed by -n "output name.ext".'
        )
    name = args[2]
    if (
        not name.strip()
        or len(name) > 120
        or name in (".", "..")
        or any(ch in name for ch in "/\\")
        or any(ord(ch) < 32 or ord(ch) == 127 for ch in name)
    ):
        raise ValueError(
            "Output name must be 1–120 characters with no paths or control characters."
        )
    return args[0], name.strip()


def parse_message(message):
    """CBML-style replied URL input, using the same bounded option parser."""
    text = getattr(message, "text", None) or getattr(message, "caption", None) or ""
    try:
        parts = shlex.split(text)
    except ValueError:
        raise ValueError("Unclosed quote in transfer request.") from None
    if not parts:
        raise ValueError("Supply a transfer command and one public URL.")
    args = parts[1:]
    if not args or (len(args) == 2 and args[0] == "-n"):
        replied = getattr(message, "reply_to_message", None)
        source = (
            getattr(replied, "text", None) or getattr(replied, "caption", None) or ""
        ).strip()
        if not source or any(char.isspace() for char in source):
            raise ValueError(
                "Reply to one public HTTP(S) URL, or supply it after the command."
            )
        return parse_request(shlex.join([parts[0], source, *args]))
    return parse_request(text)
