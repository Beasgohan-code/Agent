"""Bounded output-name option for Leech, never shell arguments."""
import shlex


def parse_request(text):
    try:
        parts = shlex.split(text)
    except ValueError:
        raise ValueError('Unclosed quote in transfer request.') from None
    args = parts[1:]
    if len(args) == 1:
        return args[0], None
    if len(args) != 3 or args[1] != '-n':
        raise ValueError('Supply one public URL, optionally followed by -n "output name.ext".')
    name = args[2]
    if (not name.strip() or len(name) > 120 or name in ('.', '..')
            or any(ch in name for ch in '/\\')
            or any(ord(ch) < 32 or ord(ch) == 127 for ch in name)):
        raise ValueError('Output name must be 1–120 characters with no paths or control characters.')
    return args[0], name.strip()
