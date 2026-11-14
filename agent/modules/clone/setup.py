"""Private, expiring clone setup. Reviewed single-plugin templates with isolated destinations.

Music requires explicit session consent and PostgreSQL account exclusivity.
Tokens are validated against Telegram, never echoed or logged.
"""
from __future__ import annotations

import asyncio
import html
import secrets
import re
import time
from weakref import WeakValueDictionary
from dataclasses import dataclass, field

import aiohttp
from pyrogram.types import InlineKeyboardButton as Button, InlineKeyboardMarkup as Keyboard

from ...ui.tables import kv_table, panel
from ...utils.rich import reply, edit
from .store import Clone, parse_token
from .catalog import TEMPLATES
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
    ai_api_key: str = field(default='', repr=False)
    ai_model: str = ''
    assistant_session: str = field(default='', repr=False)


class CloneSetup:
    def __init__(self, ctx, store, manager, entitled, quota, api=telegram):
        self.ctx, self.store, self.manager = ctx, store, manager
        self.entitled, self.quota, self.api = entitled, quota, api
        self.sessions = {}
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

    def review(self, state):
        return panel('Clone review', icon=self.ctx.theme.emoji('diamond'),
            subtitle=f"{self.ctx.theme.emoji('shield')} Verify before creating · isolated bot setup",
            table=kv_table([
                ('Bot', '@' + state.username if state.username else str(state.bot_id)),
                ('Owner', str(state.user_id)), ('Plugin', TEMPLATES[state.template][1]),
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
            options = [('Create clone', 'create')]
        body = self.review(state) if state.step == 'confirm' else panel(
            'Resume clone setup', icon=self.ctx.theme.emoji('bot'),
            table=kv_table([('Current step', state.step.replace('_', ' ')),
                            ('Time remaining', f'{max(0, int(state.expires - time.monotonic()))} seconds')]),
            lines=[prompts.get(state.step, 'Use the current setup controls.')],
            note='Your draft was preserved; expiry was not extended. Credential messages are deleted best-effort, not guaranteed.',
            footer='/cancel discards this draft · /clone resumes it')
        await reply(message, body, reply_markup=self.keyboard(state, options))

    async def begin(self, message):
        user_id = getattr(getattr(message, 'from_user', None), 'id', None)
        if not isinstance(user_id, int) or isinstance(user_id, bool) or user_id <= 0:
            await reply(message, 'Use your personal Telegram identity in private chat to set up a clone.')
            return
        if message.chat.id != user_id:
            await reply(message, 'Open this bot privately and send /clone. Never send tokens in groups.')
            return
        if not self.entitled(user_id):
            await reply(message, 'Clone setup requires bot premium, sudo access or Owner access.')
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
                                ('Other commands', 'No TOKEN_KEY needed unless storing clone credentials')]),
                lines=['<code>TOKEN_KEY</code> encrypts stored clone bot tokens, AI keys and assistant sessions.',
                       'It is not your BotFather token, Telegram password or OTP. Clone users do not supply this key.'],
                note='Owner: configure a stable random TOKEN_KEY in the hosting environment and keep a secure backup. '
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
                   'Send the token from @BotFather. I will verify the bot before asking for configuration.',
                   'Setup expires in 10 minutes. Send /cancel to discard it.'],
            footer='The authenticated person completing setup becomes the clone owner.'),
            reply_markup=self.keyboard(state, []))

    async def receive(self, client, message):
        user_id = getattr(getattr(message, 'from_user', None), 'id', None)
        if user_id is None or getattr(getattr(message, 'chat', None), 'id', None) != user_id:
            return
        state = self.active(user_id)
        if state is None:
            return
        text = (getattr(message, 'text', '') or '').strip()
        if text.split('@', 1)[0] == '/cancel':
            if state.step == 'starting':
                await reply(message, 'Creation is already starting. Manage the result through /mybots.')
                return
            self.cancel(user_id)
            await reply(message, 'Clone setup cancelled; the draft was discarded.')
            return
        if text.startswith('/') and state.step not in ('ai_key', 'music_session'):
            return
        lock = self._locks.setdefault(user_id, asyncio.Lock())
        async with lock:
            if self.active(user_id) is not state:
                return
            if not self.entitled(user_id):
                self.cancel(user_id)
                await reply(message, 'Clone access is no longer available. Setup cancelled.')
                return
            try:
                if state.step == 'token':
                    try:
                        await message.delete()
                    except Exception:
                        pass  # best effort: Telegram/cloud history is not a secret vault
                    ok, _, bot_id = parse_token(text)
                    if not ok:
                        raise SetupError('That token format is invalid. Send a token from @BotFather.')
                    if bot_id == self.ctx.settings.bot_id or self.store.get(bot_id):
                        raise SetupError('That bot is already managed here or is the main bot.')
                    me = await self.api(text, 'getMe')
                    if self.active(user_id) is not state or not self.entitled(user_id):
                        return
                    if me.get('is_bot') is not True or me.get('id') != bot_id:
                        raise SetupError('Telegram did not confirm a matching bot identity.')
                    state.token, state.bot_id = text, bot_id
                    state.username = str(me.get('username') or '')
                    state.step = 'plugin'
                    await reply(message, panel('Choose clone features', icon=self.ctx.theme.emoji('sparkles'),
                        lines=[f"Verified bot: <b>@{html.escape(state.username)}</b>",
                               'Mandatory group moderation stays available with every template.'],
                        footer='Music requires a dedicated assistant session. AI requires your own provider key and model.'),
                        reply_markup=self.keyboard(state, [(name, action) for action, (_, name, _) in TEMPLATES.items()]))
                elif state.step == 'music_session':
                    try:
                        await message.delete()
                    except Exception:
                        pass
                    if self.active(user_id) is not state or not self.entitled(user_id):
                        return
                    try:
                        validate_session(text)
                    except Exception:
                        raise SetupError('That session is unsupported. Use a production Telethon IPv4 StringSession on port 443; never send a phone number, password or OTP.') from None
                    state.assistant_session = text
                    state.step = 'log'
                    await reply(message, 'Session structure accepted, not yet authorized. Account identity and exclusivity are checked at startup. Send a log channel id, or skip.')
                elif state.step == 'ai_key':
                    try:
                        await message.delete()
                    except Exception:
                        pass
                    if self.active(user_id) is not state or not self.entitled(user_id):
                        return
                    if not re.fullmatch(r'sk-[A-Za-z0-9_-]{16,250}', text):
                        raise SetupError('Send an OpenAI API key beginning with sk-. It is not validated with a paid request.')
                    state.ai_api_key = text
                    state.step = 'ai_model'
                    await reply(message, 'Send the OpenAI model id to use. Compatibility and billing depend on your provider account. No test request is made during setup.')
                elif state.step == 'ai_model':
                    if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.:/-]{0,127}', text):
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
                    if state.step == 'log' and TEMPLATES[state.template][2]:
                        state.step = 'storage'
                        await reply(message, 'Send the FileStore archive channel id. Add the clone bot as an administrator with permission to post. You must administer it too.')
                    else:
                        state.step = 'confirm'
                        await reply(message, self.review(state),
                            reply_markup=self.keyboard(state, [('Create clone', 'create')]))
                else:
                    await reply(message, 'Use the buttons on the latest setup panel, or /cancel.')
            except SetupError as exc:
                await reply(message, str(exc))

    async def press(self, client, query, rest):
        user_id = getattr(getattr(query, 'from_user', None), 'id', None)
        state = self.active(user_id)
        origin = getattr(getattr(query, 'message', None), 'chat', None)
        nonce, _, action = rest.partition(':')
        if not state or nonce != state.nonce or getattr(origin, 'id', None) != user_id:
            await query.answer('This setup is expired or belongs to someone else.', show_alert=True)
            return
        if not self.entitled(user_id):
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
        if action in TEMPLATES and state.step == 'plugin':
            if action == 'music':
                ok, _ = capability('dependency-check-only')
                db = getattr(self.ctx, 'db', None)
                if not ok or db is None or not db.connected or not self.ctx.settings.database_url:
                    await query.answer('Music setup requires connected PostgreSQL and installed voice dependencies. Do not send a session.', show_alert=True)
                    return
                state.template = action
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
            state.template = action
            if action == 'ai_agent':
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
            if self.active(user_id) is not state or not self.entitled(user_id):
                return
            limit = self.quota(user_id)
            if len(self.store.by_owner(user_id)) >= limit or self.store.count() >= self.ctx.settings.clone_limit:
                await reply(query.message, 'Clone capacity was reached. No clone was created.')
                return
            # Revalidate identity immediately before persisting/starting.
            try:
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
                if self.active(user_id) is not state or not self.entitled(user_id):
                    return
                if self.store.get(state.bot_id):
                    raise SetupError('That bot was added while setup was running. No duplicate was created.')
                state.step = 'starting'
                record = Clone(bot_id=state.bot_id, owner_id=user_id, token=state.token,
                    username=state.username, assistant_session=state.assistant_session or None, ai_api_key=state.ai_api_key or None, ai_model=state.ai_model or None, profile='tiny', selected_plugins=(TEMPLATES[state.template][0],), managed_owner=True,
                    log_channel=state.log_channel, storage_channel=state.storage_channel)
                self.store.add(record)
                try:
                    username = await self.manager.start(record)
                except (Exception, asyncio.CancelledError) as exc:
                    self.store.remove(record.bot_id)
                    if isinstance(exc, asyncio.CancelledError):
                        self.cancel(user_id)
                        raise
                    raise SetupError('The clone did not start. The draft was discarded; check bot credentials and deployment availability.') from None
                self.cancel(user_id)
                await reply(query.message, panel('Clone ready', icon=self.ctx.theme.emoji('sparkles'),
                    lines=[f'Bot id: <code>{record.bot_id}</code>', f'Bot: @{html.escape(username or state.username)}',
                           f'Owner: <code>{user_id}</code>', f'{TEMPLATES[state.template][1]} is configured. Manage it with /mybots.',
                           'Group use still requires approval and activation through /plugin and group /plugins.']))
            except SetupError as exc:
                self.cancel(user_id)
                await reply(query.message, str(exc))
            except Exception:
                self.cancel(user_id)
                await reply(query.message, 'Creation could not be confirmed. Check /mybots before retrying; the setup draft was discarded.')
