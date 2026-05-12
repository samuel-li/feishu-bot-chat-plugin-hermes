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
        "协作", "分配", "一起", "群内", "合作", "让", "问问", "帮忙", "讨论"
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

            # Detect message type: task request vs result report
            is_result_report = any(marker in user_message for marker in [
                "任务已完成", "已完成", "结果如下", "检查完成", "分析完成",
                "总结如下", "回复如下", "[任务完成]", "[结果汇报]"
            ])

            if is_result_report:
                # This is a result report - don't @ back, just process and inform user
                context = f"""
[飞书 Bot-to-Bot 协作 — 结果汇报]

机器人「{sender_name}」向你汇报了任务结果。

**回复规则**：
- **不要 @ 回发送者** — 这是结果汇报，任务已闭环
- 整理结果内容，回复给发起这个协作的用户
- 如果你是协作协调者，汇总所有机器人的结果后统一回复用户

**正确做法**：
```
收到「{sender_name}」的汇报：
- xxx问题已解决
- xxx建议是...

我来汇总一下整体情况...
```

**禁止 @ 回** — 除非你有新的任务需要对方执行（那应该另开一轮协作）。
"""
            else:
                # This is a task request - must @ back
                context = f"""
[飞书 Bot-to-Bot 协作 — 任务请求]

你收到了来自机器人「{sender_name}」的任务请求。

⚠️ **回复格式是强制性的，必须严格遵守**：

你的回复**第一行**必须是以下完整@标签（直接复制，一字不改）：
```
<at user_id="{sender_id}">{sender_name}</at> ({sender_name})
```

**回复末尾加状态标记**（防止无限循环）：
- 如果任务完成：在末尾加 `[任务完成]`
- 如果需要对方继续：明确说明下一步需求

**回复示例**：
```
<at user_id="{sender_id}">{sender_name}</at> ({sender_name})

任务已完成，结果如下：
- 发现 3 个问题
- 已修复 2 个

[任务完成]
```

**禁止的格式**：
- ❌ @{sender_name} 或 @[名字] — 不会触发飞书投递
- ❌ 不在第一行放@标签
- ❌ 汇报结果后继续@对方讨论（应该用 [任务完成] 标记闭环）

**协作闭环规则**：
- 任务完成后加 `[任务完成]` 标记
- 收到 `[任务完成]` 的机器人不再@回去
- 只有明确需要对方继续工作时才再次@
"""
        else:
            context = """
[飞书 Bot-to-Bot 协作]

消息来自另一个机器人。

- 如果是任务请求：回复第一行必须是 `<at user_id="ou_xxx">名字</at> (名字)`
- 如果是结果汇报（含"已完成"/"结果如下"）：不要再@回去
- 任务完成后在末尾加 `[任务完成]` 标记防止无限循环
"""
    else:
        # Regular collaboration context injection - when user asks for collaboration
        context = """
[飞书群内 Bot 协作]

你正在飞书群聊环境中。用户要求机器人之间协作讨论。

**协作流程规则**：

当用户说"让机器人们讨论"、"分配给xxx机器人"时：
1. **直接开始协作** — 不要先向用户报告再@其他机器人
2. 先调用 `list_group_bots` 获取群内可用机器人
3. 找到合适的机器人后，用 `format_at_tag` 生成@标签
4. 在回复中直接@目标机器人分配任务

**@格式必须正确**：
- 必须用 `<at user_id="ou_xxx">名字</at> (名字)` 格式
- 禁止用 @名字 或 @[名字] 这种写法（不会触发投递）

**防止无限循环**：
- 每个任务回复末尾加 `[任务完成]` 标记
- 收到 `[任务完成]` 或"已完成"/"结果如下"的汇报时，不要再@回去
- 只汇总结果回复给用户，除非需要对方继续工作

**角色定位**：
- 协调者：@其他机器人分配任务，收到结果后汇总给用户，不再@回去
- 执行者：完成后 @ 回发起者汇报，末尾加 `[任务完成]`

**记住**：飞书群聊的@机制需要特定XML标签格式才能生效。
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