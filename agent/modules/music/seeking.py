"""Original bounded seek syntax shared by native music controls.

Functional references: Videl0 seek and Playeon seek workflows. No upstream code
is copied. Native VC seeking is distinct from Playeon's browser-room seeking.
"""
import re

USAGE = 'Use /seek <seconds|m:ss|h:mm:ss> or /seek +30s|-5m; /fw <duration>, /bw <duration>, /seekback <duration>. Units: s, m, h. Range: 0–86400 seconds.'


def seek_target(value: str, elapsed: float) -> int:
    if len(value) > 16 or not value.isascii():
        raise ValueError(USAGE)
    duration = re.fullmatch(r'([+-]?)([0-9]{1,5})([smh]?)', value)
    if duration:
        sign, amount, unit = duration.groups()
        seconds = int(amount) * {'': 1, 's': 1, 'm': 60, 'h': 3600}[unit]
        target = int(elapsed) + (-seconds if sign == '-' else seconds) if sign else seconds
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


def control_target(command: str, value: str, elapsed: float) -> int:
    if command == 'seek':
        return seek_target(value, elapsed)
    if command not in ('fw', 'bw', 'seekback') or not re.fullmatch(r'[0-9]{1,5}[smh]?', value):
        raise ValueError(USAGE)
    amount = seek_target(value, 0)
    if amount == 0:
        raise ValueError('Choose a positive duration.')
    return seek_target(('+' if command == 'fw' else '-') + str(amount), elapsed)
