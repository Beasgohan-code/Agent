"""Missing chat admin tools use current rights and explicit acknowledgements."""
from types import SimpleNamespace as NS
from unittest.mock import AsyncMock
import pytest
from pyrogram.enums import ChatMemberStatus as Status
from agent.modules import group
import test_group as fixtures


def setup(tmp_path,text):
    ctx=fixtures.ctx.__wrapped__(tmp_path)
    message=fixtures.FakeMessage(text)
    bot=NS(get_users=AsyncMock(return_value=NS(id=22)),get_me=AsyncMock(return_value=NS(id=99)),
           get_chat_member=AsyncMock(return_value=NS(status=Status.ADMINISTRATOR,privileges=NS(can_change_info=True,can_manage_chat=True))),
           set_chat_title=AsyncMock(return_value=True),set_chat_description=AsyncMock(return_value=True),set_chat_photo=AsyncMock(return_value=True))
    return group.build(ctx)[1],bot,message


@pytest.mark.asyncio
@pytest.mark.parametrize('command,method,value',[('setchatname','set_chat_title','New name'),('setchatdescription','set_chat_description','New description')])
async def test_chat_text_mutations_confirmed(tmp_path,command,method,value):
    handlers,bot,message=setup(tmp_path,'/'+command+' '+value)
    await handlers[command](bot,message)
    getattr(bot,method).assert_awaited_once_with(message.chat.id,value)
    assert 'confirmed' in str(message.replies[-1]).lower()


@pytest.mark.asyncio
async def test_denied_and_unconfirmed_changes_never_claim_success(tmp_path):
    handlers,bot,message=setup(tmp_path,'/setchatname New')
    bot.get_chat_member.return_value=NS(status=Status.MEMBER)
    await handlers['setchatname'](bot,message)
    bot.set_chat_title.assert_not_awaited()
    bot.get_chat_member.return_value=NS(status=Status.ADMINISTRATOR,privileges=NS(can_change_info=True))
    bot.set_chat_title.return_value=False
    await handlers['setchatname'](bot,message)
    assert 'unconfirmed' in str(message.replies[-1]).lower()


@pytest.mark.asyncio
async def test_setchatphoto_uses_valid_photo_reference_only(tmp_path):
    from pyrogram.file_id import FileId,FileType,ThumbnailSource
    handlers,bot,message=setup(tmp_path,'/setchatphoto')
    file_id=FileId(file_type=FileType.PHOTO,dc_id=2,media_id=1,access_hash=2,thumbnail_source=ThumbnailSource.THUMBNAIL,thumbnail_file_type=FileType.PHOTO,thumbnail_size='x').encode(minor=32)
    message.reply_to_message=NS(chat=message.chat,photo=NS(file_id=file_id))
    await handlers['setchatphoto'](bot,message)
    bot.set_chat_photo.assert_awaited_once_with(message.chat.id,photo=file_id)


@pytest.mark.asyncio
async def test_admincount_live_list_and_rights_card(tmp_path):
    handlers,bot,message=setup(tmp_path,'/admincount')
    async def members(*a,**k):
        for i in range(3):
            yield NS(user=NS(id=i+1),status=Status.ADMINISTRATOR)
    bot.get_chat_members=members
    await handlers['admincount'](bot,message)
    assert '3' in str(message.replies[-1])
    message.text='/rights 22'
    await handlers['rights'](bot,message)
    assert 'can_change_info' in str(message.replies[-1])


@pytest.mark.asyncio
@pytest.mark.parametrize('reference',['/etc/passwd','https://example.com/photo','not-a-photo-reference'])
async def test_photo_paths_and_urls_rejected(tmp_path,reference):
    handlers,bot,message=setup(tmp_path,'/setchatphoto')
    message.reply_to_message=NS(chat=message.chat,photo=NS(file_id=reference))
    await handlers['setchatphoto'](bot,message)
    bot.set_chat_photo.assert_not_awaited()


@pytest.mark.asyncio
async def test_api_errors_are_redacted_and_not_retried(tmp_path):
    handlers,bot,message=setup(tmp_path,'/setchatname New title')
    bot.set_chat_title.side_effect=ValueError('SECRET')
    await handlers['setchatname'](bot,message)
    bot.set_chat_title.assert_awaited_once()
    assert 'unconfirmed' in str(message.replies[-1]).lower()
    assert 'SECRET' not in str(message.replies[-1])


@pytest.mark.asyncio
async def test_final_caller_rights_loss_stops_mutation(tmp_path):
    handlers,bot,message=setup(tmp_path,'/setchatname New title')
    bot.get_chat_member.side_effect=[NS(status=Status.ADMINISTRATOR,privileges=NS(can_change_info=True)),NS(status=Status.ADMINISTRATOR,privileges=NS(can_change_info=True)),NS(status=Status.MEMBER)]
    await handlers['setchatname'](bot,message)
    bot.set_chat_title.assert_not_awaited()
