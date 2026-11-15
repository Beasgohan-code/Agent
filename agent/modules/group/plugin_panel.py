"""Per-group plugin control using live transactional permission state."""
from types import SimpleNamespace

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
            available = bool(deployment and deployment['enabled'] and deployment['commands'] and deployment.get('scope') in ('all', 'group'))
            label = ('Active' if row['active'] else 'Not approved' if not row['approved']
                     else 'Available' if available else 'Unavailable here')
            rows.append((name, label))
            if row['active']:
                buttons.append([Button(f'Disable {name}', callback_data=f'{PREFIX}:ask:{slug}:{page}')])
            elif row['approved'] and available and used < 3:
                buttons.append([Button(f'Activate {name}', callback_data=f'{PREFIX}:on:{slug}:{page}')])
        nav = []
        if page:
            nav.append(Button('‹ Previous', callback_data=f'{PREFIX}:page:{page-1}'))
        if (page + 1) * PAGE_SIZE < len(state):
            nav.append(Button('Next ›', callback_data=f'{PREFIX}:page:{page+1}'))
        if nav:
            buttons.append(nav)
        buttons.append([Button('Refresh', callback_data=f'{PREFIX}:page:{page}')])
        return panel('Group plugins', subtitle=f'{3-used} / 3 slots available',
                     table=Table(headers=['Plugin', 'Status'], rows=rows, aligns=['left', 'left'], total_width=48),
                     lines=['Welcome · anti-spam · filters · moderation · reports · verification',
                            *([] if state else ['No optional plugins approved yet. Ask the bot owner to approve the tools you need.'])],
                     footer='Group Management is included. Only approved optional tools appear here.'), Keyboard(buttons)

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
            elif action in ('ask', 'on', 'off') and len(parts) == 3:
                slug, page = parts[1], int(parts[2])
                service._slug(slug)
                if action == 'ask':
                    await edit(query, panel('Disable plugin?', lines=[
                        f'Disable <b>{slug}</b> for this group? Its group-owned work will be cancelled.'
                    ]), reply_markup=Keyboard([
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
            await edit(query, body, reply_markup=keyboard)
            await query.answer('Updated.')
        except (AccessError, ValueError) as exc:
            await query.answer(str(exc), show_alert=True)
        except Exception:
            await query.answer('Plugin operation could not be confirmed. Refresh to check its state.', show_alert=True)

    ctx.actions.register(PREFIX, press)
    return show
