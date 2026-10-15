"""表情按「表情」发送 (Sticker Send As Emoji) 辅助插件主入口。

让机器人发的表情以 QQ「表情」形式呈现（小图、紧凑、可长按收藏），而不是一张撑满气泡的大图。
能无缝配合 meme_manager 等表情管理插件。
"""

from pathlib import Path
from typing import Any

import astrbot.api.message_components as Comp
from astrbot.api import logger
from astrbot.api.event import AstrMessageEvent, filter
from astrbot.api.star import Context, Star

from .matcher import StickerMatcher, mark_as_sticker
from .patcher import AiocqhttpPatcher


class StickerSendAsEmojiPlugin(Star):
    """Sticker Send As Emoji 插件核心类。"""

    def __init__(self, context: Context, config: dict | None = None) -> None:
        """初始化插件。

        Args:
            context: AstrBot 插件运行上下文.
            config: WebUI 配置字典.
        """
        super().__init__(context)
        self.config = config or {}

        # 初始化匹配引擎与底层补丁
        self.matcher = StickerMatcher(
            mode=self.config.get("mode", "smart"),
            treat_gif_as_emoji=self.config.get("treat_gif_as_emoji", True),
            extra_dirs=self.config.get("extra_dirs", []),
            debug=self.config.get("debug", False),
        )
        self.patcher = AiocqhttpPatcher(
            matcher=self.matcher,
            enabled=self.config.get("enabled", True),
            sub_type=self.config.get("sub_type", 1),
            debug=self.config.get("debug", False),
        )

    async def initialize(self) -> None:
        """异步生命周期初始化：挂载底层消息转换补丁并建立联动。"""
        try:
            kv_enabled = await self.get_kv_data("enabled", None)
            if kv_enabled is not None:
                self.patcher.enabled = bool(kv_enabled)
        except Exception:
            pass

        self.patcher.install()
        logger.info(
            f"[sticker_send_as_emoji] 插件已就绪！当前识别模式: {self.matcher.mode}, "
            f"标记值: sub_type={self.patcher.sub_type}, 启用状态: {self.patcher.enabled}"
        )

    async def terminate(self) -> None:
        """插件销毁生命周期：干净卸载所有打过的补丁，还原系统状态。"""
        self.patcher.uninstall()

    @filter.on_decorating_result(priority=50)
    async def on_decorating_result(self, event: AstrMessageEvent) -> None:
        """在最终回复消息组装前，扫描消息链中的图片组件并打上表情标记。

        Args:
            event: 消息事件对象
        """
        if not self.patcher.enabled:
            return

        result = event.get_result()
        if not result or not result.chain:
            return

        # 遍历消息链，为符合判定条件的图片赋予属性
        for comp in result.chain:
            if (
                isinstance(comp, Comp.Image)
                or getattr(comp, "type", None) == Comp.ComponentType.Image
            ):
                if self.matcher.is_sticker(comp):
                    mark_as_sticker(comp, self.patcher.sub_type)

    # ──────────────── 指令组管理 ────────────────

    @filter.command_group(
        "semoji",
        alias={"emojisticker", "sticker_emoji", "表情样式", "表情形态"},
    )
    def semoji(self) -> None:
        """表情标记辅助工具指令组（与 sticker_sense 严格隔离避免冲突）"""
        pass

    @semoji.command("status")
    async def status(self, event: AstrMessageEvent) -> Any:
        """查看表情按表情发送当前运行状态与配置"""
        from .patcher import _PATCH_INSTALLED

        known_count = len(self.matcher.get_known_dirs())
        meme_hooked = self.patcher._meme_manager_patched

        msg = (
            "【表情发送辅助插件状态】\n"
            f"• 启用状态: {'🟢 开启' if self.patcher.enabled else '🔴 关闭'}\n"
            f"• 补丁挂载: {'✅ 已挂载' if _PATCH_INSTALLED else '❌ 未挂载'}\n"
            f"• 标记数值 (sub_type): {self.patcher.sub_type} (1=表情, 0=普通大图)\n"
            f"• 识别模式: {self.matcher.mode}\n"
            f"• GIF视为表情: {'是' if self.matcher.treat_gif_as_emoji else '否'}\n"
            f"• meme_manager联动: {'✅ 深度联动已激活' if meme_hooked else 'ℹ️ 基于路径与上下文感知'}\n"
            f"• 已索引表情目录数: {known_count} 个\n"
            "💡 可用指令: /semoji status, /semoji toggle, /semoji test (支持别名 /emojisticker, /表情样式)"
        )
        yield event.plain_result(msg)

    @semoji.command("toggle")
    async def toggle(self, event: AstrMessageEvent) -> Any:
        """快速切换表情发送辅助插件的启用/禁用状态并持久化"""
        self.patcher.enabled = not self.patcher.enabled
        try:
            await self.put_kv_data("enabled", self.patcher.enabled)
        except Exception:
            pass
        state_str = (
            "🟢 开启 (表情将以小图/可长按收藏发送)"
            if self.patcher.enabled
            else "🔴 关闭 (表情将按普通大图发送)"
        )
        yield event.plain_result(f"已切换状态为: {state_str}")

    @semoji.command("test")
    async def test(self, event: AstrMessageEvent) -> Any:
        """发送一张测试表情图片，验证 QQ 客户端是否以表情样式呈现"""
        assets_path = Path(__file__).parent / "assets" / "test_sticker.png"
        if not assets_path.exists():
            yield event.plain_result("❌ 未找到测试表情素材文件。")
            return

        yield event.plain_result(
            "正在发送测试表情包（手机端应展示为小图、且可长按收藏）..."
        )
        test_img = Comp.Image.fromFileSystem(str(assets_path))
        mark_as_sticker(test_img, self.patcher.sub_type)

        yield event.chain_result([test_img])
