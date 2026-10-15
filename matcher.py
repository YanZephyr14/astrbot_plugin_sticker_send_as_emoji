"""表情与图片分类匹配引擎。

负责多维度精准判定待发送图片是否属于表情包（Sticker），
并支持与 meme_manager 的动态联动与智能识别。
"""

import contextvars
from pathlib import Path
from typing import Any

from astrbot.api import logger

# 异步上下文标记：标识当前调用链是否处于显式的表情发送流程中
IN_STICKER_CONTEXT: contextvars.ContextVar[bool] = contextvars.ContextVar(
    "in_sticker_context", default=False
)


def mark_as_sticker(segment: Any, sub_type: int = 1) -> None:
    """安全为消息组件注入表情标记属性（绕过 Pydantic v1 BaseModel 字段拦截）。

    Args:
        segment: 消息组件（通常为 Comp.Image）
        sub_type: 表情标记数值，默认 1
    """
    try:
        object.__setattr__(segment, "sub_type", int(sub_type))
        object.__setattr__(segment, "is_emoji", True)
    except Exception:
        pass


class StickerMatcher:
    """表情匹配判定器。"""

    def __init__(
        self,
        mode: str = "smart",
        treat_gif_as_emoji: bool = True,
        extra_dirs: list[str] | None = None,
        debug: bool = False,
    ) -> None:
        """初始化匹配器。

        Args:
            mode: 识别模式，可选 "smart" (智能匹配), "meme_only" (仅表情插件), "all_images" (全部图片).
            treat_gif_as_emoji: 是否将所有 GIF 动图视为表情包.
            extra_dirs: 自定义表情目录列表.
            debug: 是否输出调试日志.
        """
        self.mode = mode if mode in {"smart", "meme_only", "all_images"} else "smart"
        self.treat_gif_as_emoji = bool(treat_gif_as_emoji)
        self.debug = bool(debug)
        self._known_meme_dirs: set[str] = set()

        if extra_dirs:
            for d in extra_dirs:
                if d and isinstance(d, str):
                    self.add_known_dir(d)

        # 默认探测常见表情包根路径
        self._discover_default_meme_dirs()

    def update_config(
        self,
        mode: str | None = None,
        treat_gif_as_emoji: bool | None = None,
        extra_dirs: list[str] | None = None,
        debug: bool | None = None,
    ) -> None:
        """动态更新配置。"""
        if mode is not None:
            self.mode = (
                mode if mode in {"smart", "meme_only", "all_images"} else "smart"
            )
        if treat_gif_as_emoji is not None:
            self.treat_gif_as_emoji = bool(treat_gif_as_emoji)
        if debug is not None:
            self.debug = bool(debug)
        if extra_dirs is not None:
            for d in extra_dirs:
                if d and isinstance(d, str):
                    self.add_known_dir(d)

    def add_known_dir(self, directory: str | Path) -> None:
        """注册已知的表情包文件目录。

        Args:
            directory: 目录路径或 Path 对象.
        """
        try:
            p = Path(directory).resolve()
            normalized = str(p).lower().replace("\\", "/")
            self._known_meme_dirs.add(normalized)
            if self.debug:
                logger.debug(f"[sticker_send_as_emoji] 注册已知表情目录: {normalized}")
        except Exception as e:
            if self.debug:
                logger.warning(f"[sticker_send_as_emoji] 添加表情目录异常: {e}")

    def get_known_dirs(self) -> set[str]:
        """获取所有已注册的已知表情目录规范路径。"""
        return set(self._known_meme_dirs)

    def _discover_default_meme_dirs(self) -> None:
        """自动探测并注册标准表情包与 meme_manager 相关目录。"""
        candidates = [
            # 常见 AstrBot 插件与持久化数据目录
            "data/plugins/astrbot_plugin_meme_manager/memes",
            "data/plugins/meme_manager/memes",
            "data/plugin_data/astrbot_plugin_meme_manager",
            "data/plugin_data/meme_manager",
            "data/plugins/astrbot_plugin_meme_manager",
            "data/plugins/meme_manager",
        ]
        for c in candidates:
            p = Path(c)
            if p.exists():
                self.add_known_dir(p)

    def _is_path_in_known_dirs(self, file_path: str) -> bool:
        """检查文件路径是否属于已知表情目录或典型表情包命名规律。"""
        if not file_path:
            return False

        norm_path = file_path.lower().replace("\\", "/")

        # 1. 严格前缀匹配
        for known in self._known_meme_dirs:
            if norm_path.startswith(known):
                return True

        # 2. 启发式特征匹配：路径包含关键目录段
        indicators = [
            "/memes/",
            "/meme/",
            "/stickers/",
            "/emotions/",
            "plugin_data/astrbot_plugin_meme_manager",
            "plugin_data/meme_manager",
            "astrbot_plugin_meme_manager/memes",
        ]
        return any(ind in norm_path for ind in indicators)

    def is_sticker(self, segment: Any, explicit_sub_type: int | None = None) -> bool:
        """核心判定：判断给定的消息组件是否应该以表情形式发送。

        Args:
            segment: AstrBot 消息组件（通常为 Comp.Image）
            explicit_sub_type: 组件若已有显式 sub_type

        Returns:
            bool: 是否判定为表情
        """
        # 1. 如果不是图片组件，直接否决
        type_name = getattr(segment, "type", None)
        type_str = str(type_name).lower() if type_name else ""
        if "image" not in type_str:
            return False

        # 2. 全量模式：所有图片一律作为表情
        if self.mode == "all_images":
            return True

        # 3. 显式属性优先检查
        seg_dict = getattr(segment, "__dict__", {})
        sub_type_val = getattr(segment, "sub_type", None)
        if sub_type_val is None:
            sub_type_val = seg_dict.get("sub_type")
        if sub_type_val is None:
            sub_type_val = explicit_sub_type

        if sub_type_val == 1:
            return True
        elif sub_type_val == 0:
            # 显式指定了普通图片，不予覆盖
            return False

        # 3.2 携带表情标志位
        if any(
            getattr(segment, flag, False) is True or seg_dict.get(flag) is True
            for flag in ("is_emoji", "is_sticker", "_is_meme", "as_sticker")
        ):
            return True

        # 4. 处于表情发送上下文栈中 (例如 meme_manager 发送期间)
        if IN_STICKER_CONTEXT.get():
            return True

        # 5. 提取图片可能的文件路径
        file_cand = (
            getattr(segment, "path", None)
            or getattr(segment, "file", None)
            or getattr(segment, "url", None)
            or ""
        )
        file_str = str(file_cand) if file_cand else ""

        # 6. 路径检测（meme_manager 图库、自定义目录等）
        if file_str and self._is_path_in_known_dirs(file_str):
            return True

        # 7. 动图检测（在 smart 模式下，若开启 treat_gif_as_emoji 则将 GIF 视为表情）
        if self.mode == "smart" and self.treat_gif_as_emoji:
            if file_str.lower().endswith((".gif", ".webp.gif")):
                return True

        # meme_only 模式或普通静态大图，均不视为表情
        return False
