"""Tool schemas for Feishu Bot Chat plugin."""

LIST_GROUP_BOTS = {
    "name": "list_group_bots",
    "description": """查询当前飞书群聊中可协作的其他机器人列表。

使用场景：
- 用户要求"群内协作"、"分配任务"时，先调用此工具了解可用机器人
- 用户询问"群里有哪些机器人可以帮忙"时
- 需要决定 @ 哪个机器人执行任务前

返回每个机器人的 botName 和 botOpenId，用于后续 format_at_tag 工具生成正确的 @ 标签。
""",
    "parameters": {
        "type": "object",
        "properties": {
            "chat_id": {
                "type": "string",
                "description": "飞书群聊 ID (oc_xxx 格式)。如果不确定，可以留空使用当前会话的群 ID。"
            }
        },
        "required": []
    }
}

FORMAT_AT_TAG = {
    "name": "format_at_tag",
    "description": """生成飞书 <at> 标签，用于在消息中 @ 指定的机器人。

飞书的 @ 机制要求使用特定的 XML 标签格式：
<at user_id="ou_xxxx">机器人名字</at>

直接写 @机器人名字 这种纯文本格式不会触发飞书的 @ 投递！

使用场景：
- 需要让其他机器人执行任务时
- 需要通知其他机器人时（配合 🔕仅通知 标记）
- 回复任务结果时 @ 回发起者

参数：
- bot_open_id: 机器人的 open_id (ou_xxx 格式)
- bot_name: 机器人的显示名称
- notification_only: 是否为仅通知类型（默认 False）
""",
    "parameters": {
        "type": "object",
        "properties": {
            "bot_open_id": {
                "type": "string",
                "description": "目标机器人的 Feishu open_id (ou_xxx 格式)"
            },
            "bot_name": {
                "type": "string",
                "description": "目标机器人的显示名称"
            },
            "notification_only": {
                "type": "boolean",
                "description": "是否为仅通知类型。True 时会在 @ 标签前加 🔕仅通知 标记，对方不需要 @ 回你。",
                "default": False
            }
        },
        "required": ["bot_open_id", "bot_name"]
    }
}