"""Focused worker front doors. Presentation only, never an authorization source."""
import base64
import re
import difflib

from pyrogram.types import InlineKeyboardMarkup as Keyboard
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
# Read-only onboarding: copying a command never executes a privileged action.
WORKFLOWS = {
    'filestore': ('Open a file link issued by this bot in private chat.', 'Complete any verification shown before delivery.', 'Use the available file commands below for usage and access checks.'),
    'encoder': ('Send a supported video or document.', 'Reply to that media with an encoding command; open /help encode for options.', 'Watch the job result. Use /cancel to stop your own active job.'),
    'moderation': ('Add this bot to your group with only the administrator rights you need.', 'Open /settings in the group to choose rules, greetings and protection.', 'Review your settings before using moderation actions on members.'),
    'postmaker': ('Prepare the text or media you want to publish.', 'Open /help post for the supported composition format.', 'Check the content and destination before publishing. Permissions still apply.'),
    'linkshare': ('Choose a file you own, or reply to supported media.', 'Open /help genlink to choose expiry and use limits.', 'Share the issued link privately. Revocation cannot erase copies already delivered.'),
    'leech': ('Choose a supported public file URL; do not include secrets.', 'Send /leech followed by the URL, or reply to one URL with /leech.', 'Receive the file here. Use /cancel to stop your own active transfer.'),
    'music': ('Ask the Owner to configure this bot’s own assistant.', 'An admin must activate the approved Music plugin for the group.', 'Use only supported downloaded local media. Remote URL, YouTube and search playback remain disabled.'),
    'ai_agent': ('Write a question without credentials or private secrets.', 'Send /ask followed by your question. Only that message goes to the configured provider.', 'Verify important answers. Auto-chat is opt-in; the assistant cannot perform Telegram actions.'),
    'renamer': ('Send supported media to this bot.', 'Reply with the rename command; open /help rename for its syntax.', 'Check the resulting filename. Manage caption and thumbnail preferences with the installed tools.'),
    'utilities': ('Choose the detail you need from the commands below.', 'Copy a command and send it in this chat.', 'Use /help command to check usage. Private and administrator-only actions stay restricted.'),
}
PAGE_SIZE = 8


def selected(theme):
    requested = getattr(theme, 'worker_plugins', None)
    if requested is None:
        return None
    if tuple(requested) == ('*',):
        from ..modules import MODULES
        compatible = {module.MANIFEST.slug for module in MODULES if module.MANIFEST.clone_compatible}
        return tuple(slug for slug in PROFILES if slug in compatible and slug not in GROUP_CORE)
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
    title, icon, _ = PROFILES[slug]
    return theme.button(title, icon=icon, callback_data=f'worker:{slug}:{page}',
                        style=ButtonStyle.PRIMARY)


def navigation(theme):
    return [theme.button('Home', icon='bot', callback_data=CB_HOME),
            theme.button('All tools', icon='search', callback_data=CB_HELP, style=ButtonStyle.PRIMARY)]


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
    for slug in dict.fromkeys((*primary, 'moderation')):
        name, accent, _ = PROFILES[slug]
        available = commands(slug, active)
        preferred = [command for command in QUICK_START[slug] if command in available]
        examples = (' · '.join('/' + command for command in (preferred or available[:3]))
                    if available else 'Unknown' if active is None else 'Not registered')
        rows.append((markup(f'{theme.emoji(accent)} {rich_esc(name)}'), examples))
    lines = [f'{theme.emoji("wave")} Welcome, <b>{rich_esc(display_name(user) or "there")}</b>.']
    if len(primary) == 1:
        lines.append(PROFILES[primary[0]][2])
    else:
        lines.append('Choose a workspace below. Each tool has its own getting-started guide and command list.')
    if not visible:
        lines.append('Command registration is unknown. Open Availability and refresh.' if active is None else
                     'No tools are currently registered. Ask this bot’s owner to check its configuration.')
    shortcuts = []
    if not help_mode:
        preferred = [[cmd for cmd in QUICK_START[slug] if cmd in commands(slug, active)] for slug in primary]
        # One first action per selected workspace before a second from one tool.
        for position in range(3):
            for choices in preferred:
                if position < len(choices) and choices[position] not in shortcuts:
                    shortcuts.append(choices[position])
        shortcuts = shortcuts[:2]
        if shortcuts:
            lines.append('Copying does not run a command. Add required arguments and send it yourself; normal access checks still apply.')
    body = panel(title, icon=theme.emoji(icon), subtitle='Explore your tools' if help_mode else 'Quick start', table=Table(headers=('Tools', 'Try'), rows=tuple(rows)),
                 lines=lines, note='Choose a tool below for instructions.' if not help_mode else 'Group actions require administrator permissions. Optional tools require owner approval and group activation.',
                 footer='/help command · More detail for any available command')
    keys = [[button(theme, slug)] for slug in visible]
    if visible and not help_mode:
        keys.insert(0, [theme.button('Get started', icon='bolt', callback_data=f'worker:guide:{visible[0]}', style=ButtonStyle.PRIMARY)])
    if shortcuts:
        keys.insert(1, [theme.button('Copy /' + cmd, icon='pin', copy_text='/' + cmd) for cmd in shortcuts])
    keys.append([theme.button('Availability', icon='stats', callback_data='worker:availability')])
    keys.append([theme.button('How to use', icon='question', callback_data=CB_HELP, style=ButtonStyle.PRIMARY), theme.button('About', icon='info', callback_data='worker:about')])
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
                 note='Choose a command from this page. Administrator actions still require the appropriate permissions.',
                 footer=f'Page {page + 1} of {pages} · {len(available)} commands · /help command')
    paging = []
    if page:
        paging.append(theme.button('Previous', icon='back', callback_data=f'worker:{slug}:{page - 1}'))
    if page + 1 < pages:
        paging.append(theme.button('Next', icon='arrow', callback_data=f'worker:{slug}:{page + 1}', style=ButtonStyle.PRIMARY))
    detail_buttons = [theme.button(f'/{name}', icon='question', callback_data=f'worker:cmd:{name}')
                      for name in available[page * PAGE_SIZE:(page + 1) * PAGE_SIZE]]
    details = [detail_buttons[index:index + 2] for index in range(0, len(detail_buttons), 2)]
    keys = details + ([paging] if paging else []) + [[theme.button('Get started', icon='bolt', callback_data=f'worker:guide:{slug}', style=ButtonStyle.PRIMARY)]] + [navigation(theme)]
    return Screen(body, Keyboard(keys))


def callback(data, user, theme, *, active=None):
    search = re.fullmatch(r'worker:find:([0-9]{1,4}):([A-Za-z0-9_-]{1,32})', data)
    if search:
        try:
            encoded = search[2]
            query = base64.b64decode(encoded + '=' * (-len(encoded) % 4), altchars=b'-_', validate=True).decode('utf-8')
            if not query or len(query.encode()) > 24 or any(ord(c) < 32 for c in query):
                return None
            if base64.urlsafe_b64encode(query.encode()).decode().rstrip('=') != encoded:
                return None
        except (ValueError, UnicodeError):
            return None
        return search_screen(user, theme, query, active=active, page=int(search[1]))
    if data == 'worker:availability':
        return availability_screen(user, theme, active=active) if selected(theme) is not None else None
    command = re.fullmatch(r'worker:cmd:([a-z][a-z0-9_]{0,31})', data)
    if command:
        return command_screen(user, theme, command[1], active=active)
    guide = re.fullmatch(r'worker:guide:([a-z_]{1,32})', data)
    if guide:
        return guide_screen(user, theme, guide[1], active=active)
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
    rows = tuple((markup(f'{theme.emoji(PROFILES[slug][1])} {PROFILES[slug][0]}'), str(len(commands(slug, active))))
                 for slug in dict.fromkeys((*configured, 'moderation')) if commands(slug, active))
    body = panel(f'About · {identity}', icon=theme.emoji('info'), subtitle='Purpose & available tools',
                 lines=[PROFILES[slug][2] for slug in configured],
                 table=Table(headers=('Tools', 'Commands'), rows=rows),
                 note='Availability depends on this bot’s configuration. Private data and administrator actions remain permission-protected.',
                 footer='Open Help for usage and available commands.')
    return Screen(body, Keyboard([navigation(theme)]))


def lookup(argument, user, theme, *, active=None):
    """Resolve only this bot's tools; never fall through to controller categories."""
    query = (argument or '').strip().lstrip('/!.?').lower()[:64]
    slug = next((key for key, (name, _, _) in PROFILES.items() if query in (key, name.lower())), None)
    if slug:
        screen = plugin_screen(user, theme, slug, active=active)
        if screen is not None:
            return screen
    direct = command_screen(user, theme, query, active=active)
    if direct is not None:
        return direct
    return search_screen(user, theme, query, active=active)


def search_screen(user, theme, query, *, active=None, page=0):
    from .screens import Screen
    from ..platform.menu import DESCRIPTIONS
    query = query.casefold()
    if selected(theme) is None:
        return None
    if (not query or len(query.encode('utf-8')) > 24 or any(ord(c) < 32 for c in query)):
        if page:
            return None
        return Screen(panel('Find a command', icon=theme.emoji('search'),
            lines=['Search with /help followed by 1–24 UTF-8 bytes without control characters.'],
            note='Exact command and tool names can still be opened directly.'), Keyboard([navigation(theme)]))
    candidates = sorted(name for name in discoverable(theme, active) if name in DESCRIPTIONS)
    matches = sorted((name for name in candidates if query in name or query in DESCRIPTIONS[name].casefold()),
                     key=lambda name: (0 if name.startswith(query) else 1 if query in name else 2, name)) if len(query) >= 3 else []
    fuzzy = False
    if not matches and len(query) >= 3:
        matches = difflib.get_close_matches(query, candidates, n=6, cutoff=0.7)
        fuzzy = bool(matches)
    pages = max(1, (len(matches) + 5) // 6)
    if not 0 <= page < pages:
        return None
    current = matches[page * 6:(page + 1) * 6]
    from richgram import rich_esc
    body = panel('Find a command', icon=theme.emoji('search'),
                 subtitle=f'Results for {rich_esc(query)}',
                 table=Table(headers=('Command', 'What it does'), rows=tuple(
                     (markup(f'<code>/{name}</code>'), DESCRIPTIONS[name]) for name in current)) if current else None,
                 lines=[] if current else ['No matching commands in this bot’s selected, registered tools. Try another /help query.'],
                 note='Similar spelling suggestions; not exact matches.' if fuzzy else 'Command name matches first, then description matches. Tap for details; search does not execute actions.',
                 footer=f'Page {page+1} / {pages} · {len(matches)} matches · selected, registered commands only')
    buttons = [theme.button(f'/{name}', icon='question', callback_data=f'worker:cmd:{name}') for name in current]
    keys = [buttons[index:index + 2] for index in range(0, len(buttons), 2)]
    encoded = base64.urlsafe_b64encode(query.encode()).decode().rstrip('=')
    paging = []
    if page:
        paging.append(theme.button('Previous', icon='back', callback_data=f'worker:find:{page-1}:{encoded}'))
    if page + 1 < pages:
        paging.append(theme.button('Next', icon='arrow', callback_data=f'worker:find:{page+1}:{encoded}'))
    if paging:
        keys.append(paging)
    return Screen(body, Keyboard(keys + [navigation(theme)]))


def discoverable(theme, active):
    """Intersection of live registry and this worker's feature/navigation boundary."""
    configured = selected(theme)
    if configured is None or active is None:
        return set()
    candidates = {'start', 'help', 'menu', 'about', 'ping'}
    for slug in (*configured, 'moderation'):
        candidates.update(commands(slug, active))
    if configured:
        candidates.update(('plugin', 'plugins'))
    if set(configured) & {'encoder', 'leech', 'renamer'}:
        candidates.update(('jobs', 'cancel'))
    return candidates & set(active)


def command_screen(user, theme, name, *, active=None):
    from .screens import Screen
    from ..platform.menu import DESCRIPTIONS
    if name not in discoverable(theme, active) or name not in DESCRIPTIONS:
        return None
    configured = selected(theme) or ()
    owner = next((slug for slug in (*configured, 'moderation') if name in commands(slug, active)), None)
    from ..modules import MODULES
    slugs = GROUP_CORE if owner == 'moderation' else (owner,) if owner else ()
    manifest = next((module.MANIFEST for module in MODULES
                     if module.MANIFEST.slug in slugs and name in module.MANIFEST.commands), None)
    rows = [(markup(f'<code>/{name}</code>'), DESCRIPTIONS[name])]
    if manifest is not None:
        rows.extend([('Tool', PROFILES[owner][0]), ('Chat scope', manifest.scope),
                     ('Permissions', ', '.join(manifest.permissions) or 'None declared'),
                     ('Dependencies', ', '.join(manifest.dependencies) or 'None declared'),
                     ('Required credential names', ', '.join(manifest.required_credentials) or 'None declared'),
                     ('Required capabilities', ', '.join(manifest.required_capabilities) or 'None declared')])
    else:
        rows.append(('Tool', 'Built-in navigation · no feature requirements declared here'))
    body = panel(f'/{name}', icon=theme.emoji(PROFILES[owner][1] if owner else 'question'),
                 subtitle='Command details',
                 table=Table(headers=('Detail', 'Information'), rows=tuple(rows)),
                 note='Declared requirements are not a readiness check or access grant. Group tools may require Owner approval, admin activation and Telegram rights. Copying does not run this command; add required arguments before sending.',
                 footer='Send the command for its current usage. Never include passwords or secret tokens.')
    keys = [[theme.button(f'Copy /{name}', icon='pin', copy_text=f'/{name}', style=ButtonStyle.PRIMARY)]]
    if owner:
        page = commands(owner, active).index(name) // PAGE_SIZE
        keys.append([theme.button('Back to commands', icon='back', callback_data=f'worker:{owner}:{page}'),
                     theme.button('Get started', icon='bolt', callback_data=f'worker:guide:{owner}')])
    keys.append(navigation(theme))
    return Screen(body, Keyboard(keys))


def profile_screen(user, theme, *, active=None):
    from .screens import Screen, display_name
    body = panel('Your profile', icon=theme.emoji('info'), subtitle='Your Telegram details',
                 table=Table(headers=('Detail', 'Value'), rows=(
                     ('Name', display_name(user) or 'Not provided'),
                     ('Telegram ID', str(getattr(user, 'id', None) or 'Not provided')),
                     ('Language', getattr(user, 'language_code', None) or 'Not provided'),
                 )),
                 note='These details come from your Telegram profile, not a paid plan.',
                 footer='Personal settings and access are managed by this bot.')
    return Screen(body, Keyboard([navigation(theme)]))


def guide_screen(user, theme, slug, *, active=None):
    """A live-selected, read-only workflow with safe copy-command shortcuts."""
    from .screens import Screen
    if slug not in PROFILES or not allowed(theme, slug):
        return None
    available = commands(slug, active)
    if not available:
        return None
    title, icon, _ = PROFILES[slug]
    steps = WORKFLOWS[slug]
    rows = tuple((markup(f'{theme.emoji(number)} Step {index}'), text)
                 for index, (number, text) in enumerate(zip(('one', 'two', 'three'), steps), 1))
    shortcuts = [command for command in QUICK_START[slug] if command in available]
    body = panel(f'{title} · Get started', icon=theme.emoji(icon), subtitle='A simple path from start to result',
                 table=Table(headers=('Step', 'What to do'), rows=rows),
                 note='Copy buttons only put a command on your clipboard. Send it yourself when ready; access checks still apply.',
                 footer='Need exact syntax? Send /help followed by a command name.')
    buttons = [theme.button(f'Copy /{command}', icon='pin', copy_text=f'/{command}') for command in shortcuts]
    keys = [buttons[index:index + 2] for index in range(0, len(buttons), 2)]
    keys.append([theme.button('Browse commands', icon='search', callback_data=f'worker:{slug}:0', style=ButtonStyle.PRIMARY)])
    keys.append(navigation(theme))
    return Screen(body, Keyboard(keys))


def availability_screen(user, theme, *, active=None):
    """Read-only registration facts, never credentials, group grants or live health."""
    from .screens import Screen
    configured = selected(theme)
    if configured is None:
        return None
    rows = []
    for slug in dict.fromkeys((*(configured or ('moderation',)), 'moderation')):
        name, icon, _ = PROFILES[slug]
        count = len(commands(slug, active))
        status = 'Unknown' if active is None else 'Commands registered' if count else 'Not registered'
        rows.append((markup(f'{theme.emoji(icon)} {name}'), status, str(count) if active is not None else 'Unknown'))
    body = panel('Tool availability', icon=theme.emoji('stats'), subtitle='Selected tools · current command registration',
                 table=Table(headers=('Tool', 'State', 'Commands'), rows=tuple(rows)),
                 lines=['Not registered can mean disabled runtime, missing setup, or a module that could not load. This screen does not diagnose the cause.'],
                 note='Registration does not prove provider connectivity, Telegram permissions, Owner approval or group activation. Ask the bot’s owner to inspect configuration privately.',
                 footer='Refresh reads the current command registry. No credentials or internal errors are shown.')
    links = [button(theme, slug) for slug in dict.fromkeys((*(configured or ('moderation',)), 'moderation'))
             if allowed(theme, slug) and commands(slug, active)]
    keys = [links[index:index+2] for index in range(0, len(links), 2)]
    keys.extend([[theme.button('Refresh availability', icon='stats', callback_data='worker:availability', style=ButtonStyle.PRIMARY)], navigation(theme)])
    return Screen(body, Keyboard(keys))
