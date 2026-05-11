"""Tool handlers for Feishu Bot Chat plugin."""

import json
import os
import time
import logging
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

# Cache directory for bot registry
_CACHE_DIR = Path.home() / ".hermes" / "fbc-registry"
_CACHE_FILE = _CACHE_DIR / "registry.json"
_CACHE_TTL_SECONDS = 24 * 60 * 60  # 24 hours


def _get_feishu_credentials():
    """Get Feishu app credentials from environment or Hermes config."""
    # Try environment variables first
    app_id = os.environ.get("FEISHU_APP_ID")
    app_secret = os.environ.get("FEISHU_APP_SECRET")
    domain = os.environ.get("FEISHU_DOMAIN", "feishu")  # 'feishu' or 'lark'

    # If not in env, try Hermes config (for gateway mode)
    if not app_id or not app_secret:
        try:
            import yaml
            config_path = Path.home() / ".hermes" / "config.yaml"
            if config_path.exists():
                config = yaml.safe_load(config_path.read_text())
                platforms = config.get("platforms", {})
                feishu_config = platforms.get("feishu", {})
                if not app_id:
                    app_id = feishu_config.get("api_key") or feishu_config.get("app_id")
                if not app_secret:
                    app_secret = feishu_config.get("api_secret") or feishu_config.get("app_secret")
                domain = feishu_config.get("domain", domain)
        except Exception as e:
            logger.debug(f"Failed to load Hermes config: {e}")

    return app_id, app_secret, domain


async def _get_tenant_token(app_id: str, app_secret: str, domain: str) -> Optional[str]:
    """Get Feishu tenant access token."""
    base = "https://open.larksuite.com" if domain == "lark" else "https://open.feishu.cn"
    url = f"{base}/open-apis/auth/v3/tenant_access_token/internal"
    try:
        import httpx
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.post(url, json={"app_id": app_id, "app_secret": app_secret})
            data = resp.json()
            if data.get("code") == 0:
                return data.get("tenant_access_token")
        logger.warning(f"Failed to get tenant token: {data.get('msg')}")
    except Exception as e:
        logger.error(f"Error getting tenant token: {e}")
    return None


async def _get_bot_info(token: str, domain: str) -> Optional[dict]:
    """Get current bot info from Feishu API."""
    base = "https://open.larksuite.com" if domain == "lark" else "https://open.feishu.cn"
    url = f"{base}/open-apis/bot/v3/info"
    try:
        import httpx
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.get(url, headers={"Authorization": f"Bearer {token}"})
            data = resp.json()
            if data.get("code") == 0:
                bot = data.get("bot", {})
                return {
                    "bot_open_id": bot.get("open_id"),
                    "bot_name": bot.get("app_name") or bot.get("bot_name")
                }
        logger.warning(f"Failed to get bot info: {data.get('msg')}")
    except Exception as e:
        logger.error(f"Error getting bot info: {e}")
    return None


async def _get_group_bot_members(chat_id: str, token: str, domain: str) -> list:
    """Get bot members in a Feishu group chat with their names."""
    base = "https://open.larksuite.com" if domain == "lark" else "https://open.feishu.cn"
    bot_members = []
    page_token = ""

    try:
        import httpx
        async with httpx.AsyncClient(timeout=10) as client:
            for _ in range(10):  # Max 10 pages
                params = {"member_id_type": "open_id", "page_size": "100"}
                if page_token:
                    params["page_token"] = page_token
                url = f"{base}/open-apis/im/v1/chats/{chat_id}/members"
                resp = await client.get(url, params=params, headers={"Authorization": f"Bearer {token}"})
                data = resp.json()
                if data.get("code") != 0:
                    logger.warning(f"Failed to get group members: {data.get('msg')}")
                    break
                for m in data.get("data", {}).get("items", []):
                    if m.get("member_type") == "bot" and m.get("member_id"):
                        # Try to get bot name from member_name or name field
                        bot_name = m.get("member_name") or m.get("name") or f"Bot({m['member_id']})"
                        bot_members.append({
                            "bot_open_id": m["member_id"],
                            "bot_name": bot_name
                        })
                if not data.get("data", {}).get("has_more"):
                    break
                page_token = data.get("data", {}).get("page_token", "")
    except Exception as e:
        logger.error(f"Error getting group bot members: {e}")

    return bot_members


async def list_group_bots(args: dict, **kwargs) -> str:
    """List available bots in a Feishu group chat.

    Returns JSON with bot list and collaboration instructions.
    """
    chat_id = args.get("chat_id", "")

    # Get credentials
    app_id, app_secret, domain = _get_feishu_credentials()
    if not app_id or not app_secret:
        return json.dumps({
            "error": "Feishu credentials not configured",
            "hint": "Set FEISHU_APP_ID and FEISHU_APP_SECRET environment variables, or configure in ~/.hermes/config.yaml"
        })

    # Get token
    token = await _get_tenant_token(app_id, app_secret, domain)
    if not token:
        return json.dumps({"error": "Failed to authenticate with Feishu"})

    # Get current bot info first
    current_bot = await _get_bot_info(token, domain)
    if not current_bot:
        return json.dumps({"error": "Failed to get current bot info"})
    current_open_id = current_bot.get("bot_open_id")

    # Build result
    result = {
        "current_bot": current_bot,
        "group_bots": [],
        "instructions": _get_collaboration_instructions()
    }

    # If chat_id provided, get group members
    if chat_id:
        bot_members = await _get_group_bot_members(chat_id, token, domain)
        # Filter out current bot from list
        other_bots = [bot for bot in bot_members if bot.get("bot_open_id") != current_open_id]
        result["group_bots"] = other_bots
        result["hint"] = "Use format_at_tag to create proper @ mentions for collaboration"

    return json.dumps(result, indent=2)


def format_at_tag(args: dict, **kwargs) -> str:
    """Generate Feishu <at> tag for bot mentions.

    Returns the proper XML tag format that triggers Feishu's native @ delivery.
    """
    bot_open_id = args.get("bot_open_id", "")
    bot_name = args.get("bot_name", "")
    notification_only = args.get("notification_only", False)

    if not bot_open_id or not bot_name:
        return json.dumps({
            "error": "Missing bot_open_id or bot_name",
            "hint": "Use list_group_bots to get valid bot info first"
        })

    # Validate open_id format
    if not bot_open_id.startswith("ou_"):
        return json.dumps({
            "error": f"Invalid bot_open_id format: {bot_open_id}",
            "hint": "Feishu open_id should start with 'ou_'"
        })

    # Generate the at tag
    at_tag = f'<at user_id="{bot_open_id}">{bot_name}</at>'

    # Add text fallback for better visibility in streaming cards
    at_tag_with_fallback = f'{at_tag} ({bot_name})'

    result = {
        "at_tag": at_tag_with_fallback,
        "pure_tag": at_tag,
        "usage_hint": "Copy the at_tag into your response message to @ the bot"
    }

    if notification_only:
        result["at_tag"] = f'🔕仅通知 {at_tag_with_fallback}'
        result["notification_hint"] = "对方收到后不需要 @ 回你"

    return json.dumps(result, indent=2)


def _get_collaboration_instructions() -> str:
    """Get collaboration instructions for the agent."""
    return """
[A2A — 群内协作规则]

默认行为：
- 正常情况下不要主动 @ 其他机器人
- 每次回复最多 @ 1 个机器人

重要：区分"提到"和"请求"
- 如果你只是在回复中提到某个机器人，直接用它的名字，不要用 <at> 标签
- 只有当你确实需要对方执行任务、回答问题时，才使用 <at> 标签

触发协作：
- 当用户提到"群内协作"、"分配任务"、"协作完成"等关键字时，可以根据任务需要主动 @ 合适的机器人
- 当用户明确要求你联系某个机器人时，也可以 @

@ 的两种类型：

1. 任务型 @（需要对方完成任务并回传结果）：
   - 直接在回复中用 <at> 标签 @ 对方，说明任务内容
   - 对方完成后应该 @ 回你汇报结果
   - 你收到结果后，整理结果回复用户，不要再 @ 回对方

2. 通知型 @（只是告知信息，不需要对方回复）：
   - 在消息中加上 🔕仅通知 标记
   - 示例：「🔕仅通知 <at ...>xxx</at> 排期已确认，按原计划推进即可」
   - 对方收到后不需要 @ 回你

⚠️ @ 格式要求（非常重要）：
- 必须使用 <at user_id="ou_xxxx">名字</at> 格式
- 禁止使用 @名字 这种明文写法，明文写法不会触发飞书的 @ 投递
- 使用 format_at_tag 工具生成正确的 @ 标签

回复规则：
- 当收到 [来自机器人「xxx」] 开头的消息时，说明这是另一个机器人 @ 你的任务请求
- 完成任务后，使用消息中提供的 <at> 标签 @ 回发起者汇报结果
- 如果对方只是通知你信息（消息中包含 🔕仅通知），不需要 @ 回对方
"""