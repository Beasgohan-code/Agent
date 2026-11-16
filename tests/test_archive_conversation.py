from types import SimpleNamespace as NS
from unittest.mock import AsyncMock
import pytest
from agent.modules.filestore.conversation import ArchiveConversation
from test_archive_links import request, context


@pytest.mark.asyncio
async def test_original_batch_prompt_sequence_and_single_completion():
    generate = AsyncMock()
    flow = ArchiveConversation(context(), generate)
    start = request("/batch")
    await flow.start(None, start, "batch")
    first = request("https://t.me/c/123/10")
    # Configured archive is -100; reject foreign references without advancing.
    await flow.receive(None, first)
    assert flow.state["ids"] == []
    first.forward_from_chat = NS(id=-100)
    first.forward_from_message_id = 10
    await flow.receive(None, first)
    last = request("")
    last.forward_from_chat = NS(id=-100)
    last.forward_from_message_id = 12
    await flow.receive(None, last)
    assert generate.await_args.args[1].text == "/custom_batch 10 12"
    await flow.receive(None, last)
    assert generate.await_count == 1


@pytest.mark.asyncio
async def test_custom_batch_done_cancellation_expiry_and_identity():
    generate = AsyncMock()
    clock = [0]
    flow = ArchiveConversation(context(), generate, clock=lambda: clock[0])
    await flow.start(None, request("/custom_batch"), "custom_batch")
    await flow.receive(None, request("/done"))
    generate.assert_not_awaited()
    foreign = request("/cancel", 22)
    await flow.receive(None, foreign)
    assert flow.state is not None
    await flow.receive(None, request("/cancel"))
    assert flow.state is None
    await flow.start(None, request("/custom_batch"), "custom_batch")
    item = request("")
    item.forward_from_chat = NS(id=-100)
    item.forward_from_message_id = 10
    await flow.receive(None, item)
    await flow.receive(None, request("/done"))
    assert generate.await_args.args[1].text == "/custom_batch 10 10"
    await flow.start(None, request("/batch"), "batch")
    clock[0] = 301
    await flow.receive(None, item)
    assert flow.state is None
    assert generate.await_count == 1
