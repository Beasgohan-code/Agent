"""Security and consent controls preserve exact action binding with custom icons."""
import pytest
from agent.modules.security.verify import button_for
from agent.ui.theme import Theme
from pyrogram.enums import ButtonStyle


def test_verify_icon_preserves_member_binding():
    theme = Theme()
    button = button_for(-100,22,theme=theme).inline_keyboard[0][0]
    assert button.icon_custom_emoji_id == theme.emoji_id('check')
    assert button.text == 'I am human'
    assert button.callback_data == 'verify:-100:22'
    assert button.style == ButtonStyle.SUCCESS


def test_verify_disabled_theme_has_one_unicode_glyph():
    button = button_for(-100,22,theme=Theme({})).inline_keyboard[0][0]
    assert button.icon_custom_emoji_id is None and button.text == '✅ I am human'


def test_federation_consent_icons_preserve_invitation_actions():
    from agent.modules.federations.roles import invitation_keyboard
    theme = Theme()
    buttons = [b for row in invitation_keyboard(theme,'opaque').inline_keyboard for b in row]
    assert [b.callback_data for b in buttons] == ['fedrole:accept:opaque','fedrole:decline:opaque']
    assert [b.style for b in buttons] == [ButtonStyle.SUCCESS,ButtonStyle.DANGER]
    assert [b.icon_custom_emoji_id for b in buttons] == [theme.emoji_id('check'),theme.emoji_id('cross')]


@pytest.mark.asyncio
async def test_consent_send_falls_back_only_for_explicit_icon_rejection():
    from types import SimpleNamespace as NS
    from unittest.mock import AsyncMock
    from agent.modules.federations.roles import invitation_keyboard
    from agent.utils.rich import send
    theme = Theme()
    original = invitation_keyboard(theme,'bound-token')
    client = NS(send_message=AsyncMock(side_effect=[RuntimeError('CUSTOM_EMOJI_INVALID'),NS(id=10)]))
    assert (await send(client,22,'Invitation',reply_markup=original)).id == 10
    calls = client.send_message.await_args_list
    assert len(calls) == 2
    fallback = calls[1].kwargs['reply_markup'].inline_keyboard[0][0]
    assert fallback.text == '✅ Accept' and not fallback.icon_custom_emoji_id
    assert fallback.callback_data == 'fedrole:accept:bound-token'
    assert original.inline_keyboard[0][0].icon_custom_emoji_id


@pytest.mark.asyncio
async def test_consent_ambiguous_send_never_retries():
    import pytest
    from types import SimpleNamespace as NS
    from unittest.mock import AsyncMock
    from agent.modules.federations.roles import invitation_keyboard
    from agent.utils.rich import send
    client = NS(send_message=AsyncMock(side_effect=TimeoutError()))
    with pytest.raises(TimeoutError):
        await send(client,22,'Invitation',reply_markup=invitation_keyboard(Theme(),'token'))
    client.send_message.assert_awaited_once()


@pytest.mark.asyncio
async def test_required_channel_join_button_keeps_verified_url():
    from types import SimpleNamespace as NS
    from unittest.mock import AsyncMock
    from pyrogram.enums import ChatMemberStatus, ChatType
    from agent.modules.linkshare.subscription import allowed
    theme = Theme()
    ctx = NS(theme=theme,db=NS(connected=True,get=lambda *a: {'channel':-100}))
    client = NS(get_chat_member=AsyncMock(return_value=NS(status=ChatMemberStatus.LEFT)),
                get_chat=AsyncMock(return_value=NS(id=-100,type=ChatType.CHANNEL,username='PublicChannel')))
    message = NS(from_user=NS(id=22),reply=AsyncMock())
    assert not await allowed(ctx,client,message)
    button = message.reply.await_args.kwargs['reply_markup'].inline_keyboard[0][0]
    assert button.url == 'https://t.me/PublicChannel'
    assert button.icon_custom_emoji_id == theme.emoji_id('add')
    assert button.style == ButtonStyle.PRIMARY
