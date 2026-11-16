"""Offline profile-link cards. Never claim a remote account was looked up."""
import re
from pyrogram.enums import ButtonStyle
from pyrogram.types import InlineKeyboardMarkup
from ...platform.commands import command_name
from ...ui.tables import panel, kv_table
from ...utils.rich import reply

# Deliberately ASCII-only: international handles are not normalized or guessed.
PROFILES = {
    'tiktok': ('TikTok', r'[A-Za-z0-9_][A-Za-z0-9_.]{0,22}[A-Za-z0-9_]', 'https://www.tiktok.com/@{}'),
    'x': ('X', r'[A-Za-z0-9_]{1,15}', 'https://x.com/{}'),
    'yt': ('YouTube', r'[A-Za-z0-9_][A-Za-z0-9_.-]{1,28}[A-Za-z0-9_]', 'https://www.youtube.com/@{}'),
    'ig': ('Instagram', r'[A-Za-z0-9_](?:[A-Za-z0-9_.]{0,28}[A-Za-z0-9_])?', 'https://www.instagram.com/{}/'),
}


def build(ctx):
    async def profile(client, message):
        text = getattr(message, 'text', '') or ''
        command = command_name(text)
        if command not in PROFILES:
            await reply(message, 'Use /tiktok, /x, /yt or /ig followed by one handle.')
            return
        title, pattern, template = PROFILES[command]
        args = text.split()[1:]
        handle = args[0].removeprefix('@') if len(args) == 1 else ''
        if not re.fullmatch(pattern, handle, flags=re.ASCII) or '..' in handle:
            await reply(message, f'Usage: <code>/{command} @handle</code> — one ASCII handle, not a URL. '
                        'Only letters, digits and this platform’s supported separators; no spaces or query strings.')
            return
        url = template.format(handle)
        await reply(message, panel(f'{title} profile link', icon=ctx.theme.emoji('globe'),
            table=kv_table([('Platform', title), ('Handle', '@' + handle)]),
            lines=[f'<code>{url}</code>'],
            note='Account existence and ownership are not verified. No live profile lookup, biography or follower statistics were fetched. '
                 'Opening this link visits an external platform.'),
            reply_markup=InlineKeyboardMarkup([
                [ctx.theme.button('Open profile', icon='globe', url=url, style=ButtonStyle.PRIMARY)],
                [ctx.theme.button('Copy profile link', icon='copy', copy_text=url)],
            ]))
    return {name: profile for name in PROFILES}
