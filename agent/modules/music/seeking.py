"""Original bounded seek syntax shared by native music controls.

Functional references: Videl0 seek and Playeon seek workflows. No upstream code
is copied. Native VC seeking is distinct from Playeon's browser-room seeking.
"""
import re

USAGE = 'Use /seek <seconds|m:ss|h:mm:ss> or /seek +30s|-30s. Range: 0–86400 seconds.'


def seek_target(value: str, elapsed: float) -> int:
    if len(value) > 16 or not value.isascii():
        raise ValueError(USAGE)
    if re.fullmatch(r'[+-][0-9]{1,5}s?', value):
        target = int(elapsed) + int(value.rstrip('s'))
    elif re.fullmatch(r'[0-9]{1,5}', value):
        target = int(value)
    elif re.fullmatch(r'[0-9]{1,2}:[0-9]{2}(?::[0-9]{2})?', value):
        parts = [int(part) for part in value.split(':')]
        if any(part >= 60 for part in parts[1:]):
            raise ValueError(USAGE)
        target = 0
        for part in parts:
            target = target * 60 + part
    else:
        raise ValueError(USAGE)
    if not 0 <= target <= 86400:
        raise ValueError(USAGE)
    return target
