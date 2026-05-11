# Hermes 主程序修改指南

本插件需要 Hermes 主程序中的 `gateway/platforms/feishu.py` 进行相应修改，以支持 Bot-to-Bot @ 通信。

## 修改目的

当飞书群聊中有其他机器人 @ 本机器人时，Hermes 需要在消息文本前注入发送者信息，让 Agent 知道如何 @ 回发送者：

```
[来自机器人「前端机器人」— 如需 @ 回请使用：<at user_id="ou_xxx">前端机器人</at>]

原始消息内容...
```

## 修改内容概览

共需添加 **76 行代码**，分为三部分：

1. **群聊类型正确识别**（约 15 行）- 修复 `_handle_message_event_data()` 中的 chat_type 判断
2. **消息注入逻辑**（约 22 行）- 在 `_process_inbound_message()` 函数中
3. **机器人名称获取方法**（约 39 行）- 新增 `_get_bot_name_from_chat_members()` 方法

---

## 修改位置 1：群聊类型正确识别（重要 Bug 修复）

**文件**: `gateway/platforms/feishu.py`
**函数**: `FeishuAdapter._handle_message_event_data()`
**行号**: 约 1995 行

**问题**：飞书 Bot-to-Bot 消息的 `message.chat_type` 字段可能缺失或错误，导致群聊消息被错误识别为私聊（p2p），回复发送到私聊而非群聊。

**解决方案**：先调用 `get_chat_info()` API 获取真实的 chat 类型。

替换原有代码：

```python
# 原代码（有问题）
chat_type = getattr(message, "chat_type", "p2p")
chat_id = getattr(message, "chat_id", "") or ""
if chat_type != "p2p" and not self._should_accept_group_message(message, sender_id, chat_id):
    ...
```

为：

```python
# 新代码（修复后）
# Get chat_id first, then resolve true chat_type from API
# (message.chat_type may be missing or wrong for bot-to-bot messages)
chat_id = getattr(message, "chat_id", "") or ""
event_chat_type = getattr(message, "chat_type", "p2p")

# Fetch real chat info to determine if this is group vs p2p
chat_info = await self.get_chat_info(chat_id)
resolved_chat_type = chat_info.get("type", "dm")

# Use resolved type, but fallback to event_chat_type if API failed
if resolved_chat_type == "dm" and event_chat_type != "p2p":
    # API returned dm but event says otherwise - trust event
    resolved_chat_type = self._map_chat_type(event_chat_type)

if resolved_chat_type != "dm" and not self._should_accept_group_message(message, sender_id, chat_id):
    logger.debug("[Feishu] Dropping group message that failed mention/policy gate: %s", message_id)
    return
await self._process_inbound_message(
    data=data,
    message=message,
    sender_id=sender_id,
    chat_type=event_chat_type,  # Pass original to _process_inbound_message
    message_id=message_id,
)
```

---

## 修改位置 2：消息注入

**文件**: `gateway/platforms/feishu.py`
**函数**: `FeishuAdapter._normalize_inbound()`
**行号**: 约 2500 行（`sender_profile = await self._resolve_sender_profile(sender_id)` 之后）

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
    # Try multiple sources to get bot name
    bot_sender_name = sender_profile.get("user_name") or None
    if not bot_sender_name and sender_open_id and chat_id:
        # Fallback: get bot name from chat members API (bots have member_name)
        bot_sender_name = await self._get_bot_name_from_chat_members(chat_id, sender_open_id)
    if not bot_sender_name:
        # Last fallback: use open_id prefix as name
        bot_sender_name = sender_open_id.split("_")[-1] if sender_open_id else "Bot"
    if sender_open_id and text:
        sender_type_hint = f"[来自机器人「{bot_sender_name}」— 如需 @ 回请使用：<at user_id=\"{sender_open_id}\">{bot_sender_name}</at>]\n\n"
        text = sender_type_hint + text
```

## 修改位置 3：机器人名称获取方法

**位置**: `_resolve_sender_profile()` 方法附近（约 3290 行）

在 `_resolve_sender_profile()` 方法之后，添加以下新方法：

```python
async def _get_bot_name_from_chat_members(self, chat_id: str, bot_open_id: str) -> Optional[str]:
    """Get bot name from chat members API (bots have member_name field).

    Used for A2A collaboration to get the name of the sending bot.
    Cached for 10 minutes to reduce API calls.
    """
    if not chat_id or not bot_open_id or not self._client:
        return None

    # Check cache first
    cache_key = f"bot_name:{bot_open_id}:{chat_id}"
    cached_name = self._get_cached_sender_name(cache_key)
    if cached_name is not None:
        return cached_name

    try:
        from lark_oapi.api.im.v1 import GetChatMembersRequest
        request = GetChatMembersRequest.builder() \
            .chat_id(chat_id) \
            .member_id_type("open_id") \
            .page_size(50) \
            .build()
        response = await asyncio.to_thread(self._client.im.v1.chat_members.get, request)
        if not response or not response.success():
            return None
        items = getattr(getattr(response, "data", None), "items", None) or []
        for item in items:
            if getattr(item, "member_type", None) == "bot":
                member_id = getattr(item, "member_id", None)
                if member_id == bot_open_id:
                    name = getattr(item, "member_name", None) or getattr(item, "name", None)
                    if name:
                        # Cache for 10 minutes
                        self._sender_name_cache[cache_key] = (name, time.time() + 600)
                        return name
    except Exception:
        logger.debug("[Feishu] Failed to get bot name from chat members", exc_info=True)
    return None
```

## 上下文参考

### 修改位置 1 上下文（群聊类型识别）

```python
# ... 现有代码 ...
if self._is_self_sent_bot_message(event):
    logger.debug("[Feishu] Dropping self-sent bot event: %s", message_id)
    return

# === 在此处替换原有的 chat_type 获取逻辑 ===
# 原代码: chat_type = getattr(message, "chat_type", "p2p")
# 新代码: 调用 get_chat_info() API 获取真实类型

# ... 后续代码 ...
```

### 修改位置 2 上下文（消息注入）

```python
# ... 现有代码 ...
chat_id = getattr(message, "chat_id", "") or ""
chat_info = await self.get_chat_info(chat_id)
sender_profile = await self._resolve_sender_profile(sender_id)

# === 在此处插入消息注入代码 ===

source = self.build_source(
    chat_id=chat_id,
    chat_name=chat_info.get("name") or chat_id or "Feishu Chat",
    # ... 其他参数 ...
)
# ... 后续代码 ...
```

### 修改位置 3 上下文（机器人名称获取方法）

```python
# ... 现有代码 ...
async def _resolve_sender_profile(self, sender_id: Any) -> dict:
    # ... 方法实现 ...
    # ... 方法结尾 ...

# === 在此处插入 _get_bot_name_from_chat_members 方法 ===

async def _fetch_message_text(self, message_id: str) -> Optional[str]:
    # ... 后续方法 ...
```

## 工作原理

### 机器人名称获取的三层 Fallback

1. **第一层**: 从 `sender_profile.user_name` 获取（通常对机器人返回 None）
2. **第二层**: 调用 `_get_bot_name_from_chat_members()` 从群成员 API 获取
3. **第三层**: 使用 `open_id` 的最后一部分作为名称（如 `ou_xxx` → `xxx`）

### 缓存机制

`_get_bot_name_from_chat_members()` 使用现有的 `_sender_name_cache` 缓存：
- 缓存键: `bot_name:{bot_open_id}:{chat_id}`
- 缓存时长: 10 分钟
- 减少重复 API 调用

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
5. 观察日志确认 `_get_bot_name_from_chat_members()` 调用情况

## 注意事项

- **修改位置 1 是关键 Bug 修复**：不修复会导致群聊 Bot-to-Bot 消息被错误路由到私聊
- 此修改仅影响飞书平台（不影响其他平台）
- `sender_type` 值可能因飞书版本不同而变化，当前支持 `bot` 和 `app`
- 群成员 API 每页最多 50 条，如果群内机器人超过 50 个可能需要分页
- 缓存 10 分钟，机器人改名后需要等待缓存过期
- 此功能依赖飞书原生 @ 机制，需要确保机器人之间的 @ 能正常触发投递

## 相关文件

- 本插件: `__init__.py` - 工具注册和 Hook 定义
- 本插件: `tools.py` - `format_at_tag` 工具实现
- Hermes: `gateway/platforms/feishu.py` - 本修改的位置