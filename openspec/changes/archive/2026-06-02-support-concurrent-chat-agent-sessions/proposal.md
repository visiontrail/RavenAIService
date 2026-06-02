## Why

当前 AI 对话页仍是“单活跃会话”的运行模型：`frontend/src/views/AIChat.vue` 只有一份 `chatHistory` / `sessionId` / `isSending` / `pendingPermissions`，发送后会在同一个组件实例里一直 `await fetch('/api/v1/ai-chat/chat/stream')` 直到 SSE 结束。用户在 A 会话发起 DeviceAgent 后切到 B 会话或点击“新建对话”，A 的 fetch loop 仍会把后续事件写进当前页面这份共享状态；同时全局 `isSending` 会阻止 B 会话发送消息。侧边栏也只展示 `ChatSessionSummary` 的标题/消息数，没有“正在运行”的状态。

后端也有同样的生命周期耦合：`AIChatService.chat_stream()` 直接在当前 HTTP SSE 请求里驱动 `DeviceAgent().run_stream(ctx)`，客户端断开会触发 `asyncio.CancelledError`，没有类似 `LogAnalysisChatService.AgentJob` 的后台任务、事件缓冲、重连重放和完成后持久化。结果是：用户离开对话窗口后无法可靠恢复正在生成的内容，也无法在多个会话中同时启动独立 Agent loop。

我们要把“对话窗口”从“Agent loop 生命周期”里解耦：发送消息只负责创建一个 session-scoped run；run 在后端后台独立运行、独立工作目录、独立事件缓冲；任意前端窗口只是订阅者，可以离开、切换、稍后重新进入并完整重放。

## What Changes

- 新增 **Chat Agent Run 管理层**：`app/services/chat_run_service.py`（或同名模块）维护 `ChatAgentRun` 后台任务注册表，按 `run_id` / `session_id` 管理 DeviceAgent 与主对话 LogAnalysisAgent 的运行状态、SSE 事件缓冲、权限 broker、完成结果和保留期。
- 新增持久化模型与迁移：`chat_agent_runs` 表记录 `run_id`、`session_id`、`user_id`、`agent_kind`、`status`、用户输入、目标设备/日志上下文、`workspace_path`、`answer`、`model`、`error`、`trace_events_json`、`started_at`、`finished_at`。运行中的事件仍以内存缓冲为实时源，完成后写入 DB 供刷新/晚到订阅回放。
- 改造 `AIChatService.chat_stream()`：收到 `POST /chat/stream` 时只“创建或附着到”后台 run，然后把当前 SSE 连接作为订阅者；SSE 断开不取消 Agent loop。完成后由后台任务使用新的 DB session 持久化 user/assistant exchange、标题和 run 终态。
- 复用/抽象 `LogAnalysisChatService` 的后台 Job 模式：主对话日志分析继续支持文件上传与持久工作区，但前端统一按 `run_id/session_id` 订阅状态，避免 `AIChat.vue` 的 `isSending` 卡住其它会话。
- 扩展 API：
  - `POST /api/v1/ai-chat/chat/stream` 保持兼容：可创建 run 并实时订阅；若同一 session 已有运行中 run，则无新消息时附着重放，有新消息时返回 409。
  - `GET /api/v1/ai-chat/chat/runs/{run_id}`：返回 run 快照（状态、answer、error、trace_events、pending_permission 等）。
  - `GET /api/v1/ai-chat/chat/runs/{run_id}/stream`：只订阅既有 run，先重放事件再接续实时事件。
  - `GET /api/v1/ai-chat/chat/sessions/{session_id}/active-run`：返回该会话当前运行中的 run，供点击历史恢复。
  - `POST /api/v1/ai-chat/chat/runs/{run_id}/cancel`：显式取消运行中的 run。
  - `POST /chat/permissions/{request_id}/resolve` 增加 `run_id` 定位，保留 `session_id` 兼容。
- 扩展会话摘要：`ChatSessionSummary` 增加可选 `active_run_id`、`run_status`、`run_agent_kind`、`run_started_at`、`run_updated_at`；`list_chat_sessions` 叠加运行中 run 状态，侧边栏可显示转圈等待图标。
- 明确 **多用户隔离**：所有 active-run registry、snapshot/stream/cancel、权限裁决、会话列表 run overlay 和工作区路径都必须按 `owner_scope + session_id + run_id` 隔离；即使两个用户提交相同 `session_id`，也不能互相看到、订阅、取消或裁决对方的 run。
- 前端新增 **per-session conversation state**：
  - Pinia store 按 `session_id` 保存消息列表、当前 run、订阅状态、pending permissions、局部 `isSending`。
  - `AIChat.vue` 渲染当前选中 session 的状态，不再持有全局唯一 `chatHistory/isSending`。
  - 用户离开 A 会话时 A 的 run 继续由 store 或后端维护；进入 B 会话可立即发送另一条消息，B 会话创建独立 run。
  - 点击侧边栏正在运行的会话时，先加载 DB 历史，再拉取 active run 快照并打开 `run_id/stream` 重放，恢复用户消息、assistant 占位、trace、HITL 弹窗和最终答案。
- DeviceAgent 工作区改为 owner/run-scoped：`prepare_session(session_id, run_id, owner_scope)` 创建 `<base>/device_agent/<owner_scope>/<session_id>/<run_id>/`（或等价安全路径），确保多用户、多会话、多个并发 run 物理隔离；完成/取消后按现有策略清理，必要时可在测试/调试配置下短期保留。

## Capabilities

### New Capabilities

- `chat-agent-session-runs`：定义对话 Agent 后台 run 的生命周期、状态机、事件缓冲/重放、并发边界、多用户归属隔离、权限 broker 定位、owner/run-scoped 工作区和持久化恢复语义。
- `chat-conversation-ui`：定义前端多会话 UI 状态、侧边栏运行图标、点击运行中会话恢复、多个会话并发发送和 per-session HITL 弹窗行为。

### Modified Capabilities

- `device-agent`：DeviceAgent 不再直接绑定到单个 HTTP SSE 请求生命周期；由 run manager 在后台任务中驱动。工作目录从“请求级随机目录”收敛为包含 `run_id` 的隔离路径。
- `agent-trace-stream` / `agent-trace-ui`：DeviceAgent trace 与主对话 LogAnalysis trace 都通过 run 订阅通道重放；客户端按 `run_id + seq` 去重，而不是只依赖当前组件里的 `answerMessageId`。

## Impact

- **后端服务**：新增 `chat_run_service.py`；重写 `AIChatService.chat_stream` 的执行模型；权限 broker registry 从 `{session_id: broker}` 扩展为 `{run_id: broker}` + owner/session fallback；后台任务使用 `db_manager.session_factory()` 自行持久化。
- **数据库**：新增 Alembic migration 创建 `chat_agent_runs` 表；`ChatSessionSummary` Pydantic/TS 类型增加 optional run 字段，不破坏旧客户端。
- **API**：新增 run snapshot/stream/cancel/active-run 端点；保留现有 `/chat/stream` 数据帧格式与 `done/error/session/run_*` 事件。
- **前端**：`chatSession` store 增加运行态 overlay；新增 `conversationRun`/`conversationState` store（名称实现时定）；`WorkbenchLayout.vue` 会话行显示运行 spinner；`AIChat.vue` 从 session-scoped store 读取/写入消息和发送状态。
- **测试**：新增后端并发集成测试（两个 session 同时跑两个 fake DeviceAgent run，工作区不同、事件不串线、断开后可重连）；前端 store/unit 测试覆盖 A 会话运行时切 B 会话发送；组件测试覆盖 sidebar spinner 与点击恢复。
- **非目标**：本变更不支持同一会话内同时跑两轮 user turn；同一 session 有 active run 时，新的用户消息应被禁用或返回 409。也不承诺服务进程重启后继续执行未完成的 in-memory Agent loop；重启后未终态 run 标记为 `failed/stale` 并允许用户重试。
