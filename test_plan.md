# 测试方案与验收用例 (test_plan.md)

## 1. 测试范围

针对 `astrbot_plugin_sticker_send_as_emoji` 插件的核心功能进行全面覆盖测试：
- **匹配器单元测试** (`matcher.py`)：显式属性判定、meme_manager 路径判定、动图识别、模式切换（smart / meme_only / all_images）。
- **补丁器单元测试** (`patcher.py`)：`_from_segment_to_dict` 注入、sub_type 保持既有值不覆盖、异常时放行容错、补丁挂载与卸载幂等性。
- **插件主体集成测试** (`main.py`)：生命周期加载、配置解析与热变更响应、`/sticker` 指令触发（status, toggle, test）。

---

## 2. 具体测试用例设计

### 用例 1: 属性标记优先识别
- **输入**：带有 `segment.sub_type = 1` 或 `segment.is_emoji = True` 的 `Comp.Image`
- **预期**：`matcher.is_sticker(segment)` 返回 `True`，且 `segment.sub_type` 被保留。

### 用例 2: meme_manager 路径匹配
- **输入**：`Image.fromFileSystem("data/plugins/astrbot_plugin_meme_manager/memes/happy/cat.jpg")`
- **预期**：在 `smart` 与 `meme_only` 模式下均判定为 `True`，成功注入 `sub_type=1`。

### 用例 3: 普通照片与大图不误伤
- **输入**：`Image.fromFileSystem("/home/user/photos/scenery.png")`
- **预期**：在 `smart` 与 `meme_only` 模式下均判定为 `False`，转换得到的字典中**不含** `sub_type`（或保持为 0），保留为普通大图。

### 用例 4: GIF 动图判定
- **输入**：普通路径下的动图 `sample.gif`
- **预期**：在 `treat_gif_as_emoji=True` 时判定为 `True`；在 `treat_gif_as_emoji=False` 时判定为 `False`。

### 用例 5: 补丁注入与异常放行
- **输入**：调用补丁后的 `AiocqhttpMessageEvent._from_segment_to_dict`
- **预期**：表情图片返回 `{"type": "image", "data": {"file": "...", "sub_type": 1}}`；如发生意外异常，静默降级为普通图片字典，绝不向上抛出异常。

### 用例 6: 补丁生命周期幂等性
- **输入**：连续调用 `install()` 两次，随后调用 `uninstall()`
- **预期**：不会出现双重包裹；`uninstall()` 恢复为原始的原型方法引用。
