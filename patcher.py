"""底层消息转换与协议发送补丁模块。

负责拦截 OneBot V11 (aiocqhttp) 的图片转换方法与发送出口，
精准注入 sub_type 字段，同时与 meme_manager 建立安全的双向联动。
"""

from typing import Any

from astrbot.api import logger
from astrbot.core.message.components import BaseMessageComponent
from astrbot.core.platform.sources.aiocqhttp.aiocqhttp_message_event import (
    AiocqhttpMessageEvent,
)

from .matcher import IN_STICKER_CONTEXT, StickerMatcher, mark_as_sticker

# 记录原始方法引用的全局字典，确保完全可逆与幂等
_ORIGINALS: dict[str, Any] = {}
_PATCH_INSTALLED = False


class AiocqhttpPatcher:
    """aiocqhttp 适配器与表情发送拦截补丁管理器。"""

    def __init__(
        self,
        matcher: StickerMatcher,
        enabled: bool = True,
        sub_type: int = 1,
        debug: bool = False,
    ) -> None:
        """初始化补丁器。

        Args:
            matcher: 表情匹配引擎实例.
            enabled: 是否启用补丁.
            sub_type: 表情标记值（默认 1）.
            debug: 是否输出调试日志.
        """
        self.matcher = matcher
        self.enabled = bool(enabled)
        self.sub_type = int(sub_type)
        self.debug = bool(debug)
        self._meme_manager_patched = False

    def update_config(
        self,
        enabled: bool | None = None,
        sub_type: int | None = None,
        debug: bool | None = None,
    ) -> None:
        """更新运行配置。"""
        if enabled is not None:
            self.enabled = bool(enabled)
        if sub_type is not None:
            self.sub_type = int(sub_type)
        if debug is not None:
            self.debug = bool(debug)

    def install(self) -> bool:
        """挂载核心补丁。

        Returns:
            bool: 是否成功安装
        """
        global _PATCH_INSTALLED
        if _PATCH_INSTALLED:
            if self.debug:
                logger.debug(
                    "[sticker_send_as_emoji] 补丁已处于安装状态，跳过重复挂载。"
                )
            return True

        try:
            # 1. 拦截 AiocqhttpMessageEvent._from_segment_to_dict
            orig_from_segment = AiocqhttpMessageEvent._from_segment_to_dict
            _ORIGINALS["AiocqhttpMessageEvent._from_segment_to_dict"] = (
                orig_from_segment
            )

            async def patched_from_segment_to_dict(
                segment: BaseMessageComponent,
            ) -> dict:
                d = await orig_from_segment(segment)
                if not self.enabled:
                    return d

                try:
                    if isinstance(d, dict) and d.get("type") == "image":
                        data = d.get("data")
                        if isinstance(data, dict):
                            # 如果已有非 None 的 sub_type，保留调用方的显式设置
                            if "sub_type" not in data or data["sub_type"] is None:
                                if self.matcher.is_sticker(segment):
                                    data["sub_type"] = self.sub_type
                                    if self.debug:
                                        logger.debug(
                                            f"[sticker_send_as_emoji] 已为图片段注入 sub_type={self.sub_type}: "
                                            f"segment={segment.__class__.__name__}"
                                        )
                except Exception as exc:
                    # 防御性放行：绝不阻断正常消息发送
                    if self.debug:
                        logger.warning(
                            f"[sticker_send_as_emoji] 注入 sub_type 异常（本次按普通图片发送）: {exc}"
                        )
                return d

            AiocqhttpMessageEvent._from_segment_to_dict = staticmethod(
                patched_from_segment_to_dict
            )

            # 2. 拦截 AiocqhttpMessageEvent._dispatch_send 作为兜底防线
            orig_dispatch_send = AiocqhttpMessageEvent._dispatch_send
            _ORIGINALS["AiocqhttpMessageEvent._dispatch_send"] = orig_dispatch_send

            @classmethod
            async def patched_dispatch_send(
                cls,
                bot: Any,
                event: Any,
                is_group: bool,
                session_id: str | None,
                messages: list[dict],
            ) -> None:
                if self.enabled and isinstance(messages, list):
                    try:
                        for seg in messages:
                            if isinstance(seg, dict) and seg.get("type") == "image":
                                data = seg.get("data")
                                if isinstance(data, dict):
                                    if (
                                        "sub_type" not in data
                                        or data["sub_type"] is None
                                    ):
                                        file_val = data.get("file", "")
                                        # 如果在表情上下文，或处于全量模式，或匹配已知路径
                                        if (
                                            IN_STICKER_CONTEXT.get()
                                            or self.matcher.mode == "all_images"
                                            or (
                                                file_val
                                                and self.matcher._is_path_in_known_dirs(
                                                    str(file_val)
                                                )
                                            )
                                        ):
                                            data["sub_type"] = self.sub_type
                                            if self.debug:
                                                logger.debug(
                                                    f"[sticker_send_as_emoji] dispatch_send 补齐 sub_type={self.sub_type}"
                                                )
                    except Exception as exc:
                        if self.debug:
                            logger.warning(
                                f"[sticker_send_as_emoji] dispatch_send 补齐异常: {exc}"
                            )

                return await orig_dispatch_send.__func__(
                    cls, bot, event, is_group, session_id, messages
                )

            AiocqhttpMessageEvent._dispatch_send = patched_dispatch_send

            # 3. 尝试联动 meme_manager
            self._try_hook_meme_manager()

            _PATCH_INSTALLED = True
            logger.info(
                f"[sticker_send_as_emoji] 表情转换补丁挂载成功！(enabled={self.enabled}, sub_type={self.sub_type})"
            )
            return True

        except Exception as e:
            logger.error(f"[sticker_send_as_emoji] 挂载补丁失败: {e}", exc_info=True)
            return False

    def _try_hook_meme_manager(self) -> bool:
        """安全尝试联动 meme_manager，为其表情分发打上上下文标记与对象属性。"""
        try:
            # 尝试导入 meme_manager 的混入类
            target_cls = None
            try:
                from astrbot_plugin_meme_manager.mixins.event_handlers import (  # type: ignore
                    EventHandlers,
                )

                target_cls = EventHandlers
            except ImportError:
                try:
                    from meme_manager.mixins.event_handlers import (  # type: ignore
                        EventHandlers,
                    )

                    target_cls = EventHandlers
                except ImportError:
                    pass

            if not target_cls:
                if self.debug:
                    logger.debug(
                        "[sticker_send_as_emoji] 未发现已导入的 meme_manager 模块，将纯依靠路径与特征识别。"
                    )
                return False

            # Hook 1: _send_meme_image
            if hasattr(target_cls, "_send_meme_image"):
                orig_send_meme = getattr(target_cls, "_send_meme_image")
                if not getattr(orig_send_meme, "_sticker_hooked", False):
                    _ORIGINALS["meme_manager._send_meme_image"] = orig_send_meme

                    async def hooked_send_meme_image(
                        inst: Any, event: Any, image: Any
                    ) -> None:
                        token = IN_STICKER_CONTEXT.set(True)
                        try:
                            # 显式打上标记
                            mark_as_sticker(image, self.sub_type)
                            return await orig_send_meme(inst, event, image)
                        finally:
                            IN_STICKER_CONTEXT.reset(token)

                    hooked_send_meme_image._sticker_hooked = True  # type: ignore
                    setattr(target_cls, "_send_meme_image", hooked_send_meme_image)
                    if self.debug:
                        logger.debug(
                            "[sticker_send_as_emoji] 已安全包裹 meme_manager._send_meme_image"
                        )

            # Hook 2: _merge_components_with_images (混合消息)
            if hasattr(target_cls, "_merge_components_with_images"):
                orig_merge = getattr(target_cls, "_merge_components_with_images")
                if not getattr(orig_merge, "_sticker_hooked", False):
                    _ORIGINALS["meme_manager._merge_components_with_images"] = (
                        orig_merge
                    )

                    def hooked_merge_components_with_images(
                        inst: Any, components: Any, images: Any
                    ) -> Any:
                        if isinstance(images, list):
                            for img in images:
                                mark_as_sticker(img, self.sub_type)
                        return orig_merge(inst, components, images)

                    hooked_merge_components_with_images._sticker_hooked = True  # type: ignore
                    setattr(
                        target_cls,
                        "_merge_components_with_images",
                        hooked_merge_components_with_images,
                    )
                    if self.debug:
                        logger.debug(
                            "[sticker_send_as_emoji] 已安全包裹 meme_manager._merge_components_with_images"
                        )

            self._meme_manager_patched = True
            logger.info(
                "[sticker_send_as_emoji] 成功与 meme_manager 建立直接上下文联动！"
            )
            return True

        except Exception as e:
            if self.debug:
                logger.warning(
                    f"[sticker_send_as_emoji] 联动 meme_manager 时发生轻微异常 (不影响常规运作): {e}"
                )
            return False

    def uninstall(self) -> None:
        """卸载所有打过的补丁，完全恢复系统原有状态。"""
        global _PATCH_INSTALLED

        # 1. 还原 AiocqhttpMessageEvent._from_segment_to_dict
        if "AiocqhttpMessageEvent._from_segment_to_dict" in _ORIGINALS:
            AiocqhttpMessageEvent._from_segment_to_dict = _ORIGINALS[
                "AiocqhttpMessageEvent._from_segment_to_dict"
            ]
            del _ORIGINALS["AiocqhttpMessageEvent._from_segment_to_dict"]

        # 2. 还原 AiocqhttpMessageEvent._dispatch_send
        if "AiocqhttpMessageEvent._dispatch_send" in _ORIGINALS:
            AiocqhttpMessageEvent._dispatch_send = _ORIGINALS[
                "AiocqhttpMessageEvent._dispatch_send"
            ]
            del _ORIGINALS["AiocqhttpMessageEvent._dispatch_send"]

        # 3. 还原 meme_manager
        target_cls = None
        for mod_name in ("astrbot_plugin_meme_manager", "meme_manager"):
            try:
                import sys

                if mod_name in sys.modules:
                    target_cls = getattr(
                        sys.modules[mod_name].mixins.event_handlers,
                        "EventHandlers",
                        None,
                    )
                    if target_cls:
                        break
            except Exception:
                pass

        if target_cls:
            if "meme_manager._send_meme_image" in _ORIGINALS:
                setattr(
                    target_cls,
                    "_send_meme_image",
                    _ORIGINALS["meme_manager._send_meme_image"],
                )
                del _ORIGINALS["meme_manager._send_meme_image"]

            if "meme_manager._merge_components_with_images" in _ORIGINALS:
                setattr(
                    target_cls,
                    "_merge_components_with_images",
                    _ORIGINALS["meme_manager._merge_components_with_images"],
                )
                del _ORIGINALS["meme_manager._merge_components_with_images"]

        _PATCH_INSTALLED = False
        self._meme_manager_patched = False
        logger.info("[sticker_send_as_emoji] 表情转换补丁已成功卸载并还原。")
