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

    # Inject on first turn or when collaboration keywords appear
    is_first_turn = kwargs.get("is_first_turn", False)
    has_collaboration_keywords = any(kw in user_message.lower() for kw in [
        "协作", "分配", "一起", "群内", "合作", "让", "问问", "帮忙"
    ])

    if not (is_first_turn or has_collaboration_keywords):
        return None

    # Avoid duplicate injection
    if session_id in _sessions_with_context and not has_collaboration_keywords:
        return None

    _sessions_with_context.add(session_id)

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