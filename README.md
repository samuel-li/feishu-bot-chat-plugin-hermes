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

## Hermes 框架要求

本插件需要 Hermes 框架支持以下接口和 Hook：

### 1. 插件注册 API

Hermes 需要实现 `ctx` 上下文对象，提供以下注册方法：

```python
# tools.py 中的调用示例
ctx.register_tool(
    name="list_group_bots",       # 工具名称
    toolset="feishu-bot-chat",    # 工具集名称
    schema=schemas.LIST_GROUP_BOTS,  # JSON Schema
    handler=tools.list_group_bots    # 处理函数
)

ctx.register_hook(
    "pre_llm_call",               # Hook 名称
    _inject_collaboration_context  # Hook 处理函数
)

ctx.register_skill(
    "a2a-collaboration-guide",    # 技能名称
    skill_md                      # SKILL.md 文件路径
)
```

### 2. pre_llm_call Hook 参数

Hook 函数 `_inject_collaboration_context` 接收以下参数：

```python
def _inject_collaboration_context(
    session_id: str,      # 会话 ID（用于避免重复注入）
    user_message: str,    # 用户消息内容
    platform: str,        # 平台标识：'feishu' 或 'lark'
    is_first_turn: bool,  # 是否为首轮对话
    **kwargs              # 其他上下文信息
) -> dict | None:         # 返回 {'context': str} 或 None
```

**Hermes 需要在调用 LLM 前传递这些参数**。

### 3. 配置文件读取

插件会尝试从 `~/.hermes/config.yaml` 读取飞书配置（当环境变量不存在时）：

```yaml
platforms:
  feishu:
    app_id: "cli_xxxx"
    app_secret: "xxxxx"
    domain: "feishu"  # 或 "lark"
```

### 4. 调用工具时的 kwargs

当 LLM 调用工具时，Hermes 需要传递会话相关信息：

```python
# list_group_bots 调用示例
result = await tools.list_group_bots(
    args={"chat_id": "oc_xxx"},  # LLM 提供的参数
    # Hermes 可传递以下 kwargs：
    session_id="xxx",
    chat_id="oc_xxx",  # 当前会话的群聊 ID（可选）
    ...
)
```

### 5. 实现 Checklist

在 Hermes 中集成此插件前，确认以下功能已实现：

- [ ] 插件发现机制：扫描 `~/.hermes/plugins/` 目录
- [ ] 插件 manifest 解析：读取 `plugin.yaml`
- [ ] `ctx.register_tool()` 工具注册接口
- [ ] `ctx.register_hook()` Hook 注册接口
- [ ] `ctx.register_skill()` 技能注册接口
- [ ] `pre_llm_call` Hook 调用时机：LLM 调用前
- [ ] Hook 参数传递：`session_id`, `user_message`, `platform`, `is_first_turn`
- [ ] 平台标识支持：识别飞书/Lark 会话并传递 `platform` 参数

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