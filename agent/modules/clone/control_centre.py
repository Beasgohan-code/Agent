"""Owner-private observations of the existing clone authority, never a second writer.

Views are read-only; confirmed lifecycle actions use durable owner/revision/
generation admission and the existing reconciler. Missing local telemetry is
not proof of fleet-wide offline state. No credentials enter cards.
"""
import base64
import logging
import hashlib
import re
import time

from pyrogram.errors import MessageNotModified
from pyrogram.types import InlineKeyboardButton, InlineKeyboardMarkup, CopyTextButton
from pyrogram.enums import ButtonStyle

from ...ui.tables import Table, kv_table, panel, markup
from ...utils import rich

logger = logging.getLogger(__name__)
PAGE_SIZE = 6


class CloneControlCentre:
    def __init__(self, ctx, manager):
        self.ctx, self.manager, self.store = ctx, manager, manager._store

    def button(self, clone, title, view, icon='info'):
        return self.ctx.theme.button(title, icon=icon, callback_data=f'cc:{clone.bot_id}:{view}')

    @staticmethod
    def date(value):
        return time.strftime('%Y-%m-%d %H:%M UTC', time.gmtime(value)) if value else 'Unavailable'

    def navigation(self, clone):
        return [self.button(clone, 'Dashboard', 'home', 'bot'),
                self.ctx.theme.button('My Bots', icon='back', callback_data='cc:list:all:0')]

    def confirmation(self, clone, action, revision, generation):
        body = panel(f'Confirm {action}', icon=self.ctx.theme.emoji('warn'),
            lines=[f'Apply {action} to bot {clone.bot_id}?',
                   ('Delete removes the managed record and requests local teardown. Delivered files/messages, revision history and retained worker data are not erased.' if action == 'delete' else
                    'Stop saves durable stop intent; remote controllers must observe it. Start, restart and reconcile can replace the worker and interrupt work.'),
                   f'Configuration revision {revision} · lifecycle generation {generation}.'],
            note='No changes have been made. Confirmation rechecks owner, revision, generation and start eligibility.')
        keyboard = InlineKeyboardMarkup([
            [self.ctx.theme.button(f'Confirm {action}', icon='ban' if action in ('stop', 'restart', 'delete') else 'bolt',
                style=ButtonStyle.DANGER if action in ('stop', 'restart', 'delete') else ButtonStyle.PRIMARY,
                callback_data=f'cc:{clone.bot_id}:run:{action}:{revision}:{generation}')],
            [self.button(clone, 'Cancel', 'home', 'back')]])
        return body, keyboard

    async def render(self, clone, view, page=0, *, operation=None, command=None):
        observation = self.manager.observe_worker(clone.bot_id)
        plugins = observation['plugins']
        metadata = await self.manager.configuration.read(clone.bot_id) if self.store._db is not None else None
        rows, keys = [], []
        if view == 'home':
            registered = sum(len(p['commands']) for p in plugins) if plugins is not None else 'Unavailable'
            enabled = sum(len(p['commands']) for p in plugins if p['enabled']) if plugins is not None else 'Unavailable'
            rows = [('Name', clone.name[:80] or 'Not saved'), ('Username', clone.handle[:80]), ('Telegram ID', str(clone.bot_id)),
                    ('Created', self.date(clone.created_at)), ('Local lifecycle', self.manager.state(clone.bot_id).label),
                    ('Local worker', 'Observed in this controller' if observation['observed'] else 'Not observed in this controller'),
                    ('Desired intent', 'Stopped' if clone.disabled else 'Start eligible; subject to entitlement and validation'),
                    ('Configuration', metadata['configuration_status'] if metadata else 'Unavailable · legacy local record'),
                    ('Desired / applied revision', f"{metadata['desired_revision']} / {metadata['applied_revision']}" if metadata else 'Unavailable'),
                    ('Lifecycle generation', str(clone.lifecycle_generation)),
                    ('Registered / enabled commands', f'{registered} / {enabled}'),
                    ('Enabled plugins', str(sum(bool(p['enabled']) for p in plugins if p['slug'] != 'navigation')) if plugins is not None else 'Unavailable'),
                    ('Last activity', observation['activity']), ('Profile picture', 'Unavailable · not fetched'),
                    ('Per-worker CPU / RAM', 'Unavailable · workers share this process')]
            keys = [[self.button(clone, 'Commands', 'commands:0', 'search'), self.button(clone, 'Plugins', 'plugins:0', 'gear')],
                    [self.button(clone, 'Configuration', 'configuration', 'gear'), self.button(clone, 'Diagnostics', 'diagnostics', 'stats')],
                    [self.button(clone, 'Refresh', 'home', 'stats'), self.button(clone, 'Recent activity', 'activity:0', 'info')]]
            if metadata and metadata['desired_revision'] > 0:
                actions = []
                for action, label, icon in (('start', 'Start', 'bolt'), ('stop', 'Stop', 'ban'),
                                            ('restart', 'Restart', 'gear'), ('reconcile', 'Reconcile', 'stats')):
                    actions.append(self.ctx.theme.button(label, icon=icon,
                        callback_data=f'cc:{clone.bot_id}:ask:{action}:{metadata["desired_revision"]}:{clone.lifecycle_generation}'))
                keys.extend([actions[:2], actions[2:]])
                keys.append([self.ctx.theme.button('Delete clone', icon='ban', style=ButtonStyle.DANGER,
                    callback_data=f'cc:{clone.bot_id}:ask:delete:{metadata["desired_revision"]}:{clone.lifecycle_generation}')])
            if re.fullmatch(r'[A-Za-z][A-Za-z0-9_]{4,31}', clone.username or ''):
                keys.append([InlineKeyboardButton('Open Bot', url=f'https://t.me/{clone.username}',
                             icon_custom_emoji_id=self.ctx.theme.emoji_id('link'), style=ButtonStyle.PRIMARY)])
            note = 'Local observation is not fleet-wide online status. Registered commands do not prove provider readiness or group activation.'
        elif view == 'configuration':
            rows = [('Profile', clone.profile), ('Selected features', ', '.join(clone.selected_plugins) or 'Legacy profile selection'),
                    ('Group Management', 'Mandatory · always available'),
                    ('Archive channel', str(clone.storage_channel) if clone.storage_channel else 'Not configured'),
                    ('Log channel', str(clone.log_channel) if clone.log_channel else 'Not configured'),
                    ('Desired revision', str(metadata['desired_revision']) if metadata else 'Unavailable'),
                    ('Applied revision', str(metadata['applied_revision']) if metadata else 'Unavailable'),
                    ('Pending revision', str(metadata['pending_revision']) if metadata and metadata['pending_revision'] is not None else 'None observed'),
                    ('Last applied', self.date(metadata['last_applied_at']) if metadata else 'Unavailable')]
            keys = [[self.ctx.theme.button('Existing profile editor', icon='gear', callback_data=f'clone:{clone.bot_id}:profile')]]
            if metadata and metadata['desired_revision'] > 0:
                resets = [self.ctx.theme.button(label, icon='gear', callback_data=f'cc:{clone.bot_id}:reset:{field}:{metadata["desired_revision"]}:{clone.lifecycle_generation}')
                          for field, label in (('log_channel', 'Clear log channel'), ('storage_channel', 'Clear archive channel')) if getattr(clone, field) is not None]
                if resets:
                    keys.append(resets)
            note = 'Channel resets preview before saving a pending revision; existing copies are retained. Apply using dashboard Reconcile when ready. Arbitrary channel entry, credential editing and command toggles are unavailable here.'
        elif view == 'diagnostics':
            rows = [('Local lifecycle', self.manager.state(clone.bot_id).label),
                    ('Startup attempts', str(self.manager.state(clone.bot_id).attempts)),
                    ('Last lifecycle failure', 'Recorded · inspect controller #Errors privately' if self.manager.state(clone.bot_id).last_error else 'None recorded locally'),
                    ('Connected client', observation['connected']), ('Health', observation['health']),
                    ('Last activity', observation['activity']),
                    ('Configuration status', metadata['configuration_status'] if metadata else 'Unavailable'),
                    ('Failed revision', str(metadata['last_failed_revision']) if metadata and metadata['last_failed_revision'] else 'None observed'),
                    ('Worker logs', 'Unavailable · raw errors hidden'),
                    ('Lifecycle admission history', 'Available via Recent activity; not worker completion')]
            note = 'If configuration is pending or failed, review setup with the existing profile editor and lifecycle controls. Missing local observation is not proof of a remote failure. Raw errors and credentials are deliberately hidden.'
        elif view == 'command':
            from .control_actions import ControlConflict
            from ...platform.menu import DESCRIPTIONS
            plugin = next((p for p in plugins or () if p['enabled'] and command in p['commands']), None)
            if plugin is None:
                raise ControlConflict('Command is not available in this clone’s current local registry. Refresh Commands.')
            rows = [('Command', '/' + command), ('Description', DESCRIPTIONS.get(command, 'No usage description declared.')),
                    ('Plugin', plugin['name']), ('Scope', plugin['scope']),
                    ('Permissions', ', '.join(plugin['permissions']) or 'None declared'),
                    ('Dependencies', ', '.join(plugin['dependencies']) or 'None declared'),
                    ('Required credential names', ', '.join(plugin['credentials']) or 'None declared'),
                    ('Required capabilities', ', '.join(plugin['capabilities']) or 'None declared')]
            keys = [[InlineKeyboardButton('Copy /' + command, copy_text=CopyTextButton(text='/' + command),
                       icon_custom_emoji_id=self.ctx.theme.emoji_id('info'))],
                    [self.button(clone, 'Back to Commands', 'commands:0', 'back')]]
            note = 'Copy provides the bare command, not guessed arguments. Send it to this clone in the declared scope for current usage. Registry presence does not prove provider readiness, group approval or execution permission. No individual command toggles are supported.'
        elif view == 'activity':
            from .activity import read_activity
            events, has_next = await read_activity(self.store, clone.bot_id, clone.owner_id, page)
            rows = [(self.date(event['at']), event['action'].title() + ' · admitted (not completion)' +
                     f"\nRevision {event['revision']} · generation {event['generation']}")
                    if event else ('Unavailable receipt', 'Unsupported or malformed entry · raw data hidden') for event in events]
            if not rows:
                rows = [('No lifecycle admissions', 'No retained dashboard lifecycle requests found for this bot ID.')]
            paging = []
            if page:
                paging.append(self.button(clone, 'Previous', f'activity:{page-1}', 'back'))
            if has_next:
                paging.append(self.button(clone, 'Next', f'activity:{page+1}', 'arrow'))
            if paging:
                keys.append(paging)
            keys.append([self.button(clone, 'Refresh activity', 'activity:0', 'stats')])
            note = 'Lifecycle admission history only, not completion or worker logs. History is retained across deletion/recreation of this bot ID. Internal recovery and configuration writes are not included. Newest receipt first; no actor IDs, request IDs, credentials or raw errors displayed.'
        elif view in ('commands', 'plugins'):
            if plugins is None:
                rows = [('Registry', 'Unavailable · no inspectable local worker')]
                note = 'No command list is inferred from a saved profile. Start through the existing controls, then refresh after successful reconciliation.'
            else:
                items = [p for p in plugins] if view == 'plugins' else [(p, command) for p in plugins if p['enabled'] for command in p['commands']]
                pages = max(1, (len(items) + PAGE_SIZE - 1) // PAGE_SIZE)
                if not 0 <= page < pages:
                    raise ValueError('Stale page')
                if view == 'plugins':
                    rows = [(p['name'], ('Enabled' if p['enabled'] else 'Disabled') + f" · {len(p['commands'])} registered commands\n" +
                             'Scope: ' + p['scope'] + '\nPermissions: ' + (', '.join(p['permissions']) or 'None declared') +
                             '\nDependencies: ' + (', '.join(p['dependencies']) or 'None declared') +
                             '\nConfiguration fields: ' + (', '.join(p['fields']) or 'None declared') +
                             '\nRequired credential names: ' + (', '.join(p['credentials']) or 'None declared') +
                             '\nRequired capabilities: ' + (', '.join(p['capabilities']) or 'None declared')) for p in items[page * PAGE_SIZE:(page + 1) * PAGE_SIZE]]
                else:
                    from ...platform.menu import DESCRIPTIONS
                    rows = [(markup(f'<code>/{command}</code>'), DESCRIPTIONS.get(command, 'Send this command for current usage.') + '\nPlugin: ' + p['name'] + '\nScope: ' + p['scope'] + '\nPermissions: ' + (', '.join(p['permissions']) or 'None declared')) for p, command in items[page * PAGE_SIZE:(page + 1) * PAGE_SIZE]]
                if view == 'commands':
                    command_buttons = [self.button(clone, '/' + cmd, f'command:{cmd}', 'info')
                        for _, cmd in items[page * PAGE_SIZE:(page + 1) * PAGE_SIZE] if re.fullmatch(r'[a-z0-9_]{1,32}', cmd)]
                    keys.extend(command_buttons[i:i+2] for i in range(0, len(command_buttons), 2))
                paging = []
                if page:
                    paging.append(self.button(clone, 'Previous', f'{view}:{page-1}', 'back'))
                if page + 1 < pages:
                    paging.append(self.button(clone, 'Next', f'{view}:{page+1}', 'arrow'))
                if paging:
                    keys.append(paging)
                rows.append(('Page', f'{page+1} / {pages} · {len(items)} entries'))
                note = 'Snapshot of this clone’s actual local registry. Disabled plugin commands are excluded from Commands. Individual command toggles are not supported here; plugin runtime and group approval are separate.'
        else:
            raise ValueError('Stale view')
        keys.append(self.navigation(clone))
        return panel('Clone dashboard · ' + view.title(), icon=self.ctx.theme.emoji('bot'),
                     subtitle=f'Bot {clone.bot_id}', table=kv_table(rows) if view not in ('commands', 'plugins') else Table(headers=('Item', 'Details'), rows=tuple(rows)),
                     lines=[operation] if operation else [], note=note, footer='Owner-private · existing in-process workers · no OS sandbox'), InlineKeyboardMarkup(keys)

    @staticmethod
    def search_text(value):
        value = value.strip()
        if len(value.encode('utf-8')) > 24 or any(ord(c) < 32 or ord(c) == 127 for c in value):
            raise ValueError('Search must be at most 24 UTF-8 bytes without control characters.')
        return value

    async def render_directory(self, uid, mode, page, search=''):
        """Canonical owner-only read; callers enforce private Telegram origin."""
        await self.store.aall()
        search = self.search_text(search)
        suffix = ':' + base64.urlsafe_b64encode(search.encode()).decode().rstrip('=') if search else ''
        owned = sorted((c for c in self.store.all() if c.owner_id == uid), key=lambda c: c.bot_id)
        matches = [c for c in owned if mode == 'all' or (c.disabled if mode == 'stopped' else not c.disabled)]
        if search:
            term = search.casefold().removeprefix('@')
            matches = [c for c in matches if term in c.name.casefold() or term in c.username.casefold() or term in str(c.bot_id)]
        pages = max(1, (len(matches) + PAGE_SIZE - 1) // PAGE_SIZE)
        if page >= pages:
            raise ValueError('That page changed. Open My Bots again.')
        rows, keys = [], []
        for clone in matches[page * PAGE_SIZE:(page + 1) * PAGE_SIZE]:
            rows.append((clone.name[:48] or clone.handle[:48],
                f'Bot {clone.bot_id} · ' + ('Saved stop intent' if clone.disabled else 'Saved start eligibility') +
                '\nLocal worker: ' + ('observed' if self.manager.is_running(clone.bot_id) else 'not observed')))
            keys.append([self.button(clone, (clone.name or clone.handle)[:40], 'home', 'bot')])
        for pair in ((('all', 'All'), ('eligible', 'Start eligible')), (('stopped', 'Stop intent'), (mode, 'Refresh'))):
            keys.append([self.ctx.theme.button(label, icon='stats' if label == 'Refresh' else 'search',
                callback_data=f'cc:list:{value}:0{suffix}') for value, label in pair])
        paging = []
        if page:
            paging.append(self.ctx.theme.button('Previous', icon='back', callback_data=f'cc:list:{mode}:{page-1}{suffix}'))
        if page + 1 < pages:
            paging.append(self.ctx.theme.button('Next', icon='arrow', callback_data=f'cc:list:{mode}:{page+1}{suffix}'))
        if paging:
            keys.append(paging)
        if search:
            keys.append([self.ctx.theme.button('Clear search', icon='search', callback_data='cc:list:all:0')])
        keys.append([self.ctx.theme.button('Controller panel', icon='back', callback_data='clone:refresh')])
        body = panel('My Bots', icon=self.ctx.theme.emoji('bot'),
            subtitle=f'{len(matches)} matching · {len(owned)} owned · Page {page+1} / {pages}',
            table=kv_table(rows) if rows else None,
            lines=([f'Search: {search}'] if search else []) + ([] if rows else ['No clones match this filter. Choose All or use /clone to begin setup.']),
            note='Filters show saved intent, not fleet-wide online status. Start eligibility is still subject to Premium and validation. Local worker observation only describes this controller.',
            footer='Owner-private · search with /mybots <name, @username or bot ID> (24 UTF-8 bytes)')
        return body, InlineKeyboardMarkup(keys)

    async def directory(self, query, uid, mode, page, search=''):
        try:
            body, keys = await self.render_directory(uid, mode, page, search)
            try:
                await rich.edit(query, body, reply_markup=keys)
            except MessageNotModified:
                pass
            await query.answer()
        except Exception as exc:
            logger.warning('#Errors Clone directory unavailable (%s)', type(exc).__name__)
            notice = str(exc) if isinstance(exc, ValueError) else 'Saved bots could not be read safely. Retry My Bots after checking controller availability.'
            await query.answer(notice, show_alert=True)

    async def reset_channel(self, query, uid, match):
        """Narrow, non-secret editor; never reconfigure workers inside a save."""
        from .configuration import ConfigurationWriteError
        from .revisions import RevisionConflict
        try:
            bot_id, stage, field, revision, generation = int(match[1]), match[2], match[3], int(match[4]), int(match[5])
            await self.store.aall()
            clone = self.store.get(bot_id)
            if (self.store._db is None or clone is None or clone.owner_id != uid or revision <= 0 or
                    (clone.configuration_revision, clone.lifecycle_generation) != (revision, generation)):
                raise ConfigurationWriteError('Configuration access refused or stale. Refresh My Bots.')
            if stage == 'reset':
                if getattr(clone, field) is None:
                    raise ConfigurationWriteError('This channel is already unset. Refresh configuration.')
                label = 'Archive channel' if field == 'storage_channel' else 'Log channel'
                body = panel('Preview channel reset', icon=self.ctx.theme.emoji('warn'),
                    table=kv_table([('Field', label), ('Current', str(getattr(clone, field))),
                                    ('Proposed', 'Not configured'), ('Expected revision', str(revision))]),
                    note='No change saved. Clearing the archive channel removes the saved durable-copy destination; clearing the log channel removes the saved log destination. Existing copies are not deleted. Save creates pending configuration; workers must reconcile separately.')
                keys = InlineKeyboardMarkup([
                    [self.ctx.theme.button('Save reset', icon='gear', style=ButtonStyle.DANGER,
                        callback_data=f'cc:{bot_id}:save:{field}:{revision}:{generation}')],
                    [self.button(clone, 'Cancel', 'configuration', 'back')]])
            else:
                await query.answer('Validating configuration…')
                request_id = hashlib.sha256(f'{uid}:{query.data}'.encode()).hexdigest()
                result = await self.manager.configuration.write(bot_id, actor_id=uid, expected_revision=revision,
                    request_id=request_id, changes={field: None}, owner_only=True, expected_generation=generation)
                await self.store.aall()
                current = self.store.get(bot_id)
                if current is None or current.owner_id != uid:
                    raise ConfigurationWriteError('Configuration saved but clone changed. Refresh My Bots.')
                body, keys = await self.render(current, 'configuration',
                    operation=f'Saved desired revision {result["desired_revision"]}. Worker application is pending; review and use Reconcile from the dashboard when ready.')
            try:
                await rich.edit(query, body, reply_markup=keys)
            except MessageNotModified:
                pass
            if stage == 'reset':
                await query.answer()
        except Exception as exc:
            logger.warning('#Errors Clone configuration reset unconfirmed (%s)', type(exc).__name__)
            notice = str(exc) if isinstance(exc, (ConfigurationWriteError, RevisionConflict)) else 'Result unconfirmed. Refresh configuration before retrying.'
            await query.answer(notice, show_alert=True)

    async def press(self, client, query, rest):
        user = getattr(query, 'from_user', None)
        uid = getattr(user, 'id', None)
        origin = getattr(query, 'message', None)
        if type(uid) is not int or uid <= 0 or getattr(getattr(origin, 'chat', None), 'id', None) != uid:
            await query.answer('Open /mybots privately as yourself.', show_alert=True)
            return
        directory_match = re.fullmatch(r'list:(all|eligible|stopped):([0-9]{1,4})(?::([A-Za-z0-9_-]{1,32}))?', rest)
        if directory_match:
            try:
                encoded = directory_match[3]
                search = base64.b64decode(encoded + '=' * (-len(encoded) % 4), altchars=b'-_', validate=True).decode('utf-8') if encoded else ''
                search = self.search_text(search)
                if encoded and base64.urlsafe_b64encode(search.encode()).decode().rstrip('=') != encoded:
                    raise ValueError('Noncanonical search')
            except (ValueError, UnicodeError):
                await query.answer('That search control is stale. Use /mybots to search again.', show_alert=True)
                return
            await self.directory(query, uid, directory_match[1], int(directory_match[2]), search)
            return
        reset_match = re.fullmatch(r'([0-9]{6,12}):(reset|save):(log_channel|storage_channel):([0-9]{1,12}):([0-9]{1,12})', rest)
        if reset_match:
            await self.reset_channel(query, uid, reset_match)
            return
        command_match = re.fullmatch(r'([0-9]{6,12}):command:([a-z0-9_]{1,32})', rest)
        action_match = re.fullmatch(r'([0-9]{6,12}):(ask|run):(start|stop|restart|reconcile|delete):([0-9]{1,12}):([0-9]{1,12})', rest)
        match = re.fullmatch(r'([0-9]{6,12}):(home|configuration|diagnostics|commands|plugins|activity)(?::([0-9]{1,4}))?', rest)
        if not command_match and not action_match and (not match or ((match[2] in ('commands', 'plugins', 'activity')) != (match[3] is not None))):
            await query.answer('That dashboard control is stale.', show_alert=True)
            return
        try:
            await self.store.aall()  # Canonical reload before ownership check, including after deletion/transfer.
            clone = self.store.get(int(command_match[1] if command_match else action_match[1] if action_match else match[1]))
            if clone is None or clone.owner_id != uid:
                await query.answer('This clone is unavailable to you. Refresh My Bots.', show_alert=True)
                return
            result = None
            if action_match:
                from .control_actions import ControlConflict
                stage, action, revision, generation = action_match[2], action_match[3], int(action_match[4]), int(action_match[5])
                if self.store._db is None or revision <= 0 or (clone.configuration_revision, clone.lifecycle_generation) != (revision, generation):
                    raise ControlConflict('Lifecycle control is unavailable or stale. Refresh the dashboard.')
                if stage == 'ask':
                    body, keyboard = self.confirmation(clone, action, revision, generation)
                else:
                    await query.answer('Validating lifecycle request…')
                    request_id = hashlib.sha256(f'{uid}:{rest}'.encode()).hexdigest()
                    result = await self.manager.control(clone.bot_id, action, actor_id=uid,
                        expected_revision=revision, expected_generation=generation, request_id=request_id)
                    await self.store.aall()
                    current = self.store.get(clone.bot_id)
                    if action == 'delete':
                        body = panel('Clone removed', icon=self.ctx.theme.emoji('info'), lines=[result],
                            note='This removes the managed record, not messages/files already delivered or all retained worker data.')
                        keyboard = InlineKeyboardMarkup([[self.ctx.theme.button('My Bots', icon='back', callback_data='cc:list:all:0')]])
                    elif current is None or current.owner_id != uid:
                        raise ControlConflict('Clone changed during the operation. Refresh My Bots.')
                    else:
                        body, keyboard = await self.render(current, 'home', operation=result)
            elif command_match:
                body, keyboard = await self.render(clone, 'command', command=command_match[2])
            else:
                body, keyboard = await self.render(clone, match[2], int(match[3] or 0))
            try:
                await rich.edit(query, body, reply_markup=keyboard)
            except MessageNotModified:
                pass
            if result is None:
                await query.answer()
        except Exception as exc:
            logger.warning('#Errors Clone dashboard unavailable (%s)', type(exc).__name__)
            from .control_actions import ControlConflict
            from .manager import CloneError
            notice = str(exc) if isinstance(exc, (ControlConflict, CloneError)) else 'Result could not be confirmed. Refresh My Bots before retrying.'
            await query.answer(notice, show_alert=True)
