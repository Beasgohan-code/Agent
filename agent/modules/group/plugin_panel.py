"""Per-group plugin control using live transactional permission state."""
from types import SimpleNamespace
from pyrogram.errors import MessageNotModified

from pyrogram.types import InlineKeyboardButton as Button, InlineKeyboardMarkup as Keyboard

from ...platform.plugin_access import AccessError
from ...ui.tables import Table, panel
from ...utils.rich import reply, edit

PREFIX = 'gplug'
PAGE_SIZE = 5
LABELS = {'music': 'Music', 'filestore': 'FileStore', 'encoder': 'Encoder',
          'leech': 'Leech', 'linkshare': 'Linkshare', 'postmaker': 'Post Maker',
          'ai_agent': 'AI Agent', 'clone': 'Clones', 'renamer': 'Renamer',
          'premium': 'Premium', 'utilities': 'Utilities'}

DESCRIPTIONS = {
    'music': ('Voice-chat player', '/play a direct media or YouTube video link after activation. Requires this bot’s own connected assistant session; TypeTube is used for YouTube.'),
    'filestore': ('Channel-message FileStore', 'Configure this bot’s archive channel before creating or redeeming archive links. Private-chat delivery tools stay private.'),
    'encoder': ('Video processing', 'Reply to a video or attach one with a command caption. Encoding runs through this bot’s shared cancellable jobs.'),
    'leech': ('Downloads and YouTube audio', 'Use /leech URL or reply to one public URL. TypeTube handles YouTube audio; private upload settings live in /leech.'),
    'linkshare': ('Controlled file sharing', 'Share owned files with expiry/use limits. Required-channel membership is configured privately by this bot’s Owner.'),
    'postmaker': ('Rich posts', 'Compose posts with the installed Post Maker commands. Publishing still requires the relevant Telegram permissions.'),
    'ai_agent': ('Explicit AI questions', 'Uses this bot’s own provider key/model. No automatic group-history upload or autonomous actions.'),
}


def available(deployment):
    return bool(deployment and deployment['enabled'] and deployment['commands'] and deployment.get('scope') in ('all', 'group'))


def build(ctx):
    service = getattr(ctx, 'plugin_access', None)
    if service is None:
        return None

    async def render(client, message, page=0):
        state = await service.status(client, message)
        used = sum(row['active'] for row in state)
        state = [row for row in state if row['approved'] or row['active']]
        page = max(0, min(page, (len(state) - 1) // PAGE_SIZE))
        visible = state[page * PAGE_SIZE:(page + 1) * PAGE_SIZE]
        runtime = {row['slug']: row for row in ctx.runtime.state()}
        rows, buttons = [("Group Management", "Always on · no slots")], []
        for row in visible:
            slug = row['slug']
            name = LABELS.get(slug, slug)
            deployment = runtime.get(slug)
            usable = available(deployment)
            label = ('Active' if usable and row['approved'] else 'Active slot · runtime unavailable' if row['approved'] else 'Active slot · approval revoked') if row['active'] else (
                'Not approved' if not row['approved'] else 'Ready to activate' if usable else
                'Private-chat only' if deployment and deployment.get('scope') == 'private' else 'Runtime unavailable')
            rows.append((name, label))
            if row['active']:
                buttons.append([Button(f'Disable {name}', callback_data=f'{PREFIX}:ask:{slug}:{page}')])
            elif row['approved'] and usable and used < 3:
                buttons.append([Button(f'Activate {name}', callback_data=f'{PREFIX}:on:{slug}:{page}')])
            buttons.append([Button(f'About {name} · setup', callback_data=f'{PREFIX}:info:{slug}:{page}')])
        nav = []
        if page:
            nav.append(Button('‹ Previous', callback_data=f'{PREFIX}:page:{page-1}'))
        if (page + 1) * PAGE_SIZE < len(state):
            nav.append(Button('Next ›', callback_data=f'{PREFIX}:page:{page+1}'))
        if nav:
            buttons.append(nav)
        buttons.append([Button('Refresh', callback_data=f'{PREFIX}:page:{page}')])
        return panel('Group plugins', subtitle=f'{3-used} / 3 slots available · choose a tool workspace',
                     table=Table(headers=['Plugin', 'Status'], rows=rows, aligns=['left', 'left'], total_width=48),
                     lines=['Moderation · welcome · anti-spam · filters · reports · verification are included.',
                            *([] if state else ['No optional plugins approved yet. Runtime switches alone do not approve group use.']),
                            'Owner setup: <code>/plugin music on</code> → <code>/plugin music approve</code> (replace music with the tool slug).',
                            'Group admin: tap Activate for a ready tool. Open its setup card for requirements and installed commands.'],
                     note='Runtime on ≠ Owner approval ≠ group activation. Group Management is included and uses no optional slots.',
                     footer='Only approved optional tools appear here. /plugins opens this panel; /play starts music only after activation.'), Keyboard(buttons)

    async def details(client, message, slug, page):
        state = await service.status(client, message)
        selected = next((row for row in state if row['slug'] == slug), None)
        if selected is None or not (selected['approved'] or selected['active']):
            raise AccessError('This tool is not approved for this group. Refresh the plugin panel.')
        deployment = next((row for row in ctx.runtime.state() if row['slug'] == slug), None)
        used = sum(bool(row['active']) for row in state)
        usable = available(deployment)
        description, guidance = DESCRIPTIONS.get(slug, ('Optional tool', 'Use /help for this installed module’s commands.'))
        commands = deployment.get('commands', []) if deployment else []
        body = panel(LABELS.get(slug, slug) + ' · Plugin workspace', subtitle=description,
            table=Table(headers=('Check', 'Current state'), rows=[
                ('Runtime', 'registered and enabled' if deployment and deployment['enabled'] and commands else 'unavailable or disabled'),
                ('Owner approval', 'approved' if selected['approved'] else 'revoked'),
                ('This group', 'active slot' if selected['active'] else 'not activated'),
                ('Group slots', f'{used} / 3 used'),
                ('Command scope', deployment.get('scope', 'unknown') if deployment else 'not installed'),
            ]),
            lines=[guidance, 'Installed commands: ' + (' · '.join('/' + name for name in commands[:12]) or 'none registered')],
            note='Registered commands are not proof of live provider connectivity. Runtime on ≠ Owner approval ≠ group activation. Group Management remains always on and slot-free.',
            footer='Refresh reads live permission state. No credentials or stored configuration values are displayed.')
        buttons = []
        if selected['active']:
            buttons.append([Button('Disable for this group', callback_data=f'{PREFIX}:ask:{slug}:{page}')])
        elif selected['approved'] and usable and used < 3:
            buttons.append([Button('Activate for this group', callback_data=f'{PREFIX}:on:{slug}:{page}')])
        buttons += [[Button('Refresh status', callback_data=f'{PREFIX}:info:{slug}:{page}')],
                    [Button('‹ All group plugins', callback_data=f'{PREFIX}:page:{page}')]]
        return body, Keyboard(buttons)

    async def update(query, body, keyboard):
        try:
            await edit(query, body, reply_markup=keyboard)
        except MessageNotModified:
            pass

    async def show(client, message):
        try:
            body, keyboard = await render(client, message)
            await reply(message, body, reply_markup=keyboard)
        except AccessError as exc:
            await reply(message, str(exc))
        except Exception:
            await reply(message, 'Plugin state is unavailable. No local fallback or activation was attempted.')

    async def press(client, query, rest):
        origin = getattr(query, 'message', None)
        message = SimpleNamespace(chat=getattr(origin, 'chat', None), from_user=getattr(query, 'from_user', None))
        try:
            # Reauthorize the actual presser, not the sender of the bot's panel.
            await service._admin(client, message)
            parts = rest.split(':')
            action = parts[0]
            if action == 'page' and len(parts) == 2:
                page = int(parts[1])
            elif action in ('ask', 'on', 'off', 'info') and len(parts) == 3:
                slug, page = parts[1], int(parts[2])
                service._slug(slug)
                if action == 'info':
                    body, keyboard = await details(client, message, slug, page)
                    await update(query, body, keyboard)
                    await query.answer()
                    return
                if action == 'ask':
                    await update(query, panel('Disable plugin?', lines=[
                        f'Disable <b>{slug}</b> for this group? Its group-owned work will be cancelled.'
                    ]), Keyboard([
                        [Button('Confirm disable', callback_data=f'{PREFIX}:off:{slug}:{page}')],
                        [Button('Cancel', callback_data=f'{PREFIX}:page:{page}')],
                    ]))
                    await query.answer()
                    return
                if action == 'on':
                    available = {row['slug']: row for row in ctx.runtime.state()}.get(slug)
                    if not available or not available['enabled'] or not available['commands'] or available.get('scope') not in ('all', 'group'):
                        raise AccessError('Plugin is unavailable in this deployment.')
                    await service.activate(client, message, slug)
                else:
                    await service.deactivate(client, message, slug)
            else:
                raise AccessError('Invalid plugin control.')
            body, keyboard = await render(client, message, page)
            await update(query, body, keyboard)
            await query.answer('Updated.')
        except (AccessError, ValueError) as exc:
            await query.answer(str(exc), show_alert=True)
        except Exception:
            await query.answer('Plugin operation could not be confirmed. Refresh to check its state.', show_alert=True)

    ctx.actions.register(PREFIX, press)
    return show
