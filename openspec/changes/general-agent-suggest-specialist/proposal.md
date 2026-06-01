## Why

当用户在一个**已有的对话窗口**里继续提问、但**没有选择任何专门 Agent** 时，请求会默认落到 `GeneralAgent`（通用轻量级 Agent，见 [`app/agents/general_agent/agent.py`](../../../app/agents/general_agent/agent.py)）。

现状有两个问题：

1. **上下文确实能传入，但行为没有被规范固化。** `GeneralAgent` 已经通过 `GeneralAgentContext.history` 接收会话历史，并在 `run_stream` 里用 `_format_history_block` 包成 `<conversation_history>` 注入提示词。但此前从未有 spec 记录这一行为，也没有记录"未选 Agent 默认走 GeneralAgent"这条路由约定，容易在后续重构中被破坏。

2. **GeneralAgent 不会主动、结构化地引导用户去选对应 Agent。** 它当前只在判定"超出系统使用范围"时被动输出一段固定拒答话术，里面笼统列出三个模块（设备操作 / 日志分析 / 检索包），**漏掉了项目专家（project_expert）**，而且：
   - 不会**根据用户最新输入做意图归类**（例如"帮我重启 X 设备""分析这份日志为什么报错"应分别指向设备操作 / 日志分析）；
   - 没有"**你必须先选中对应 Agent 才能继续**"的强引导；
   - 提示只存在于自由文本里，**前端拿不到结构化信号**，无法高亮/弹窗/一键切换。

本变更让 GeneralAgent 成为一个**轻量路由引导者**：在不具备专门能力时，根据用户最新输入判断该用哪个专门 Agent，明确提示用户**必须先在上方选择对应 Agent**，并通过一个结构化字段 `suggested_agent_type` 把建议透传到前端，由前端给出醒目提示与一键切换。

## What Changes

- **固化 GeneralAgent 的上下文与路由契约**（spec 层）：未选择任何专门 Agent 的对话默认路由到 GeneralAgent；GeneralAgent 必须接收并使用截断后的会话历史（最多 `anthropic_max_history_turns` 轮）。
- **增强 `GeneralAgent` 系统提示词**（[`app/agents/general_agent/agent.py`](../../../app/agents/general_agent/agent.py)）：
  - 新增对**全部四个专门 Agent**（`device` / `log_analysis` / `package_search` / `project_expert`）的职责说明与意图判定规则；
  - 当用户最新输入实际属于某专门 Agent 的任务时，**不臆测执行**，而是明确告知"该需求需使用「XX」，请先在上方选择对应 Agent 后再发送"；
  - 要求模型在回复**最后一行**输出机器可读标记 `[[SUGGESTED_AGENT:<key>]]`（key ∈ `device|log_analysis|package_search|project_expert|none`）。
- **结构化输出 `suggested_agent_type`**：
  - `GeneralAgent.run_stream` 解析并**剥离**回复末尾的标记，把建议放进 `run_complete` 事件的 `suggested_agent_type` 字段（无建议时为 `null`），并保证用户看到的正文不含标记；
  - `chat_run_service._run_general_job` 把该字段透传到 SSE 的 `run_complete` 与 `done` 帧，并记入 `ChatRunJob` 快照供断线重连/回放；
  - 非流式 `ai_chat_service.chat` 在 `ChatResponse` 上回填 `suggested_agent_type`。
- **前端结构化提示与一键切换**（[`frontend/src/stores/conversationRuns.ts`](../../../frontend/src/stores/conversationRuns.ts)、[`frontend/src/views/AIChat.vue`](../../../frontend/src/views/AIChat.vue)）：store 记录本轮 `suggestedAgentType`；当其非空时，AIChat 在回复下方展示醒目提示条，提示"该请求需使用 XX，请先选择对应 Agent"，并提供一键切换到对应 Agent（设备类引导用户使用设备操作入口）。

## Capabilities

### New Capabilities
- `general-agent`：通用轻量级对话 Agent 的能力规格。覆盖三件事：(1) 默认路由——未选择任何专门 Agent 的对话走 GeneralAgent；(2) 上下文——GeneralAgent 接收并按上限截断使用会话历史；(3) Agent 路由引导——根据用户最新输入判定意图，对属于专门 Agent 的请求明确要求用户先选中对应 Agent，并通过结构化 `suggested_agent_type` 字段把建议透传到前端。

### Modified Capabilities
<!-- agent-trace-stream / agent-trace-ui 的既有事件契约保持兼容：仅在 run_complete/done 帧上**新增可选**字段 suggested_agent_type，不改变既有字段语义；故不修改其 spec。 -->

## Impact

- **新增 spec**：`openspec/specs/general-agent/spec.md`（经本变更归档后生成）。
- **修改代码（后端）**：
  - [`app/agents/general_agent/agent.py`](../../../app/agents/general_agent/agent.py)：增强 `SYSTEM_PROMPT`、新增 `_extract_suggested_agent`、`run_complete` 增加 `suggested_agent_type`、`_FALLBACK_ANSWER` 补全 project_expert。
  - [`app/services/chat_run_service.py`](../../../app/services/chat_run_service.py)：`ChatRunJob` 新增 `suggested_agent_type` 字段；`_run_general_job` 透传到 `done` 帧；`_snapshot_payload` 纳入快照。
  - [`app/services/ai_chat_service.py`](../../../app/services/ai_chat_service.py)：`chat` / `chat_stream` 捕获并回填 `suggested_agent_type`。
  - [`app/models/chat.py`](../../../app/models/chat.py)：`ChatResponse` 新增可选字段 `suggested_agent_type`。
- **修改代码（前端）**：
  - [`frontend/src/stores/conversationRuns.ts`](../../../frontend/src/stores/conversationRuns.ts)：`ConversationState` 新增 `suggestedAgentType`，在 `run_complete`/`done` 读取，新 run 开始时重置。
  - [`frontend/src/views/AIChat.vue`](../../../frontend/src/views/AIChat.vue)：新增建议提示条 + 一键切换。
- **新增/扩展测试**：[`tests/agents/general_agent/test_agent.py`](../../../tests/agents/general_agent/test_agent.py) 增加标记解析/剥离、建议透传、各意图分支用例；service 层透传断言。
- **向后兼容**：`suggested_agent_type` 为新增**可选**字段，缺省 `null`；不改既有事件类型、不改 `/chat`、`/chat/stream` 契约；DeviceAgent / LogAnalysis / ProjectExpert / PackageSearch 行为不变。
- **不新增**：env 字段、依赖、数据库表/列、API 端点。
