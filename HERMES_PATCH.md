# Hermes 主程序修改指南

本插件需要 Hermes 主程序中的 `gateway/platforms/feishu.py` 进行相应修改，以支持 Bot-to-Bot @ 通信。

## 修改目的

当飞书群聊中有其他机器人 @ 本机器人时，Hermes 需要在消息文本前注入发送者信息，让 Agent 知道如何 @ 回发送者：

```
[来自机器人「前端机器人」— 如需 @ 回请使用：<at user_id="ou_xxx">前端机器人</at>]

原始消息内容...
```

## 修改位置

**文件**: `gateway/platforms/feishu.py`  
**函数**: `FeishuAdapter._normalize_inbound()`  
**行号**: 约 2500 行（`sender_profile = await self._resolve_sender_profile(sender_id)` 之后）

## 具体修改

在 `sender_profile = await self._resolve_sender_profile(sender_id)` 这行之后，`source = self.build_source(...)` 这行之前，插入以下代码：

```python
# Bot-to-Bot @ support: detect if sender is a bot and inject sender info
# This enables A2A collaboration - when another bot @ this bot, inject
# "[来自机器人「xxx」— 如需 @ 回请使用：<at user_id="ou_xxx">xxx</at>]"
sender_type_hint = ""
event = getattr(data, "event", None)
sender_obj = getattr(event, "sender", None)
sender_type_raw = str(getattr(sender_obj, "sender_type", "") or "").strip().lower()
if sender_type_raw in {"bot", "app"}:
    sender_open_id = str(getattr(sender_id, "open_id", "") or "").strip()
    # Get bot name from sender_profile (may return None for bots)
    bot_sender_name = sender_profile.get("user_name") or None
    if not bot_sender_name:
        # Fallback: use open_id as name
        bot_sender_name = f"Bot({sender_open_id})"
    if sender_open_id and text:
        sender_type_hint = f"[来自机器人「{bot_sender_name}」— 如需 @ 回请使用：<at user_id=\"{sender_open_id}\">{bot_sender_name}</at>]\n\n"
        text = sender_type_hint + text
```

## 上下文参考

修改前后的代码结构：

```python
# ... 现有代码 ...
chat_id = getattr(message, "chat_id", "") or ""
chat_info = await self.get_chat_info(chat_id)
sender_profile = await self._resolve_sender_profile(sender_id)

# === 在此处插入新代码 ===

source = self.build_source(
    chat_id=chat_id,
    chat_name=chat_info.get("name") or chat_id or "Feishu Chat",
    # ... 其他参数 ...
)
# ... 后续代码 ...
```

## 工作原理

1. **检测发送者类型**: 通过 `sender_type` 字段判断发送者是 `bot` 还是 `app`
2. **获取发送者信息**: 从 `sender_id.open_id` 获取机器人 ID，从 `sender_profile` 获取名称
3. **注入提示信息**: 在消息文本前添加 `[来自机器人「xxx」...]` 格式的提示
4. **提供 @ 回语法**: 提示中直接包含正确的 `<at user_id="ou_xxx">xxx</at>` 格式

## 修改后的效果

当机器人 A 在群聊中 @ 机器人 B 时：

**机器人 B 收到的消息**:
```
[来自机器人「机器人A」— 如需 @ 回请使用：<at user_id="ou_aaa">机器人A</at>]

请帮我检查这个页面的样式问题
```

**机器人 B 的回复**:
```
<at user_id="ou_aaa">机器人A</at> (机器人A) 

检查完成，发现以下问题：
- header 的 z-index 设置过低
- 按钮的 hover 状态缺少过渡效果
```

这样机器人 A 就能收到机器人 B 的 @ 回复，实现双向协作。

## 验证修改

修改完成后，可以通过以下方式验证：

1. 在飞书群聊中添加两个机器人
2. 用机器人 A @ 机器人 B
3. 检查机器人 B 是否收到带有 `[来自机器人「...]` 前缀的消息
4. 检查机器人 B 的回复是否能正确 @ 回机器人 A

## 注意事项

- 此修改仅影响飞书平台（不影响其他平台）
- `sender_type` 值可能因飞书版本不同而变化，当前支持 `bot` 和 `app`
- 如果 `sender_profile` 无法获取机器人名称，会使用 `Bot(open_id)` 作为 fallback
- 此功能依赖飞书原生 @ 机制，需要确保机器人之间的 @ 能正常触发投递

## 相关文件

- 本插件: `__init__.py` - 工具注册和 Hook 定义
- 本插件: `tools.py` - `format_at_tag` 工具实现
- Hermes: `gateway/platforms/feishu.py` - 本修改的位置