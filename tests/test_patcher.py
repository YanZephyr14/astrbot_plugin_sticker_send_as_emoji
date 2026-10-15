"""AiocqhttpPatcher 单元测试。"""

import pytest
from unittest.mock import AsyncMock, MagicMock
from astrbot.api.message_components import Image, Plain
from astrbot.core.platform.sources.aiocqhttp.aiocqhttp_message_event import (
    AiocqhttpMessageEvent,
)
from data.plugins.astrbot_plugin_sticker_send_as_emoji.matcher import (
    IN_STICKER_CONTEXT,
    StickerMatcher,
)
from data.plugins.astrbot_plugin_sticker_send_as_emoji.patcher import (
    AiocqhttpPatcher,
)


@pytest.fixture(autouse=True)
def clean_patcher_state():
    """每个测试前后确保还原补丁状态。"""
    yield
    # 清理卸载
    matcher = StickerMatcher()
    patcher = AiocqhttpPatcher(matcher=matcher)
    patcher.uninstall()


def test_install_and_uninstall_idempotency():
    orig_func = AiocqhttpMessageEvent._from_segment_to_dict
    orig_dispatch = AiocqhttpMessageEvent._dispatch_send

    matcher = StickerMatcher()
    patcher = AiocqhttpPatcher(matcher=matcher)

    # 首次挂载
    assert patcher.install()
    patched_func = AiocqhttpMessageEvent._from_segment_to_dict
    assert patched_func != orig_func

    # 重复挂载应幂等成功
    assert patcher.install()

    # 卸载
    patcher.uninstall()
    assert AiocqhttpMessageEvent._from_segment_to_dict == orig_func
    assert AiocqhttpMessageEvent._dispatch_send == orig_dispatch


@pytest.mark.asyncio
async def test_from_segment_to_dict_injects_sub_type():
    matcher = StickerMatcher(mode="smart")
    patcher = AiocqhttpPatcher(matcher=matcher, sub_type=1)
    patcher.install()

    meme_img = Image(file="data/plugins/astrbot_plugin_meme_manager/memes/joy/1.jpg")
    object.__setattr__(
        meme_img, "convert_to_base64", AsyncMock(return_value="mock_base64")
    )

    d = await AiocqhttpMessageEvent._from_segment_to_dict(meme_img)
    assert d["type"] == "image"
    assert d["data"]["sub_type"] == 1
    assert d["data"]["file"] == "base64://mock_base64"


@pytest.mark.asyncio
async def test_from_segment_to_dict_ignores_ordinary_photo():
    matcher = StickerMatcher(mode="smart")
    patcher = AiocqhttpPatcher(matcher=matcher, sub_type=1)
    patcher.install()

    photo = Image(file="C:/Users/Pictures/vacation.jpg")
    object.__setattr__(
        photo, "convert_to_base64", AsyncMock(return_value="photo_base64")
    )

    d = await AiocqhttpMessageEvent._from_segment_to_dict(photo)
    assert d["type"] == "image"
    assert "sub_type" not in d["data"]


@pytest.mark.asyncio
async def test_from_segment_to_dict_disabled():
    matcher = StickerMatcher(mode="all_images")
    patcher = AiocqhttpPatcher(matcher=matcher, enabled=False)
    patcher.install()

    meme_img = Image(file="data/plugins/astrbot_plugin_meme_manager/memes/joy/1.jpg")
    object.__setattr__(
        meme_img, "convert_to_base64", AsyncMock(return_value="mock_base64")
    )

    d = await AiocqhttpMessageEvent._from_segment_to_dict(meme_img)
    assert "sub_type" not in d["data"]


@pytest.mark.asyncio
async def test_from_segment_to_dict_exception_resilience():
    broken_matcher = MagicMock()
    broken_matcher.is_sticker.side_effect = RuntimeError("Simulated failure")

    patcher = AiocqhttpPatcher(matcher=broken_matcher, enabled=True, debug=True)
    patcher.install()

    img = Image(file="test.png")
    object.__setattr__(
        img, "convert_to_base64", AsyncMock(return_value="mock_base64")
    )

    d = await AiocqhttpMessageEvent._from_segment_to_dict(img)
    assert d["type"] == "image"
    assert d["data"]["file"] == "base64://mock_base64"


@pytest.mark.asyncio
async def test_dispatch_send_safety_net():
    matcher = StickerMatcher(mode="smart")
    patcher = AiocqhttpPatcher(matcher=matcher, sub_type=1)
    patcher.install()

    mock_bot = MagicMock()
    mock_bot.send_group_msg = AsyncMock()

    messages = [
        {"type": "text", "data": {"text": "看看表情"}},
        {
            "type": "image",
            "data": {
                "file": "data/plugins/astrbot_plugin_meme_manager/memes/test.jpg"
            },
        },
    ]

    await AiocqhttpMessageEvent._dispatch_send(
        mock_bot, None, True, "123456", messages
    )
    sent_msgs = mock_bot.send_group_msg.call_args[1]["message"]
    img_seg = sent_msgs[1]
    assert img_seg["data"]["sub_type"] == 1
