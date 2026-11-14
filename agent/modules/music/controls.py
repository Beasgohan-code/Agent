"""Original queue/volume controls; no reference code or external extractors."""
import html
import random

from ..moderation import is_moderator
from ...utils.rich import reply
from ...ui.tables import Table, kv_table, panel
from ...platform.voice import VoiceUnavailable

COMMANDS = ('loop', 'shuffle', 'clear', 'clearqueue', 'remove', 'move', 'jump',
            'replay', 'volume', 'volumeup', 'volumedown', 'history')


def build_controls(ctx, queues, history, volumes, advance):
    engine = ctx.voice

    async def control(client, message):
        name = message.text.split()[0].split('@')[0].lstrip('/').lower()
        args = message.text.split()[1:]
        chat_id = message.chat.id
        if name == 'history':
            if args:
                await reply(message, 'Use /history without arguments.')
                return
            records = history.get(chat_id, ())
            await reply(message, panel('Recent playback', icon=ctx.theme.emoji('music'),
                table=Table(headers=('#', 'Track'), rows=tuple((str(i), title) for i, title in enumerate(reversed(records), 1))),
                note='Session-only, acknowledged track titles. No message history is collected.'))
            return
        if not await is_moderator(client, message, owner_id=ctx.settings.owner_id):
            await reply(message, 'Only group administrators can edit the shared music queue or volume.')
            return
        queue = queues.for_chat(chat_id)
        try:
            if name == 'loop':
                if len(args) != 1 or args[0].lower() not in ('off', 'one', 'all'):
                    raise ValueError('Use /loop off|one|all.')
                queue.loop, queue.repeat_all = args[0].lower() == 'one', args[0].lower() == 'all'
                said = f'Repeat mode: {args[0].lower()}.'
            elif name in ('clear', 'clearqueue', 'shuffle'):
                if args:
                    raise ValueError(f'Use /{name} without arguments.')
                if name == 'shuffle':
                    random.SystemRandom().shuffle(queue.waiting)
                    said = f'Shuffled {len(queue.waiting)} upcoming tracks; current playback is unchanged.'
                else:
                    count = len(queue.waiting)
                    queue.waiting.clear()
                    said = f'Cleared {count} upcoming tracks; current playback is unchanged.'
            elif name in ('remove', 'move', 'jump'):
                needed = 2 if name == 'move' else 1
                if len(args) != needed or any(not value.isdecimal() or len(value) > 3 for value in args):
                    raise ValueError('Use /remove <position> or /move <from> <to>. Upcoming positions start at 1.')
                positions = [int(value) for value in args]
                if any(not 1 <= position <= len(queue.waiting) for position in positions):
                    raise ValueError('Choose an existing upcoming position from /queue; current playback is protected.')
                original = list(queue.waiting)
                track = queue.waiting.pop(positions[0] - 1)
                if name == 'move':
                    queue.waiting.insert(positions[1] - 1, track)
                elif name == 'jump':
                    queue.waiting.insert(0, track)
                    try:
                        if await advance(chat_id, force=True) is None:
                            raise VoiceUnavailable('The selected track was not started.')
                    except BaseException:
                        queue.waiting = original
                        raise
                said = ('Selected track started after voice-engine acknowledgement.' if name == 'jump'
                        else 'Upcoming queue updated; current playback is unchanged.')
            elif name == 'replay':
                if args:
                    raise ValueError('Use /replay without arguments.')
                playback = engine.playback(chat_id)
                if playback is None:
                    raise ValueError('Nothing is playing here.')
                await engine.play(chat_id, playback.source, title=playback.title, requested_by=playback.requested_by)
                said = 'Restarted the current track after voice-engine acknowledgement.'
            else:
                previous = volumes.get(chat_id, 100)
                if name == 'volume':
                    if not args:
                        await reply(message, panel('Voice volume', icon=ctx.theme.emoji('speaker'),
                            subtitle=f"{ctx.theme.emoji('stats')} This group's volume settings",
                            table=kv_table([
                                ('Volume', f'{previous}%' if chat_id in volumes else 'not set this session'),
                                ('Range', '20–200%'),
                                ('Adjustment', '20% per step'),
                            ]),
                            note=(f'Volume: {previous}% (last setting acknowledged by this process).' if chat_id in volumes else
                                  'No volume change acknowledged this session; adjustments use a 100% baseline.'),
                            footer='/volume 100 · /volumeup · /volumedown'))
                        return
                    if len(args) != 1 or not args[0].isdecimal() or len(args[0]) > 3:
                        raise ValueError('Use /volume <20-200>.')
                    target = int(args[0])
                else:
                    if args:
                        raise ValueError(f'Use /{name} without arguments.')
                    target = max(20, min(200, previous + (20 if name == 'volumeup' else -20)))
                if not 20 <= target <= 200:
                    raise ValueError('Volume must be between 20 and 200 percent.')
                if engine.playback(chat_id) is None:
                    raise ValueError('Start playback before changing voice volume.')
                acknowledged = await engine.volume(chat_id, target)
                if acknowledged is False:
                    raise VoiceUnavailable('Voice volume was not acknowledged.')
                if chat_id not in volumes and len(volumes) >= 200:
                    volumes.pop(next(iter(volumes)))
                volumes[chat_id] = target
                said = f'Volume updated to {target}%.'
            await reply(message, panel('Music updated', icon=ctx.theme.emoji('check'),
                lines=[html.escape(said)],
                note=f"{ctx.theme.emoji('music')} Changes apply to this group's current session only.",
                footer='/nowplaying · /queue · /voicehealth'))
        except ValueError as error:
            await reply(message, panel('Check this action', icon=ctx.theme.emoji('info'),
                lines=[html.escape(str(error))], footer=f'/help {name}'))
        except Exception as error:
            # No raw third-party errors or source URLs in the chat.
            await reply(message, panel('Action not confirmed', icon=ctx.theme.emoji('warn'),
                lines=[f'The music action was not confirmed ({type(error).__name__}).'],
                note='Check /queue or /nowplaying before retrying; a reply failure does not prove a failed change.'))

    return {command: control for command in COMMANDS}
