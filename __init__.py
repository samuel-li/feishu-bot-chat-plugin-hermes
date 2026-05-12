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

    Strategy: Inject context on first turn (let agent decide whether to collaborate),
    and always inject when receiving bot-to-bot messages.
    """
    # Only inject for Feishu/Lark platform
    if platform not in ("feishu", "lark"):
        return None

    # Check if message is from another bot (A2A communication)
    is_from_bot = user_message.strip().startswith("[来自机器人「") or user_message.strip().startswith("[来自机器人「")

    is_first_turn = kwargs.get("is_first_turn", False)

    # Inject on first turn OR when receiving bot message
    if not (is_first_turn or is_from_bot):
        return None

    # Track sessions that have seen collaboration context
    _sessions_with_context.add(session_id)

    # Different context based on message source
    if is_from_bot:
        # Bot-to-bot message - inject specific reply instructions
        import re
        match = re.search(r'\[来自机器人「(.+?)」— 如需 @ 回请使用：<at user_id="([^"]+)">[^<]+</at>\]', user_message)
        if match:
            sender_name = match.group(1)
            sender_id = match.group(2)

            # Detect message type: task request vs result report
            is_result_report = any(marker in user_message for marker in [
                "任务已完成", "已完成", "结果如下", "检查完成", "分析完成",
                "总结如下", "回复如下", "[任务完成]", "任务闭环"
            ])

            if is_result_report:
                context = f"""
[飞书 Bot-to-Bot 协作 — 结果汇报]

机器人「{sender_name}」向你汇报了任务结果。

**处理规则**：
- **不要 @ 回发送者** — 任务已闭环
- 整理结果内容，回复给发起协作的用户
- 如果需要继续协作，另开一轮（明确说明新的任务需求）
"""
            else:
                context = f"""
[飞书 Bot-to-Bot 协作 — 任务请求]

你收到了来自机器人「{sender_name}」的任务请求。

**强制回复格式**：

回复**第一行**必须是：
```
<at user_id="{sender_id}">{sender_name}</at> ({sender_name})
```

回复**末尾**加 `[任务完成]` 标记（防止无限循环）：

示例：
```
<at user_id="{sender_id}">{sender_name}</at> ({sender_name})

任务已完成：
- xxx问题已解决

[任务完成]
```

⚠️ 禁止使用 @{sender_name} 或 @[名字] 格式（不会触发投递）
"""
        else:
            context = """
[飞书 Bot-to-Bot 协作]

消息来自另一个机器人。
- 如果是任务请求：回复第一行用 `<at user_id="ou_xxx">名字</at> (名字)`
- 如果是结果汇报：不要再 @ 回去
- 任务完成后加 `[任务完成]` 标记
"""
    else:
        # First turn in group chat - let agent decide whether to collaborate
        context = """
[飞书群聊协作指南]

你正在飞书群聊中。群内可能有其他机器人可以协作。

**何时需要协作**（Agent 自行判断）：

✅ 需要协作的情况：
- 用户明确要求"让xxx机器人帮忙"、"分配给xxx"
- 用户说"让机器人们讨论"、"你们协作一下"
- 任务需要其他机器人的专长（前端/后端/数据分析等）

❌ 不需要协作的情况：
- 用户只是让你分析/解释/回答问题
- 你自己能完成这个任务
- 用户没有明确提到其他机器人

**如果决定协作**：
1. 调用 `list_group_bots` 获取群内可用机器人
2. 调用 `format_at_tag` 生成正确@标签
3. 直接在回复中@目标机器人分配任务（不要先向用户报告）

**如果不需要协作**：
- 直接回复用户，正常完成任务

**@标签格式**（必须遵守）：
- 正确：`<at user_id="ou_xxx">名字</at> (名字)`
- 错误：`@名字` 或 `@[名字]` — 不会触发投递

**防止无限循环**：
- 任务完成后在回复末尾加 `[任务完成]`
- 收到 `[任务完成]` 或结果汇报后，不要再@回去
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