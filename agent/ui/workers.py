"""Focused worker front doors. Presentation only, never an authorization source."""
import re

from pyrogram.types import InlineKeyboardButton as Button, InlineKeyboardMarkup as Keyboard
from pyrogram.enums import ButtonStyle

from ..platform.policy import GROUP_CORE
from .keyboards import CB_HOME, CB_HELP
from .tables import Table, markup, panel

# Reviewed native icons only: no arbitrary document IDs or upstream execution.
PROFILES = {
    'filestore': ('FileStore', 'lock', 'Your files, one link away. Open a file link from this bot to receive its contents here. Complete any access verification shown before delivery.'),
    'encoder': ('Encoder', 'gear', 'A compact studio for your videos. Reply to a video or document to encode, compress, inspect or extract audio. You can cancel your own jobs.'),
    'moderation': ('Group Management', 'shield', 'Keep your community organised and protected. Add this bot as an administrator, then choose your group’s rules with /settings. Only grant the rights you need.'),
    'postmaker': ('Post maker', 'sparkles', 'Turn a message into a prepared post. Use the publishing tools below; destination and administrator permissions are checked before posting.'),
    'linkshare': ('Linkshare', 'link', 'Share files with links you can manage. Create a link, review your links and revoke access when it is no longer needed.'),
    'leech': ('Leech', 'link', 'Bring a public download into Telegram. Send a supported public file link, then personalise uploads with your own caption and thumbnail. Private-network addresses are blocked.'),
    'music': ('Music', 'music', 'Music controls for your group call. A configured assistant and active group plugin are required. Remote URL, YouTube and search playback remain disabled; supported downloaded local media only.'),
    'ai_agent': ('AI Agent', 'bot', 'A place for your questions. Use /ask to talk to the configured AI provider. Private auto-chat is opt-in; group replies require a mention or reply to this bot. Never send secrets.'),
    'renamer': ('Renamer', 'gear', 'Give your files a fresh name. Reply to supported media, choose a filename and manage your caption or thumbnail preferences.'),
    'utilities': ('Utilities', 'info', 'Useful details, without the clutter. Find the identity, time and information commands available in this bot below.'),
}

# Prefer useful first actions over manifest ordering (which may start with aliases).
QUICK_START = {
    'filestore': ('get', 'batch', 'check'),
    'encoder': ('encode', 'compress', 'mediainfo'),
    'moderation': ('settings', 'setwelcome', 'warn'),
    'postmaker': ('post',),
    'linkshare': ('genlink', 'links', 'revoke'),
    'leech': ('leech', 'mirror', 'set_caption'),
    'music': ('play', 'queue', 'stop'),
    'ai_agent': ('ask', 'autochat'),
    'renamer': ('rename', 'autorename', 'testrename'),
    'utilities': ('id', 'info', 'time'),
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
    title = f'{identity}' + (' · Help' if help_mode else '')
    visible = [slug for slug in (*primary, 'moderation') if allowed(theme, slug) and commands(slug, active)]
    visible = list(dict.fromkeys(visible))
    rows = []
    for slug in visible:
        name, accent, _ = PROFILES[slug]
        available = commands(slug, active)
        preferred = [command for command in QUICK_START[slug] if command in available]
        examples = ' · '.join('/' + command for command in (preferred or available[:3]))
        rows.append((markup(f'{theme.emoji(accent)} {rich_esc(name)}'), examples))
    lines = [f'Welcome, <b>{rich_esc(display_name(user) or "there")}</b>.']
    lines.extend(PROFILES[slug][2] for slug in primary)
    if not visible:
        lines.append('No tools are currently available. Ask this bot’s owner to check its configuration.')
    body = panel(title, icon=theme.emoji(icon), table=Table(headers=('Tools', 'Try'), rows=tuple(rows)),
                 lines=lines, note='Choose a tool below for instructions.' if not help_mode else 'Group actions require administrator permissions. Optional tools require owner approval and group activation.',
                 footer='/help command · More detail for any available command')
    keys = [[button(theme, slug)] for slug in visible]
    keys.append([Button('How to use', callback_data=CB_HELP, style=ButtonStyle.PRIMARY), Button('About', callback_data='worker:about')])
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
    body = panel(f'{title} · Commands', icon=theme.emoji(icon),
                 table=Table(headers=('Command', 'Usage'), rows=rows), lines=[introduction],
                 note='Only commands registered in this worker are listed. Each command rechecks its own permissions; viewing this page grants no access.',
                 footer=f'Page {page + 1} of {pages} · /help <command> · Prefixes / ! . ?')
    navigation = []
    if page:
        navigation.append(Button('‹ Previous', callback_data=f'worker:{slug}:{page - 1}'))
    if page + 1 < pages:
        navigation.append(Button('Next ›', callback_data=f'worker:{slug}:{page + 1}'))
    keys = ([navigation] if navigation else []) + [[Button('All tools', callback_data=CB_HELP), Button('⌂ Home', callback_data=CB_HOME)]]
    return Screen(body, Keyboard(keys))


def callback(data, user, theme, *, active=None):
    if data == 'worker:about':
        return about_screen(user, theme, active=active) if theme.worker_plugins is not None else None
    match = re.fullmatch(r'worker:([a-z_]{1,32}):([0-9]{1,3})', data)
    if not match:
        return None
    return plugin_screen(user, theme, match[1], active=active, page=int(match[2]))


def about_screen(user, theme, *, active=None):
    """Worker-owned About panel, without controller promotion or infrastructure details."""
    from .screens import Screen
    configured = selected(theme) or ('moderation',)
    identity = PROFILES[configured[0]][0] if len(configured) == 1 else 'Multi-plugin'
    rows = tuple((PROFILES[slug][0], str(len(commands(slug, active))))
                 for slug in dict.fromkeys((*configured, 'moderation')) if commands(slug, active))
    body = panel(f'About · {identity}', icon=theme.emoji('info'),
                 lines=[PROFILES[slug][2] for slug in configured],
                 table=Table(headers=('Available tools', 'Commands'), rows=rows),
                 note='Availability depends on this bot’s configuration. Private data and administrator actions remain permission-protected.',
                 footer='Open Help for usage and available commands.')
    return Screen(body, Keyboard([[Button('Home', callback_data=CB_HOME), Button('Help', callback_data=CB_HELP)]]))


def lookup(argument, user, theme, *, active=None):
    """Resolve only this bot's tools; never fall through to controller categories."""
    from .screens import Screen
    from ..platform.menu import DESCRIPTIONS
    query = (argument or '').strip().lstrip('/!.?').lower()[:64]
    slug = next((key for key, (name, _, _) in PROFILES.items() if query in (key, name.lower())), None)
    if slug:
        screen = plugin_screen(user, theme, slug, active=active)
        if screen is not None:
            return screen
    if not query or active is None or query not in active or query not in DESCRIPTIONS:
        return overview(user, theme, active=active, help_mode=True)
    body = panel('Command help', icon=theme.emoji('help'),
                 table=Table(headers=('Command', 'Usage'), rows=((markup(f'<code>/{query}</code>'), DESCRIPTIONS[query]),)),
                 note='Each action checks the permissions it needs.', footer='Use /help to explore all available tools.')
    return Screen(body, Keyboard([[Button('All tools', callback_data=CB_HELP), Button('Home', callback_data=CB_HOME)]]))


def profile_screen(user, theme, *, active=None):
    from .screens import Screen, display_name
    body = panel('Your profile', icon=theme.emoji('info'),
                 table=Table(headers=('Detail', 'Value'), rows=(
                     ('Name', display_name(user) or 'Not provided'),
                     ('Telegram ID', str(getattr(user, 'id', None) or 'Not provided')),
                     ('Language', getattr(user, 'language_code', None) or 'Not provided'),
                 )),
                 note='These details come from your Telegram profile, not a paid plan.',
                 footer='Personal settings and access are managed by this bot.')
    return Screen(body, Keyboard([[Button('Home', callback_data=CB_HOME), Button('Help', callback_data=CB_HELP)]]))
