"""Regenerate the existing UI preview using offline, explicit command fixtures.

Run from the repository root: python -m tools.render_ui_preview
No Telegram connections, provider calls or production storage are used.
"""
from html import unescape
from pathlib import Path
import re
from types import SimpleNamespace

from agent.ui.screens import welcome_screen, help_screen, help_lookup_screen, help_section_screen
from agent.ui.theme import Theme
from agent.utils.sender import to_safe_html

# Deliberately small: this is not a claim about a deployed registry's count.
COMMANDS = {'start', 'help', 'ping', 'plugins', 'ask', 'autochat', 'gu', 'get', 'custom_batch'}


def render_preview():
    user = SimpleNamespace(id=123, first_name='Gohan', last_name='', username='example')
    theme = Theme(custom_emoji={})
    screens = [('/start', welcome_screen(user, theme, active=COMMANDS)),
               ('/help', help_screen(user, theme, active=COMMANDS)),
               ('/help essentials', help_lookup_screen('essentials', user, theme, active=COMMANDS)),
               ('/help autochat', help_lookup_screen('autochat', user, theme, active=COMMANDS)),
               ('Warnings module (explicit feature fixture)',
                help_section_screen('Warnings', user, theme, active={'warn', 'warns', 'warnlimit', 'warntime'})),
               ('Blacklist module (explicit feature fixture)',
                help_lookup_screen('blacklist', user, theme, active={'blocklist', 'addblocklist', 'rmblocklist', 'blocklistmode', 'blocklistdelete'})),
               ('Welcome module (explicit feature fixture)',
                help_lookup_screen('greetings', user, theme, active={'setwelcome', 'welcome', 'goodbye'})),
               ('Federations module (explicit feature fixture)',
                help_lookup_screen('federations', user, theme, active={'newfed', 'myfeds', 'joinfed', 'chatfed'})),
               ('Encoder clone · /help encode (encode-only fixture)',
                help_lookup_screen('encode', user, Theme(custom_emoji={}, worker_plugins=('encoder',)), active={'encode'})),
               ('FileStore clone · /help genlink (archive-only fixture)',
                help_lookup_screen('genlink', user, Theme(custom_emoji={}, worker_plugins=('filestore',)), active={'genlink'}))]
    parts = ['# UI preview',
             'Offline render of the real screen builders with a deliberately small command fixture. '
             'This is not a Telegram screenshot, a live health check, or a deployment-wide command count. '
             'Actual screens use the live registered catalogue plus `/start`, `/help`, and `/ping`.',
             'Regenerate from the repository root with `.venv/bin/python -m tools.render_ui_preview`. '
             'The tool makes no network or storage calls. Native rich messages remain the primary UI; '
             'the text below is produced from the existing classic fallback renderer.',
             'Fixture commands: ' + ', '.join('`/' + command + '`' for command in sorted(COMMANDS)) + '.']
    for title, screen in screens:
        plain = unescape(re.sub(r'<[^>]+>', '', to_safe_html(screen.rich_text)))
        parts.extend(['## ' + title, '```text\n' + plain.strip() + '\n```'])
        if screen.keyboard:
            parts.append('Buttons (row order):\n' + '\n'.join('- ' + ' · '.join(button.text for button in row)
                         for row in screen.keyboard.inline_keyboard))
    parts.extend(['## Runtime behavior',
                  '- The Telegram menu is capped at 100 commands. Overflow prioritizes cross-feature entry points; Help retains the active catalogue. Registration does not prove group approval or health.',
                  '- Menu delivery follows the command scope and supported recipient-only group navigation; this offline render does not verify Telegram delivery. Group plugin controls retain Owner approval, admin activation and the three-optional-plugin limit; moderation is slot-free.',
                  '- AI requires a configured key and model. `/ask` sends an explicit question. `/autochat on|off|status` controls default-off private text replies or group mention/reply triggers. Group configuration requires an administrator. Only the triggering text is sent to the external provider, without chat history; charges may apply.',
                  '- FileStore clones use `/genlink`, `/batch`, and `/custom_batch`; the controller retains `/get`. Retired `/check` and vault commands `/fsave`, `/files`, and `/del` are not restored.',
                  '- Provider, music, FileStore transfer and control-panel actions are not exercised by this preview. Verify them separately; no online, latency or deployment claim is implied.'])
    return '\n'.join(line.rstrip() for line in '\n\n'.join(parts).splitlines()) + '\n'


if __name__ == '__main__':
    Path('docs/UI_PREVIEW.md').write_text(render_preview())
