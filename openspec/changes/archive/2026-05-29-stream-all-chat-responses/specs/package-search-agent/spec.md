## ADDED Requirements

### Requirement: 对话框集成走流式 SSE

主对话框（`AIChat.vue`）对重构包 Agent 的调用 SHALL 走 SSE 流式路径（`POST /raven/packages/agent-search` 且 `stream: true`，经前端 `streamPackagesAgentSearch`），而非阻塞式非流式 REST。其 trace 与 `answer_delta` MUST 经与 DeviceAgent / 日志分析 Agent 相同的统一渲染管线实时呈现，三个 Agent 在对话框中的流式行为 MUST 一致。

调用过程中 MUST NOT 长时间停留在静态"正在思考..."占位：一旦后端产出首条 trace 或 `answer_delta`，UI MUST 实时更新。`final` 事件携带的结构化结果（`recommended_package_ids`、`relevant_package_ids` 等）MUST 仍用于推荐包的结构化展示与（登录态下的）会话持久化。

非流式 `agent-search` 端点 MUST 保留供非对话场景调用，本要求 MUST NOT 移除或破坏它。

#### Scenario: 对话框中重构包 Agent 实时呈现

- **WHEN** 用户在对话框中 @重构包 Agent 发起一次检索
- **THEN** 前端 MUST 通过 `stream: true` 订阅 SSE，实时渲染 trace 与逐字答复，UI MUST NOT 全程停留在"正在思考..."占位直到一次性返回

#### Scenario: 三个 Agent 流式行为一致

- **WHEN** 分别向 DeviceAgent、日志分析 Agent、重构包 Agent 发起一次对话
- **THEN** 三者 MUST 都通过 SSE 实时透传 trace，并都以 `answer_delta` 逐字呈现最终答复（在 provider 支持分块流式时）

#### Scenario: 结构化结果仍可用

- **WHEN** 重构包 Agent 流式完成并下发 `final` 事件
- **THEN** `final.data` 中的 `recommended_package_ids` MUST 仍被用于渲染推荐包卡片，登录态下该轮对话 MUST 被持久化

#### Scenario: 非流式端点保留

- **WHEN** 非对话场景以 `stream=false`（或不带 `stream`）调用 `POST /raven/packages/agent-search`
- **THEN** 该端点 MUST 仍返回与既有契约一致的非流式 JSON 响应
