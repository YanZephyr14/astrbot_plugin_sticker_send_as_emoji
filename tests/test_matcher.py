"""StickerMatcher 单元测试。"""

from pathlib import Path
from astrbot.api.message_components import Image, Plain
from data.plugins.astrbot_plugin_sticker_send_as_emoji.matcher import (
    IN_STICKER_CONTEXT,
    StickerMatcher,
    mark_as_sticker,
)


def test_non_image_segment_rejected():
    matcher = StickerMatcher()
    plain = Plain(text="hello")
    assert not matcher.is_sticker(plain)


def test_explicit_sub_type_attribute():
    matcher = StickerMatcher()
    img = Image(file="http://example.com/test.png")

    mark_as_sticker(img, sub_type=1)
    assert matcher.is_sticker(img)

    object.__setattr__(img, "sub_type", 0)
    assert not matcher.is_sticker(img)

    del img.__dict__["sub_type"]
    object.__setattr__(img, "is_emoji", True)
    assert matcher.is_sticker(img)

    del img.__dict__["is_emoji"]
    object.__setattr__(img, "is_sticker", True)
    assert matcher.is_sticker(img)


def test_in_sticker_context():
    matcher = StickerMatcher()
    img = Image(file="http://example.com/random_picture.png")

    assert not matcher.is_sticker(img)

    token = IN_STICKER_CONTEXT.set(True)
    try:
        assert matcher.is_sticker(img)
    finally:
        IN_STICKER_CONTEXT.reset(token)

    assert not matcher.is_sticker(img)


def test_meme_manager_path_matching():
    matcher = StickerMatcher(mode="smart")
    meme_img = Image(
        file="data/plugins/astrbot_plugin_meme_manager/memes/happy/dog.jpg"
    )
    assert matcher.is_sticker(meme_img)

    plugin_data_meme = Image(
        file="data/plugin_data/astrbot_plugin_meme_manager/memes/sad/cat.png"
    )
    assert matcher.is_sticker(plugin_data_meme)


def test_ordinary_photo_excluded():
    matcher = StickerMatcher(mode="smart", treat_gif_as_emoji=True)
    ordinary_photo = Image(file="C:/Users/Pictures/scenery.png")
    assert not matcher.is_sticker(ordinary_photo)


def test_gif_detection_in_smart_mode():
    matcher_gif_on = StickerMatcher(mode="smart", treat_gif_as_emoji=True)
    gif_img = Image(file="C:/Users/Pictures/dance.gif")
    assert matcher_gif_on.is_sticker(gif_img)

    matcher_gif_off = StickerMatcher(mode="smart", treat_gif_as_emoji=False)
    assert not matcher_gif_off.is_sticker(gif_img)


def test_all_images_mode():
    matcher = StickerMatcher(mode="all_images")
    ordinary_photo = Image(file="C:/Users/Pictures/scenery.png")
    assert matcher.is_sticker(ordinary_photo)


def test_extra_dirs():
    custom_dir = Path("data/custom_stickers").resolve()
    matcher = StickerMatcher(mode="meme_only", extra_dirs=[str(custom_dir)])
    custom_img = Image(file=str(custom_dir / "funny.png"))
    assert matcher.is_sticker(custom_img)


def test_update_config():
    matcher = StickerMatcher(mode="meme_only", treat_gif_as_emoji=False)
    gif_img = Image(file="C:/Users/Pictures/dance.gif")
    assert not matcher.is_sticker(gif_img)

    matcher.update_config(mode="smart", treat_gif_as_emoji=True)
    assert matcher.is_sticker(gif_img)
