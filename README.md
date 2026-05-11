# Feishu Bot Chat Plugin (Hermes Version)

飞书群聊机器人间 A2A 协作通信插件 - Hermes 版本

## 与 OpenClaw 版本的区别

| 特性 | OpenClaw 版本 | Hermes 版本 |
|------|---------------|-------------|
| 消息拦截 | inbound_claim hook | ❌ 不支持（Hermes 不处理消息收发） |
| @ 标签转换 | message_sending hook 自动转换 | ✅ 提供 format_at_tag 工具手动生成 |
| Bot 发现 | before_prompt_build 自动注入 | ✅ 提供 list_group_bots 工具 + pre_llm_call hook |
| 技能注入 | skills 目录 | ✅ 相同（ctx.register_skill） |

**架构差异说明**：
- OpenClaw 是 Gateway 框架，可以拦截和处理消息流
- Hermes 是 LLM Agent 框架，主要通过 Tools 和 pre_llm_call hook 工作

因此 Hermes 版本采用"工具驱动"方式：
- LLM 需要时主动调用工具获取 Bot 信息
- 手动调用 format_at_tag 生成 @ 标签

## 安装

```bash
# 复制插件到 Hermes 插件目录
cp -r hermes-plugin ~/.hermes/plugins/feishu-bot-chat

# 启用插件
hermes plugins enable feishu-bot-chat

# 配置环境变量（在 ~/.hermes/.env 或启动时设置）
export FEISHU_APP_ID="cli_xxxx"
export FEISHU_APP_SECRET="xxxxx"
```

## 工具说明

### list_group_bots

查询飞书群聊中可协作的机器人列表。

```bash
# 调用示例（LLM 自动调用）
{
  "chat_id": "oc_xxxx"  # 可选，群聊 ID
}
```

返回：
```json
{
  "current_bot": {
    "bot_open_id": "ou_xxxx",
    "bot_name": "我的机器人"
  },
  "group_bots": [
    {"bot_open_id": "ou_yyyy", "bot_name": "Bot (ou_yyyy)"}
  ],
  "instructions": "..."
}
```

### format_at_tag

生成飞书 `<at>` 标签。

```bash
# 任务型 @
{
  "bot_open_id": "ou_xxxx",
  "bot_name": "前端机器人"
}

# 通知型 @
{
  "bot_open_id": "ou_xxxx",
  "bot_name": "前端机器人",
  "notification_only": true
}
```

返回：
```json
{
  "at_tag": "<at user_id=\"ou_xxxx\">前端机器人</at> (前端机器人)",
  "usage_hint": "Copy the at_tag into your response message"
}
```

## Hook 说明

### pre_llm_call

在每次 LLM 调用前注入协作上下文（仅飞书平台）。

注入条件：
- 第一轮对话
- 或用户消息包含协作关键字（"协作", "分配", "一起" 等）

注入内容：
- 协作规则简述
- 工具使用提示

## Skills

插件自带一个技能：

- `a2a-collaboration-guide` - 协作规则速查手册

Agent 可通过：
```python
skill_view("feishu-bot-chat:a2a-collaboration-guide")
```

## 文件结构

```
hermes-plugin/
├── plugin.yaml        # 插件 manifest
├── __init__.py        # register(ctx) 注册逻辑
├── schemas.py         # 工具 schema 定义
├── tools.py           # 工具处理函数
└── skills/
    └── a2a-collaboration-guide/
        └── SKILL.md   # 协作指南技能
```

## 环境变量

| 变量 | 说明 | 必需 |
|------|------|------|
| FEISHU_APP_ID | 飞书 App ID | ✅ |
| FEISHU_APP_SECRET | 飞书 App Secret | ✅ |
| FEISHU_DOMAIN | 飞书/Lark 域名 (默认 feishu) | ❌ |

## 使用流程

1. 用户在飞书群聊中说"让前端机器人帮忙看看这个页面"
2. Agent 调用 `list_group_bots` 获取群内机器人列表
3. Agent 找到"前端机器人"的 open_id
4. Agent 调用 `format_at_tag` 生成 @ 标签
5. Agent 回复消息中包含生成的 @ 标签
6. 飞书原生投递消息到前端机器人

## License

MIT