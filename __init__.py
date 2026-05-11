"""Feishu Bot Chat plugin — Hermes version.

Enables bot-to-bot @ communication in Feishu group chats by providing:
1. Tools for bot discovery and @ tag formatting
2. pre_llm_call hook for collaboration context injection
"""

import logging
from pathlib import Path
from . import schemas, tools

logger = logging.getLogger(__name__)

# Track sessions that have seen collaboration instructions
_sessions_with_context = set()


def _inject_collaboration_context(session_id: str, user_message: str, platform: str, **kwargs) -> dict:
    """pre_llm_call hook: Inject collaboration context for Feishu sessions.

    Returns context dict that Hermes appends to the user message.
    """
    # Only inject for Feishu/Lark platform
    if platform not in ("feishu", "lark"):
        return None

    # Check if message is from another bot (A2A task request)
    is_from_bot = user_message.strip().startswith("[来自机器人「")

    # Inject on first turn, collaboration keywords, or when message is from another bot
    is_first_turn = kwargs.get("is_first_turn", False)
    has_collaboration_keywords = any(kw in user_message.lower() for kw in [
        "协作", "分配", "一起", "群内", "合作", "让", "问问", "帮忙"
    ])

    # Critical: Always inject when message is from another bot
    if not (is_first_turn or has_collaboration_keywords or is_from_bot):
        return None

    # Avoid duplicate injection (but allow re-injection when from bot)
    if session_id in _sessions_with_context and not is_from_bot:
        return None

    _sessions_with_context.add(session_id)

    # Different context based on whether this is a bot-to-bot message
    if is_from_bot:
        # Extract bot name and at_tag from the message prefix if present
        import re
        match = re.search(r'\[来自机器人「(.+?)」— 如需 @ 回请使用：<at user_id="([^"]+)">[^<]+</at>\]', user_message)
        if match:
            sender_name = match.group(1)
            sender_id = match.group(2)
            context = f"""
[飞书 Bot-to-Bot 协作 — 必须遵守！]

你收到了来自机器人「{sender_name}」的任务/回复。

**回复规则（必须严格遵守）**：

1. 回复开头必须是以下 **完整@标签**（直接复制，不要修改）：
```
<at user_id="{sender_id}">{sender_name}</at> ({sender_name})
```

2. **禁止使用以下错误格式**：
   - ❌ @{sender_name}
   - ❌ @{sender_name}
   - ❌ @[小叶子] 或 @[任何名字]
   - ❌ @名字 或 @[名字]
   - ❌ 任何不带 <at user_id="ou_xxx"> 的写法

3. **正确的做法**：直接复制上面的完整标签到回复开头

正确回复示例：
```
<at user_id="{sender_id}">{sender_name}</at> ({sender_name})

任务已完成，结果如下：
- 发现 3 个问题
- 已修复 2 个
```

⚠️ 如果消息含 🔕仅通知 标记，则不需要 @ 回，直接忽略即可。
"""
        else:
            context = """
[飞书 Bot-to-Bot 协作]

消息来自另一个机器人。如果这是任务请求：
- 完成后必须 @ 回发送者汇报结果
- 使用消息中提供的 <at user_id="ou_xxx">名字</at> 格式
- **禁止用 @名字 或 @[名字] 格式，那是错的！**
"""
    else:
        # Regular collaboration context injection
        context = """
[飞书群内 Bot 协作]

你正在飞书群聊环境中。如果需要 @ 其他机器人协作：

1. 先用 list_group_bots 工具查询群内可协作的机器人
2. 用 format_at_tag 工具生成正确的 @ 标签（必须用 <at user_id="ou_xxx">名字</at> 格式）
3. 不要用 @名字 这种明文写法，那不会触发飞书投递

核心规则：
- 默认不主动 @ 其他机器人
- 每次回复最多 @ 1 个机器人
- 区分"提到"和"请求"：提到用名字，请求才用 <at> 标签
- 任务型 @：对方完成后会 @ 回你
- 通知型 @：加 🔕仅通知 标记，对方不需要回复
"""

    return {"context": context}


def register(ctx):
    """Wire tools and hooks to Hermes registry."""
    # Register tools
    ctx.register_tool(
        name="list_group_bots",
        toolset="feishu-bot-chat",
        schema=schemas.LIST_GROUP_BOTS,
        handler=tools.list_group_bots
    )

    ctx.register_tool(
        name="format_at_tag",
        toolset="feishu-bot-chat",
        schema=schemas.FORMAT_AT_TAG,
        handler=tools.format_at_tag
    )

    # Register pre_llm_call hook for context injection
    ctx.register_hook("pre_llm_call", _inject_collaboration_context)

    # Register bundled skills
    skills_dir = Path(__file__).parent / "skills"
    for child in sorted(skills_dir.iterdir()):
        skill_md = child / "SKILL.md"
        if child.is_dir() and skill_md.exists():
            ctx.register_skill(child.name, skill_md)

    logger.info("[feishu-bot-chat] Registered 2 tools, 1 hook, and bundled skills")