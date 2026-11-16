"""Focused worker front doors. Presentation only, never an authorization source."""
import re

from pyrogram.types import InlineKeyboardButton as Button, InlineKeyboardMarkup as Keyboard
from pyrogram.enums import ButtonStyle

from ..platform.policy import GROUP_CORE
from .keyboards import CB_HOME, CB_HELP
from .tables import Table, markup, panel

# Reviewed native icons only: no arbitrary document IDs or upstream execution.
PROFILES = {
    'filestore': ('FileStore', 'lock', 'Open file links issued by this bot. Archive-backed file access keeps its existing verification and permission checks.'),
    'encoder': ('Encoder', 'gear', 'Reply to a video or document, choose an encoding preset, then inspect, compress or extract audio. Each job can be cancelled.'),
    'moderation': ('Group Management', 'shield', 'Add this bot to your group and grant only the administrator rights its protection actions need. Group settings remain admin-only.'),
    'postmaker': ('Post maker', 'sparkles', 'Prepare posts using this worker’s registered publishing tools. Publishing and configuration retain their existing permission checks.'),
    'linkshare': ('Linkshare', 'link', 'Create and manage links with this bot. File access and revocation remain checked by the link service.'),
    'leech': ('Leech', 'link', 'Download a supported public link, or manage your personal upload caption and thumbnail. Private-network targets remain blocked.'),
    'music': ('Music', 'music', 'Use the configured assistant in a group call. Native URL, YouTube and search playback are disabled pending safe fetching; supported downloaded local media only.'),
    'ai_agent': ('AI Agent', 'bot', 'Ask a question using this worker’s configured provider. Private autochat is opt-in; group replies follow the existing mention/reply policy.'),
    'renamer': ('Renamer', 'gear', 'Reply to media to rename it and manage supported filename, caption and thumbnail options.'),
    'utilities': ('Utilities', 'info', 'Inspect the registered identity, time and information tools for this worker.'),
}
PAGE_SIZE = 8


def selected(theme):
    requested = getattr(theme, 'worker_plugins', None)
    if requested is None:
        return None
    return tuple(dict.fromkeys(slug for slug in requested if slug in PROFILES and slug not in GROUP_CORE))


def commands(slug, active):
    from ..modules import MODULES
    manifests = {module.MANIFEST.slug: module.MANIFEST for module in MODULES}
    slugs = GROUP_CORE if slug == 'moderation' else (slug,)
    candidates = tuple(dict.fromkeys(command for key in slugs if key in manifests for command in manifests[key].commands))
    # Unknown registry state is not evidence that optional commands are loaded.
    return tuple(command for command in candidates if active is not None and command in active)


def allowed(theme, slug):
    configured = selected(theme)
    return configured is not None and (slug in configured or slug == 'moderation')


def button(theme, slug, *, page=0):
    from .theme import strip_custom_emoji
    title, icon, _ = PROFILES[slug]
    return Button(f'{strip_custom_emoji(theme.emoji(icon))} {title}',
                  callback_data=f'worker:{slug}:{page}',
                  icon_custom_emoji_id=theme.emoji_id(icon), style=ButtonStyle.PRIMARY)


def overview(user, theme, *, active=None, help_mode=False):
    from .screens import Screen, display_name
    from richgram import rich_esc
    configured = selected(theme)
    primary = configured or ('moderation',)
    identity = PROFILES[primary[0]][0] if len(primary) == 1 else 'Multi-plugin'
    icon = PROFILES[primary[0]][1] if len(primary) == 1 else 'bot'
    title = f'Meiko · {identity} worker' + (' · Help' if help_mode else '')
    visible = [slug for slug in (*primary, 'moderation') if allowed(theme, slug) and commands(slug, active)]
    visible = list(dict.fromkeys(visible))
    rows = []
    for slug in visible:
        name, accent, _ = PROFILES[slug]
        examples = ' · '.join('/' + command for command in commands(slug, active)[:3])
        rows.append((markup(f'{theme.emoji(accent)} {rich_esc(name)}'), examples))
    lines = [f'Hello, <b>{rich_esc(display_name(user) or "there")}</b>. This bot has a focused worker interface.']
    lines.extend(PROFILES[slug][2] for slug in primary)
    if not visible:
        lines.append('No worker tools are currently registered. Ask this bot’s owner to check its configuration.')
    body = panel(title, icon=theme.emoji(icon), table=Table(headers=('Tools', 'Try'), rows=tuple(rows)),
                 lines=lines, note='Buttons open instructions, not privileged actions. Registered does not mean activated in a group; optional plugins still need Owner approval and group-admin activation.',
                 footer='Meiko worker · /help <command> · Prefixes / ! . ? · Group protection stays available and slot-free.')
    keys = [[button(theme, slug)] for slug in visible]
    keys.append([Button('⌂ Worker home', callback_data=CB_HOME), Button('Help & options', callback_data=CB_HELP)])
    return Screen(body, Keyboard(keys))


def plugin_screen(user, theme, slug, *, active=None, page=0):
    from .screens import Screen
    from ..platform.menu import DESCRIPTIONS
    if slug not in PROFILES or not allowed(theme, slug):
        return None
    available = commands(slug, active)
    if not available:
        return None
    pages = (len(available) + PAGE_SIZE - 1) // PAGE_SIZE
    if not 0 <= page < pages:
        return None
    title, icon, introduction = PROFILES[slug]
    rows = tuple((markup(f'<code>/{command}</code>'), DESCRIPTIONS.get(command, 'Open this command for its current usage and permission checks.'))
                 for command in available[page * PAGE_SIZE:(page + 1) * PAGE_SIZE])
    body = panel(f'Meiko · {title} worker · Options', icon=theme.emoji(icon),
                 table=Table(headers=('Command', 'Usage'), rows=rows), lines=[introduction],
                 note='Only commands registered in this worker are listed. Each command rechecks its own permissions; viewing this page grants no access.',
                 footer=f'Page {page + 1} of {pages} · /help <command> · Prefixes / ! . ?')
    navigation = []
    if page:
        navigation.append(Button('‹ Previous', callback_data=f'worker:{slug}:{page - 1}'))
    if page + 1 < pages:
        navigation.append(Button('Next ›', callback_data=f'worker:{slug}:{page + 1}'))
    keys = ([navigation] if navigation else []) + [[Button('All worker tools', callback_data=CB_HELP), Button('⌂ Home', callback_data=CB_HOME)]]
    return Screen(body, Keyboard(keys))


def callback(data, user, theme, *, active=None):
    match = re.fullmatch(r'worker:([a-z_]{1,32}):([0-9]{1,3})', data)
    if not match:
        return None
    return plugin_screen(user, theme, match[1], active=active, page=int(match[2]))
