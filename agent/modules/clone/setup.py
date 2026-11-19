"""Private, expiring clone setup. Reviewed feature templates and combined suites.

Music requires explicit session consent and PostgreSQL account exclusivity.
Tokens are validated against Telegram, never echoed or logged.
"""
from __future__ import annotations

from ...platform.commands import command_name

import asyncio
import html
import secrets
import time
from weakref import WeakValueDictionary
from dataclasses import dataclass, field, replace

import aiohttp
from pyrogram.types import InlineKeyboardButton as Button, InlineKeyboardMarkup as Keyboard

from ...ui.tables import kv_table, panel
from ...utils.rich import reply, edit
from .store import Clone, parse_token
from .manager import CloneError
from .catalog import TEMPLATES, TEMPLATE_PLUGINS, plan_selection, selection_label
from ...platform.credentials import validate_ai_key, validate_ai_model, CredentialError
from ...platform.selection import SelectionError
from .assistant import validate_session
from ...platform.voice import capability


class SetupError(RuntimeError):
    pass


async def telegram(token, method, **payload):
    try:
        async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=15)) as session:
            async with session.post(f'https://api.telegram.org/bot{token}/{method}', json=payload) as response:
                body = await response.json()
        if not isinstance(body, dict) or not body.get('ok') or not isinstance(body.get('result'), dict):
            raise SetupError('Telegram did not confirm those credentials or permissions. Check them and retry.')
        return body['result']
    except (aiohttp.ClientError, asyncio.TimeoutError, ValueError):
        raise SetupError('Telegram verification is unavailable. No clone was created.') from None


@dataclass
class Setup:
    user_id: int
    nonce: str = field(default_factory=lambda: secrets.token_hex(8))
    expires: float = field(default_factory=lambda: time.monotonic() + 600)
    step: str = 'token'
    token: str = field(default='', repr=False)
    bot_id: int = 0
    username: str = ''
    log_channel: int | None = None
    storage_channel: int | None = None
    template: str = 'files'
    selected_plugins: tuple[str, ...] | None = None
    ai_api_key: str = field(default='', repr=False)
    ai_model: str = ''
    assistant_session: str = field(default='', repr=False)


class CloneSetup:
    def __init__(self, ctx, store, manager, entitled, quota, api=telegram):
        self.ctx, self.store, self.manager = ctx, store, manager
        self.entitled, self.quota, self.api = entitled, quota, api
        self.sessions = {}
        self._managed_offers = {}
        self._locks = WeakValueDictionary()
        self._finish_lock = asyncio.Lock()

    def active(self, user_id):
        state = self.sessions.get(user_id)
        if state and state.step != 'starting' and state.expires <= time.monotonic():
            self.sessions.pop(user_id, None)
            state.token = ''
            state.ai_api_key = ''
            state.assistant_session = ''
            return None
        return state

    def cancel(self, user_id):
        state = self.sessions.pop(user_id, None)
        if state is not None:
            state.token = ''
            state.ai_api_key = ''
            state.assistant_session = ''

    def keyboard(self, state, options):
        rows = [[Button(label, callback_data=f'csetup:{state.nonce}:{action}')] for label, action in options]
        rows.append([Button('Cancel setup', callback_data=f'csetup:{state.nonce}:cancel')])
        return Keyboard(rows)

    def plugins(self, state):
        return state.selected_plugins if state.selected_plugins is not None else TEMPLATE_PLUGINS[state.template]

    def select_plugins(self, state, requested):
        """Edit a live draft only; validation precedes any mutation."""
        if self.active(state.user_id) is not state or state.step == 'starting':
            raise SetupError('Clone draft is no longer editable.')
        selection = plan_selection(requested)
        if not selection:
            # Explicit group-core-only guided selection, not legacy profile fallback.
            selection = ('moderation',)
        state.selected_plugins = selection
        if 'ai_agent' not in selection:
            state.ai_api_key, state.ai_model = '', ''
        if 'music' not in selection:
            state.assistant_session = ''
        return selection

    def selection_keyboard(self, state):
        selected = self.plugins(state)
        options = [(('✓ ' if slug in selected else '+ ') + name, 'toggle:' + slug)
                   for action, (slug, name, _) in TEMPLATES.items()
                   if action not in ('moderation', 'file_suite', 'full_suite')]
        return self.keyboard(state, options + [('Continue with selected plugins', 'apply')])

    def review(self, state):
        return panel('Clone review', icon=self.ctx.theme.emoji('diamond'),
            subtitle=f"{self.ctx.theme.emoji('shield')} Verify before creating · isolated bot setup",
            table=kv_table([
                ('Bot', '@' + state.username if state.username else str(state.bot_id)),
                ('Owner', str(state.user_id)), ('Plugins', selection_label(self.plugins(state))),
                ('Log channel', str(state.log_channel) if state.log_channel else 'not configured'),
                ('Archive channel', str(state.storage_channel) if state.storage_channel else 'not configured'),
                ('Credentials', 'held privately for setup; never displayed'),
            ]),
            note='The authenticated token sender becomes Owner. Group use still needs approval and activation. '
                 'Creating does not prove human BotFather ownership or live voice playback.',
            footer='Create rechecks identity, channel permissions and capacity · /cancel discards the draft')

    async def resume(self, message, state):
        if state.step == 'starting':
            await reply(message, 'Creation is already starting. Do not resend credentials; check /mybots for the result.')
            return
        prompts = {
            'token': 'Send the bot token from @BotFather in this private chat.',
            'plugin': 'Choose the feature for this isolated clone.',
            'music_consent': 'Music uses your own authorized assistant session. Continue only with the account holder’s consent.',
            'music_session': 'Send your authorized assistant session only. Never send a phone number, password or OTP.',
            'ai_key': 'Send your own provider API key. Never share someone else’s credentials.',
            'ai_model': 'Send the model name for your provider credentials.',
            'log': 'Send a log channel ID or skip. You and the clone must administer the channel.',
            'storage': 'Send the FileStore archive channel ID. You and the clone must administer it.',
        }
        options = []
        if state.step == 'plugin':
            options = [(value[1], key) for key, value in TEMPLATES.items()]
        elif state.step == 'music_consent':
            options = [('I consent · continue', 'music_consent')]
        elif state.step == 'confirm':
            options = [('Edit plugins', 'edit_plugins'), ('Create clone', 'create')]
        body = self.review(state) if state.step == 'confirm' else panel(
            'Resume clone setup', icon=self.ctx.theme.emoji('bot'),
            table=kv_table([('Current step', state.step.replace('_', ' ')),
                            ('Time remaining', f'{max(0, int(state.expires - time.monotonic()))} seconds')]),
            lines=[prompts.get(state.step, 'Use the current setup controls.')],
            note='Your draft was preserved; expiry was not extended. Credential messages are deleted best-effort, not guaranteed.',
            footer='/cancel discards this draft · /clone resumes it')
        await reply(message, body, reply_markup=self.keyboard(state, options))

    async def begin(self, message, *, managed_import=False):
        user_id = getattr(getattr(message, 'from_user', None), 'id', None)
        if not isinstance(user_id, int) or isinstance(user_id, bool) or user_id <= 0:
            await reply(message, 'Use your personal Telegram identity in private chat to set up a clone.')
            return
        if message.chat.id != user_id:
            await reply(message, 'Open this bot privately and send /clone. Never send tokens in groups.')
            return
        if not await self.entitled(user_id):
            await reply(message, 'Clone setup requires bot premium, including for sudo and Owner users.')
            return
        existing = self.active(user_id)
        if existing is not None:
            await self.resume(message, existing)
            return
        if self.store.count() >= self.ctx.settings.clone_limit or len(self.store.by_owner(user_id)) >= self.quota(user_id):
            await reply(message, 'Clone capacity is reached. No token is needed; use /mybots to manage existing clones.')
            return
        if not self.store.encrypted():
            await reply(message, panel('Clone encryption needs setup', icon=self.ctx.theme.emoji('lock'),
                table=kv_table([('Status', 'No encryption key configured'),
                                ('Who sets it', 'Deployment Owner only'),
                                ('Other commands', 'Available without clone encryption setup')]),
                lines=['<code>TOKEN_KEY</code> encrypts stored clone bot tokens, AI keys and assistant sessions.',
                       'It is not your BotFather token, Telegram password or OTP. Clone users do not supply this key.'],
                note='Deployment Owner: configure a stable random TOKEN_KEY in the hosting environment and keep a secure backup. '
                     'Do not send it in Telegram or chat. Do not replace an existing key without a migration plan.',
                footer='No credentials requested · no draft created · /mybots manages existing clones'))
            return
        # Bound abandoned secrets in memory; restarting cancels all setup drafts.
        for uid in tuple(self.sessions):
            self.active(uid)
        if len(self.sessions) >= 100 and user_id not in self.sessions:
            await reply(message, 'Setup is busy. Please try again later.')
            return
        self.cancel(user_id)
        state = Setup(user_id)
        self.sessions[user_id] = state
        await reply(message, panel('Clone studio', icon=self.ctx.theme.emoji('bot'),
            lines=[f"{self.ctx.theme.emoji('diamond')} Premium setup · {self.ctx.theme.emoji('shield')} Private credentials",
                   ('Managed credential import requested. I will verify the bot before asking for configuration.'
                    if managed_import else 'Send the token from @BotFather. I will verify the bot before asking for configuration.'),
                   'Setup expires in 10 minutes. Send /cancel to discard it.'],
            footer='The authenticated person completing setup becomes the clone owner.'),
            reply_markup=self.keyboard(state, []))

    def offer_managed(self, user_id, bot_id):
        """Remember only Telegram-attested identities, never tokens, for ten minutes."""
        now = time.monotonic()
        self._managed_offers = {key: expiry for key, expiry in self._managed_offers.items()
                                if expiry > now}
        key = (user_id, bot_id)
        if (type(user_id) is not int or user_id <= 0 or type(bot_id) is not int
                or bot_id <= 0 or bot_id == self.ctx.settings.bot_id or self.store.get(bot_id)):
            return False
        if len(self._managed_offers) >= 100 and key not in self._managed_offers:
            return False
        self._managed_offers[key] = now + 600
        return True

    async def _accept_token(self, message, state, token, *, expected_bot_id=None):
        user_id = state.user_id
        if not isinstance(token, str):
            raise SetupError('Telegram did not return a valid bot credential.')
        ok, _, bot_id = parse_token(token)
        if not ok or (expected_bot_id is not None and bot_id != expected_bot_id):
            raise SetupError('That token format or managed bot identity is invalid.')
        if bot_id == self.ctx.settings.bot_id or self.store.get(bot_id):
            raise SetupError('That bot is already managed here or is the main bot.')
        allowed = await self.entitled(user_id)
        if not allowed or self.active(user_id) is not state or state.step != 'token':
            return False
        me = await self.api(token, 'getMe')
        allowed = await self.entitled(user_id)
        if not allowed or self.active(user_id) is not state or state.step != 'token':
            return False
        if (expected_bot_id is not None
                and self._managed_offers.get((user_id, expected_bot_id), 0) <= time.monotonic()):
            raise SetupError('Managed import consent expired. No credential was saved.')
        if (not self.store.encrypted() or self.store.count() >= self.ctx.settings.clone_limit
                or len(self.store.by_owner(user_id)) >= self.quota(user_id)):
            raise SetupError('Clone encryption or capacity is no longer available. No credential was saved.')
        if bot_id == self.ctx.settings.bot_id or self.store.get(bot_id):
            raise SetupError('That bot is already managed here or is the main bot.')
        if me.get('is_bot') is not True or me.get('id') != bot_id:
            raise SetupError('Telegram did not confirm a matching bot identity.')
        state.token, state.bot_id = token, bot_id
        state.username = str(me.get('username') or '')
        state.step = 'plugin'
        await reply(message, panel('Choose clone features', icon=self.ctx.theme.emoji('sparkles'),
            lines=[f"Verified bot: <b>@{html.escape(state.username)}</b>",
                   'Mandatory group moderation stays available with every template.'],
            footer='Music requires a dedicated assistant session. AI requires your own provider key and model.'),
            reply_markup=self.keyboard(state, [(name, action) for action, (_, name, _) in TEMPLATES.items()]))
        return True

    async def import_managed(self, client, message, bot_id):
        """Explicit private consent imports only a recent Telegram-attested bot.

        This never revokes a token or replaces an existing clone's credentials.
        The regular setup's final create confirmation remains required.
        """
        user_id = getattr(getattr(message, 'from_user', None), 'id', None)
        if (type(user_id) is not int or user_id <= 0 or type(bot_id) is not int or bot_id <= 0
                or getattr(getattr(message, 'chat', None), 'id', None) != user_id):
            return
        key = (user_id, bot_id)
        if self._managed_offers.get(key, 0) <= time.monotonic():
            await reply(message, 'No recent managed-bot event matches your identity and that bot. Use /clone for manual private setup.')
            return
        if self.active(user_id) is None:
            await self.begin(message, managed_import=True)
        state = self.active(user_id)
        if state is None:
            return
        lock = self._locks.setdefault(user_id, asyncio.Lock())
        async with lock:
            if self.active(user_id) is not state or state.step != 'token':
                await reply(message, 'A setup is already in progress. Finish it or /cancel before importing another bot.')
                return
            if (self._managed_offers.get(key, 0) <= time.monotonic()
                    or not await self.entitled(user_id) or not self.store.encrypted()
                    or self.store.count() >= self.ctx.settings.clone_limit
                    or len(self.store.by_owner(user_id)) >= self.quota(user_id)
                    or self.store.get(bot_id) or bot_id == self.ctx.settings.bot_id):
                await reply(message, 'Managed import is no longer available. Check access and capacity with /mybots.')
                return
            if self.active(user_id) is not state or state.step != 'token':
                return
            try:
                # Never use the revoke/replace API. Avoid exception text containing credentials.
                try:
                    token = await asyncio.wait_for(client.get_managed_bot_token(bot_id), timeout=15)
                except Exception:
                    raise SetupError('Telegram could not export that managed bot credential. No clone was created.') from None
                if (self.active(user_id) is not state
                        or self._managed_offers.get(key, 0) <= time.monotonic()):
                    return
                if await self._accept_token(message, state, token, expected_bot_id=bot_id):
                    self._managed_offers.pop(key, None)
            except SetupError as exc:
                await reply(message, str(exc))

    async def receive(self, client, message):
        user_id = getattr(getattr(message, 'from_user', None), 'id', None)
        if user_id is None or getattr(getattr(message, 'chat', None), 'id', None) != user_id:
            return
        state = self.active(user_id)
        if state is None:
            return
        text = (getattr(message, 'text', '') or '').strip()
        if command_name(text) == 'cancel':
            if state.step == 'starting':
                await reply(message, 'Creation is already starting. Manage the result through /mybots.')
                return
            self.cancel(user_id)
            await reply(message, 'Clone setup cancelled; the draft was discarded.')
            return
        if command_name(text) is not None and state.step not in ('ai_key', 'music_session'):
            return
        lock = self._locks.setdefault(user_id, asyncio.Lock())
        async with lock:
            if self.active(user_id) is not state:
                return
            if not await self.entitled(user_id):
                self.cancel(user_id)
                await reply(message, 'Clone access is no longer available. Setup cancelled.')
                return
            try:
                if state.step == 'token':
                    try:
                        await message.delete()
                    except Exception:
                        pass  # best effort: Telegram/cloud history is not a secret vault
                    await self._accept_token(message, state, text)
                elif state.step == 'music_session':
                    try:
                        await message.delete()
                    except Exception:
                        pass
                    if self.active(user_id) is not state or not await self.entitled(user_id):
                        return
                    try:
                        validate_session(text)
                    except Exception:
                        raise SetupError('That session is unsupported. Use a production Telethon IPv4 StringSession on port 443; never send a phone number, password or OTP.') from None
                    state.assistant_session = text
                    if 'ai_agent' in self.plugins(state):
                        state.step = 'ai_key'
                        await reply(message, 'Session structure accepted, not yet authorized. Account identity and exclusivity are checked at startup. Next send this clone’s own OpenAI API key; it will be encrypted. Messages are deleted best-effort, not guaranteed. No paid validation request is made.')
                    else:
                        state.step = 'log'
                        await reply(message, 'Session structure accepted, not yet authorized. Account identity and exclusivity are checked at startup. Send a log channel id, or skip.')
                elif state.step == 'ai_key':
                    try:
                        await message.delete()
                    except Exception:
                        pass
                    if self.active(user_id) is not state or not await self.entitled(user_id):
                        return
                    try:
                        validate_ai_key(text)
                    except CredentialError:
                        raise SetupError('Send an OpenAI API key beginning with sk-. It is not validated with a paid request.')
                    state.ai_api_key = text
                    state.step = 'ai_model'
                    await reply(message, 'Send the OpenAI model id to use. Compatibility and billing depend on your provider account. No test request is made during setup.')
                elif state.step == 'ai_model':
                    try:
                        validate_ai_model(text)
                    except CredentialError:
                        raise SetupError('Send a model id of at most 128 letters, numbers or model-id punctuation, without spaces.')
                    state.ai_model = text
                    state.step = 'log'
                    await reply(message, 'Send a log channel id, or skip. Your AI key will not appear in logs or setup panels.')
                elif state.step in ('log', 'storage'):
                    if state.step == 'log' and text.lower() == 'skip':
                        state.log_channel = None
                    else:
                        try:
                            channel = int(text)
                        except ValueError:
                            raise SetupError('Send a numeric Telegram channel id, such as -1001234567890.') from None
                        if not -(2**63) < channel < 0:
                            raise SetupError('A negative Telegram channel id is required.')
                        chat = await self.api(state.token, 'getChat', chat_id=channel)
                        if chat.get('type') != 'channel':
                            raise SetupError('Choose a channel, not a user or group.')
                        for uid in (state.bot_id, user_id):
                            member = await self.api(state.token, 'getChatMember', chat_id=channel, user_id=uid)
                            if member.get('status') not in ('administrator', 'creator'):
                                raise SetupError('Both you and the clone bot must administer this channel.')
                            if uid == state.bot_id and member.get('status') != 'creator' and not member.get('can_post_messages'):
                                raise SetupError('Grant the clone bot permission to post in this channel.')
                        if state.step == 'log':
                            state.log_channel = channel
                        else:
                            state.storage_channel = channel
                    if state.step == 'log' and ('filestore' in self.plugins(state)):
                        state.step = 'storage'
                        await reply(message, 'Send the FileStore archive channel id. Add the clone bot as an administrator with permission to post. You must administer it too.')
                    else:
                        state.step = 'confirm'
                        await reply(message, self.review(state),
                            reply_markup=self.keyboard(state, [('Edit plugins', 'edit_plugins'), ('Create clone', 'create')]))
                else:
                    await reply(message, 'Use the buttons on the latest setup panel, or /cancel.')
            except (SetupError, SelectionError, CloneError) as exc:
                await reply(message, str(exc))

    async def press(self, client, query, rest):
        user_id = getattr(getattr(query, 'from_user', None), 'id', None)
        state = self.active(user_id)
        origin = getattr(getattr(query, 'message', None), 'chat', None)
        nonce, _, action = rest.partition(':')
        if not state or nonce != state.nonce or getattr(origin, 'id', None) != user_id:
            await query.answer('This setup is expired or belongs to someone else.', show_alert=True)
            return
        if not await self.entitled(user_id):
            self.cancel(user_id)
            await query.answer('Clone access is no longer available.', show_alert=True)
            return
        if action == 'cancel':
            if state.step == 'starting':
                await query.answer('Creation is already starting. Manage the result through /mybots.', show_alert=True)
                return
            self.cancel(user_id)
            await query.answer('Setup cancelled.')
            return
        if action == 'music_consent' and state.step == 'music_consent':
            state.step = 'music_session'
            await edit(query, panel('Private assistant session', icon=self.ctx.theme.emoji('gear'),
                lines=['Send a pre-generated Telethon StringSession for a dedicated account you control.',
                       'Never send a phone number, password, recovery code or OTP. Use /cancel to stop.']))
            await query.answer()
            return
        if action == 'edit_plugins' and state.step == 'confirm':
            state.step = 'plugin'
            await edit(query, panel('Select clone plugins', lines=[
                'Group Management is always included. Toggle optional plugins, then continue.',
                'New selections recheck credentials and channels before creation.']),
                reply_markup=self.selection_keyboard(state))
            await query.answer()
            return
        if action.startswith('toggle:') and state.step == 'plugin':
            slug = action.partition(':')[2]
            choices = {value[0] for key, value in TEMPLATES.items()
                       if key not in ('moderation', 'file_suite', 'full_suite')}
            if slug not in choices:
                await query.answer('Unsupported optional plugin.', show_alert=True)
                return
            selected = set(self.plugins(state))
            selected.symmetric_difference_update({slug})
            self.select_plugins(state, selected)
            await edit(query, panel('Select clone plugins', lines=[
                'Group Management is always included.', selection_label(self.plugins(state))]),
                reply_markup=self.selection_keyboard(state))
            await query.answer()
            return
        if (action in TEMPLATES or action == 'apply') and state.step == 'plugin':
            if action in TEMPLATES:
                self.select_plugins(state, TEMPLATE_PLUGINS[action])
                state.template = action
            if 'music' in self.plugins(state):
                ok, _ = capability('dependency-check-only')
                db = getattr(self.ctx, 'db', None)
                if not ok or db is None or not db.connected or not self.ctx.settings.database_url:
                    await query.answer('Music setup requires an available database and installed voice dependencies. Do not send a session.', show_alert=True)
                    return
                state.step = 'music_consent'
                await edit(query, panel('Assistant account consent', icon=self.ctx.theme.emoji('shield'),
                    lines=['A session string grants access to a Telegram USER account, not just voice calls.',
                           'Use only a dedicated account you control. Never use your personal account.',
                           'The session is encrypted at rest, but the running service must decrypt it.',
                           'Telegram messages are deleted best-effort; chat history is not a credential vault.',
                           'You can cancel now. Revoke the session in Telegram Devices to invalidate access.']),
                    reply_markup=self.keyboard(state, [('I control this dedicated account — continue', 'music_consent')]))
                await query.answer()
                return
            if 'ai_agent' in self.plugins(state):
                state.step = 'ai_key'
                await edit(query, panel('Private AI credentials', icon=self.ctx.theme.emoji('gear'),
                    lines=['Send your own OpenAI API key here. It will be encrypted with TOKEN_KEY.',
                           'Only explicit questions go to the provider; no group history or autonomous actions.',
                           'Messages are deleted best-effort. Telegram history is not a secret vault; cancel if you prefer not to send credentials here.']))
                await query.answer()
                return
            state.step = 'log'
            await edit(query, panel('Clone log channel', icon=self.ctx.theme.emoji('gear'),
                lines=['Send a log channel id, or send <code>skip</code>. Both you and the clone must administer the channel.']))
            await query.answer()
            return
        if action != 'create' or state.step != 'confirm':
            await query.answer('Use the current setup step.', show_alert=True)
            return
        await query.answer('Checking and starting your clone…')
        async with self._finish_lock:
            if self.active(user_id) is not state or not await self.entitled(user_id):
                return
            limit = self.quota(user_id)
            if len(self.store.by_owner(user_id)) >= limit or self.store.count() >= self.ctx.settings.clone_limit:
                await reply(query.message, 'Clone capacity was reached. No clone was created.')
                return
            # Revalidate identity immediately before persisting/starting.
            try:
                snapshot = replace(state)
                me = await self.api(state.token, 'getMe')
                if me.get('id') != state.bot_id or me.get('is_bot') is not True or self.store.get(state.bot_id):
                    raise SetupError('Bot identity or availability changed. Restart setup.')
                for channel in (state.log_channel, state.storage_channel):
                    if channel is None:
                        continue
                    for uid in (state.bot_id, user_id):
                        member = await self.api(state.token, 'getChatMember', chat_id=channel, user_id=uid)
                        if member.get('status') not in ('administrator', 'creator'):
                            raise SetupError('Channel administrator permissions changed. Restart setup.')
                        if uid == state.bot_id and member.get('status') != 'creator' and not member.get('can_post_messages'):
                            raise SetupError('The clone can no longer post in the configured channel.')
                if self.active(user_id) is not state or not await self.entitled(user_id):
                    return
                if self.store.get(state.bot_id):
                    raise SetupError('That bot was added while setup was running. No duplicate was created.')
                # Validation occurs before persistence; Premium was just rechecked.
                candidate = Clone(bot_id=state.bot_id, owner_id=user_id, token=state.token,
                    selected_plugins=self.plugins(state), ai_api_key=state.ai_api_key or None,
                    ai_model=state.ai_model or None, assistant_session=state.assistant_session or None)
                self.manager.settings_for(candidate, premium=True)
                if not await self.entitled(user_id):
                    raise SetupError('Clone Premium eligibility changed. No clone was created.')
                if self.active(user_id) is not state or state != snapshot:
                    raise SetupError('Clone draft changed during validation. Restart setup; no clone was created.')
                state.step = 'starting'
                record = Clone(bot_id=state.bot_id, owner_id=user_id, token=state.token,
                    username=state.username, assistant_session=state.assistant_session or None, ai_api_key=state.ai_api_key or None, ai_model=state.ai_model or None, profile='tiny', selected_plugins=self.plugins(state), managed_owner=True,
                    log_channel=state.log_channel, storage_channel=state.storage_channel)
                await self.store.aadd(record, owner_limit=limit, total_limit=self.ctx.settings.clone_limit)
                try:
                    username = await self.manager.start(record)
                except (Exception, asyncio.CancelledError) as exc:
                    await self.store.aremove(record.bot_id)
                    if isinstance(exc, asyncio.CancelledError):
                        self.cancel(user_id)
                        raise
                    raise SetupError('The clone did not start. The draft was discarded; check bot credentials and deployment availability.') from None
                self.cancel(user_id)
                await reply(query.message, panel('Clone ready', icon=self.ctx.theme.emoji('sparkles'),
                    lines=[f'Bot id: <code>{record.bot_id}</code>', f'Bot: @{html.escape(username or state.username)}',
                           f'Owner: <code>{user_id}</code>', f'{selection_label(self.plugins(state))} is configured. Manage it with /mybots.',
                           'Group use still requires approval and activation through /plugin and group /plugins.']))
            except (SetupError, SelectionError, CloneError) as exc:
                self.cancel(user_id)
                await reply(query.message, str(exc))
            except Exception:
                self.cancel(user_id)
                await reply(query.message, 'Creation could not be confirmed. Check /mybots before retrying; the setup draft was discarded.')
