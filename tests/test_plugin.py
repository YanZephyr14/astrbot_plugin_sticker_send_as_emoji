"""StickerSendAsEmojiPlugin 集成测试。"""

import pytest
from unittest.mock import AsyncMock, MagicMock
from astrbot.api.event import AstrMessageEvent, MessageChain
from astrbot.api.message_components import Image, Plain
from astrbot.api.star import Context
from data.plugins.astrbot_plugin_sticker_send_as_emoji.main import (
    StickerSendAsEmojiPlugin,
)


@pytest.fixture
def dummy_context():
    ctx = MagicMock(spec=Context)
    return ctx


@pytest.mark.asyncio
async def test_plugin_lifecycle(dummy_context):
    plugin = StickerSendAsEmojiPlugin(
        dummy_context, config={"enabled": True, "sub_type": 1}
    )
    await plugin.initialize()
    assert plugin.patcher.enabled is True
    assert plugin.patcher.sub_type == 1

    await plugin.terminate()


@pytest.mark.asyncio
async def test_on_decorating_result_tags_images(dummy_context):
    plugin = StickerSendAsEmojiPlugin(
        dummy_context, config={"enabled": True, "mode": "smart"}
    )
    await plugin.initialize()

    mock_event = MagicMock(spec=AstrMessageEvent)
    mock_result = MagicMock()
    meme_img = Image(file="data/plugins/astrbot_plugin_meme_manager/memes/happy/smile.png")
    text = Plain(text="你好呀")
    mock_result.chain = [text, meme_img]
    mock_event.get_result.return_value = mock_result

    await plugin.on_decorating_result(mock_event)

    assert getattr(meme_img, "sub_type", None) == 1
    assert getattr(meme_img, "is_emoji", False) is True

    await plugin.terminate()


@pytest.mark.asyncio
async def test_command_status(dummy_context):
    plugin = StickerSendAsEmojiPlugin(dummy_context)
    await plugin.initialize()

    mock_event = MagicMock(spec=AstrMessageEvent)
    mock_event.plain_result = lambda text: text

    results = []
    async for res in plugin.status(mock_event):
        results.append(res)

    assert len(results) == 1
    assert "【表情发送辅助插件状态】" in results[0]
    assert "🟢 开启" in results[0]

    await plugin.terminate()


@pytest.mark.asyncio
async def test_command_toggle(dummy_context):
    plugin = StickerSendAsEmojiPlugin(dummy_context, config={"enabled": True})
    await plugin.initialize()

    mock_event = MagicMock(spec=AstrMessageEvent)
    mock_event.plain_result = lambda text: text

    results = []
    async for res in plugin.toggle(mock_event):
        results.append(res)

    assert plugin.patcher.enabled is False
    assert "🔴 关闭" in results[0]

    # 再次 toggle
    results.clear()
    async for res in plugin.toggle(mock_event):
        results.append(res)
    assert plugin.patcher.enabled is True
    assert "🟢 开启" in results[0]

    await plugin.terminate()


@pytest.mark.asyncio
async def test_command_test(dummy_context):
    plugin = StickerSendAsEmojiPlugin(dummy_context)
    await plugin.initialize()

    mock_event = MagicMock(spec=AstrMessageEvent)
    mock_event.plain_result = lambda text: text
    mock_event.chain_result = lambda chain: chain

    results = []
    async for res in plugin.test(mock_event):
        results.append(res)

    assert len(results) == 2
    assert "正在发送测试表情包" in results[0]
    test_chain = results[1]
    assert isinstance(test_chain, list)
    assert isinstance(test_chain[0], Image)
    assert getattr(test_chain[0], "sub_type", None) == 1
    assert getattr(test_chain[0], "is_emoji", False) is True

    await plugin.terminate()
