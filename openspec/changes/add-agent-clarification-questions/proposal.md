## Why

当用户指令不清晰（缺少关键参数、存在多种合理解读、目标设备/范围不明确）时，DeviceAgent 目前只能"猜一个"继续执行或直接报错，二者都会浪费一轮昂贵的 agent loop 并降低结果可信度。我们需要一种像 Claude Code `AskUserQuestion` 一样的机制：**由 Agent 自行判断**是否需要澄清，向用户抛出一组带预设选项、同时允许自由输入的问题，待用户作答后再继续执行。该机制可直接复用现有 HITL（工具审批 `PermissionBroker`）管线，落地成本低。

## What Changes

- 新增一个 in-process MCP 工具 `AskUserQuestion`（默认对 DeviceAgent 可用），Agent 在推理过程中**自行决定**是否调用；调用即阻塞当前 agent loop，等待用户作答后将答案作为工具返回值回喂模型，Agent 继续。
- 单次调用 SHALL 支持**一个或多个问题**；每个问题携带 `header`、`question`、2–4 个预设 `options`，以及一个隐式的「自定义输入」入口（用户可不选预设、自行输入文本）。
- 新增两类 trace 事件 `clarification_request` / `clarification_resolved`，通过现有 `agent_trace` SSE 通道下发，遵循 `AgentTraceEvent` 协议（`type`/`task_id`/`seq`/`timestamp`）。
- 新增 HTTP 端点 `POST /api/v1/ai-chat/chat/clarifications/{request_id}/resolve`，把用户答案写回 `PermissionBroker` 的 Future（沿用工具审批的 run_id/session_id/owner_scope 归属与查找逻辑）。
- run snapshot 与重连回放 SHALL 额外携带未决澄清请求（`pending_clarifications`），断线/切会话/刷新后仍能恢复待回答的问题卡片。
- 前端新增「澄清问题卡片」渲染：在 `AgentTraceStream` 中渲染选项按钮 + 自由输入框，支持多问题、必答校验与一次性提交；答案按 `session_id` 隔离存储，与现有 `pendingPermissions` 同构。
- 新增**超时策略设置项**：用户可在设置中选择「澄清超时后基于已知信息继续」；**默认为「超时后取消本轮」**。
- 范围：本期落地于 **DeviceAgent**，但工具、事件、broker、端点与前端组件均按**可复用**方式设计，后续 log_analysis / project_expert / package_search 等 SDK agent 可低成本接入。

## Capabilities

### New Capabilities
- `agent-clarification`: Agent 主动向用户澄清不清晰指令的端到端能力 —— `AskUserQuestion` 工具契约、`clarification_request`/`clarification_resolved` 事件、resolve 端点与 broker 语义、多问题/预设选项+自由输入的数据契约、未决请求快照回放、前端问题卡片渲染、以及超时策略设置项。

### Modified Capabilities
<!-- 现有 capability 的需求文本不发生改写：澄清流程作为全新 capability 自包含描述其对 run snapshot / 前端 store / trace 通道的扩展要求。复用点见 Impact，属实现细节。 -->

## Impact

- **新增后端**：`app/agents/device_agent/clarification.py`（工具 + can-ask 语义 + broker 交互）、`app/agents/device_agent/trace.py`（两个事件常量）、`app/api/ai_chat.py`（resolve 端点）、`app/services/chat_run_service.py`（snapshot 增加 `pending_clarifications`、事件回放）。
- **复用现有 HITL 管线**：`PermissionBroker`（`open/resolve/cancel/close`）、broker 注册表（`ChatRunService._brokers` / `get_broker_by_run_id`）、owner_scope 归属校验，与工具审批共用。
- **配置**：新增 `clarification` 超时与默认行为开关（沿用 `device_agent_permission_timeout_seconds` 量级，新增 `device_agent_clarification_on_timeout`：`cancel`(默认) / `continue`）。
- **新增前端**：`AgentTraceStream.vue` / 新子组件 `ClarificationCard.vue`、`stores/conversationRuns.ts`（`pendingClarifications` 状态 + `submitClarification`）、`api/chat.ts`（`resolveChatClarification`）、`types/agentTrace.ts`（事件与数据类型）、i18n 文案、设置面板开关。
- **国际化**：问题/选项文案由模型按 `locale` 生成；前端按钮（提交/自定义输入占位符/必答校验）走 i18n。
- **非破坏性**：所有新增事件/字段对旧客户端可忽略；不调用 `AskUserQuestion` 时行为与现状完全一致。
