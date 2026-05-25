## 1. 数据模型与迁移

- [x] 1.1 新增 `app/models/chat_run.py`（或并入现有 user/chat model），定义 `ChatAgentRun`：`id/session_id/user_id/agent_kind/status/user_message/request_json/workspace_path/answer/model/error/trace_events_json/started_at/finished_at/timestamps`
- [x] 1.2 新增 Alembic migration 创建 `chat_agent_runs` 表，并为 `(user_id, status)`、`session_id`、`updated_at` 建索引
- [x] 1.3 在启动流程或 `ChatRunService.initialize()` 中扫描 `queued/running` 旧 run，标记为 `stale` 并写入可读错误
- [x] 1.4 扩展 `app/models/user.py::ChatSessionSummary`，增加 optional `active_run_id/run_status/run_agent_kind/run_started_at/run_updated_at`
- [x] 1.5 扩展前端 `frontend/src/types/index.ts::ChatSessionSummary` 同名 optional 字段

## 2. 会话历史增量写入

- [x] 2.1 在 `chat_history_service` 新增 `append_message(db, user_id, session_id, role, content)`，支持只写 user 或 ai 单条消息
- [x] 2.2 新增/调整 session activity helper：写入单条消息时正确维护 `message_count` 与 `last_message_at`
- [x] 2.3 保留 `save_exchange()` 兼容旧调用；内部可改为调用新 helper，避免重复逻辑
- [x] 2.4 单元测试：新 session append user 后 message_count=1；append ai 后 message_count=2；soft-deleted session 被恢复

## 3. ChatRunService 后端运行管理

- [x] 3.1 新增 `app/services/chat_run_service.py`：定义 `ChatRunJob` dataclass、内存 registry、finished retention、lazy eviction
- [x] 3.2 实现 `start_device_run(payload, db, user) -> ChatRunJob`：创建/确保 session，立即落库 user message，创建 `chat_agent_runs` running 记录，启动后台 task
- [x] 3.3 实现 `_run_device_job(job, ctx)`：驱动 `DeviceAgent.run_stream(ctx)`，把每个事件 append 到 `job.events/trace_events`，终态用新 DB session 写 assistant 消息与 run 结果
- [x] 3.4 实现 `subscribe(run_id)`：先 replay buffered events，再实时推送；SSE 断开不取消 job；15s heartbeat
- [x] 3.5 实现 `get_active_run(session_id, user)`、`get_snapshot(run_id, user)`、`cancel(run_id, user)`、`evict_finished_jobs()`
- [x] 3.6 加入并发保护：同一 session 只允许一个 active run；不同 session 可同时运行；可选 `chat_agent_max_concurrent_runs_per_user` 限流
- [x] 3.7 后端测试：两个 session 同时启动 fake DeviceAgent，各自产生事件并成功完成，事件和答案不串线
- [x] 3.8 后端测试：订阅 A run 后主动断开，run 继续完成；重新订阅可 replay 全部事件与 done
- [x] 3.9 后端测试：同一 session active 时再次发送新消息返回 409，并携带 active_run_id

## 4. DeviceAgent run_id 与工作区隔离

- [x] 4.1 扩展 `DeviceAgentContext` 增加 `run_id`
- [x] 4.2 修改 `app/agents/device_agent/workspace.prepare_session(session_id, run_id)`，创建包含 run_id 的独立路径
- [x] 4.3 修改 DeviceAgent trace task_id：使用 `run_id`，并在所有 SSE payload 中带 `run_id/session_id`
- [x] 4.4 将 workspace path 回写到 `ChatAgentRun.workspace_path`
- [x] 4.5 测试：并发两个 run 时 workspace path 不同，且均位于各自 session/run 目录下；终态后按策略清理

## 5. 权限 broker 改为 run-scoped

- [x] 5.1 将 `AIChatService.permission_broker_registry` 迁移到 run service：`permission_broker_by_run_id`
- [x] 5.2 `tool_permission_request/resolved` 事件增加 `run_id`
- [x] 5.3 `POST /chat/permissions/{request_id}/resolve` body 增加 optional `run_id`；解析优先级为 run_id -> session_id -> legacy scan
- [x] 5.4 权限校验：resolver 只能 resolve 当前用户自己的 run；匿名 run 保持现有进程内可见语义
- [x] 5.5 测试：两个 session 同时各有 pending permission，按 run_id resolve 时只解锁对应 run

## 6. API 端点改造

- [x] 6.1 改造 `POST /api/v1/ai-chat/chat/stream` 为 create-or-subscribe；保持现有 SSE 帧格式兼容
- [x] 6.2 新增 `GET /api/v1/ai-chat/chat/sessions/{session_id}/active-run`
- [x] 6.3 新增 `GET /api/v1/ai-chat/chat/runs/{run_id}`
- [x] 6.4 新增 `GET /api/v1/ai-chat/chat/runs/{run_id}/stream`
- [x] 6.5 新增 `POST /api/v1/ai-chat/chat/runs/{run_id}/cancel`
- [x] 6.6 扩展 `list_chat_sessions`：为每个 session 叠加 active run 状态，输出 optional run 字段
- [x] 6.7 API 测试：active-run 404/200、run snapshot 权限、run stream replay、cancel terminal event

## 7. LogAnalysis 主对话适配

- [x] 7.1 将 `LogAnalysisChatService` 创建/完成/cancel 的 `AgentJob` 状态投影到 `chat_agent_runs`
- [x] 7.2 为日志分析 active job 提供统一 snapshot：`run_id/session_id/agent_kind/events/trace_events/status/answer/error`
- [x] 7.3 前端日志分析路径改用 conversation run store 的 active run 状态；移除全局 `activeLogAnalysisSessionId`
- [x] 7.4 测试：A 会话日志分析运行时切到 B 会话可发送 DeviceAgent；回 A 会话可恢复日志分析 trace 与取消按钮

## 8. 前端 per-session conversation store

- [x] 8.1 新增 `frontend/src/stores/conversationRuns.ts`（命名可调整），按 session_id 保存 messages、activeRunId、runStatus、isSending、pendingPermissions、subscription
- [x] 8.2 实现 `loadSession(sessionId)`：加载 DB messages，再查询 active-run，存在则 merge virtual assistant message 并订阅 run stream
- [x] 8.3 实现 `startRun(sessionId, payload)`：本地 append user + assistant placeholder，创建/订阅 backend run
- [x] 8.4 实现 `applyRunEvent(sessionId, runId, payload)`：按 run_id+seq 去重，只更新匹配 session 的 state
- [x] 8.5 实现切会话时 abort 旧 subscription 但不 cancel 后端 run
- [x] 8.6 将 pending HITL 弹窗从 `AIChat.vue` 局部 ref 迁移到 run store，按当前 session/run 显示
- [x] 8.7 前端单元测试：A run streaming 时切 B，A 后续事件不写入 B；B 可发送并独立完成

## 9. AIChat.vue 与 WorkbenchLayout.vue 改造

- [x] 9.1 `AIChat.vue` 删除全局 `chatHistory/sessionId/isSending/pendingPermissions` 主状态，改为从 conversation store 读取当前 session state
- [x] 9.2 输入框和发送按钮只按当前 session 的 `isSending` 禁用；其它 session running 不影响当前 session
- [x] 9.3 点击历史 running session 时自动恢复 run snapshot + stream；不重复创建新 run
- [x] 9.4 `WorkbenchLayout.vue` 会话行显示 running spinner，hover 菜单不遮挡 spinner
- [x] 9.5 `chatSession` store 合并后端 `run_status` 与本地 running overlay；有 running run 时每 5s 轻量刷新
- [x] 9.6 前端组件/交互测试：侧边栏 spinner 出现/消失；点击 running 会话恢复 trace；终态刷新后显示最终 DB 消息

## 10. 回归与发布检查

- [~] 10.1 后端测试集：`tests/api/test_chat_happy_path.py`、DeviceAgent tests、HITL tests、LogAnalysis chat stream tests 通过 — `test_chat_happy_path.py` 与其它 26 个 chat 测试全部通过（含 `_run_device_job` 的 `done` payload 补回 `messages` 字段）；`test_chat_hitl_integration.py::test_chat_stream_full_hitl_flow`、`test_log_analysis_chat_stream_trace.py` 中 2 个 reconnect-replay 用例在主分支上即已超时失败，与本变更无关，单独跟踪
- [x] 10.2 新增并发集成测试：两个不同 session 同时 fake agent run，总耗时证明并发而非串行等待 — `tests/api/test_chat_concurrent_runs.py::test_two_sessions_run_concurrently_without_event_crosstalk`
- [x] 10.3 前端 `vue-tsc --noEmit` 通过
- [ ] 10.4 前端手测：A 会话发消息后切 B；侧边栏 A 转圈；B 可发消息；回 A 完整恢复内容
- [ ] 10.5 手测 HITL：A 会话弹权限确认时切 B；回 A 弹窗仍在，可 allow/deny 并继续
- [x] 10.6 文档更新：`DEPLOY_USAGE.md` 补充多会话后台 run、stale run、工作区隔离和并发限制说明

## 11. 多用户隔离补充

- [x] 11.1 数据模型补充 `owner_scope`，并新增/调整 `(owner_scope, session_id, status)` 索引；登录用户 owner_scope 从 `user_id` 派生，匿名用户 owner_scope 由服务端生成（cookie/header `X-Client-Scope` 承载）
- [x] 11.2 将所有 active run registry 从裸 `session_id` key 改为 `(owner_scope, session_id)` key；禁止任何 active-run lookup 只用 session_id
- [x] 11.3 所有 run snapshot / stream / cancel API 按 `owner_scope` 校验归属；非归属请求返回 404，且不泄露 run 内容
- [x] 11.4 权限 broker legacy scan fallback 按 `owner_scope` 过滤；user B 不能 resolve user A 的 pending permission
- [x] 11.5 DeviceAgent workspace 路径加入 `owner_scope` 或等价隔离前缀，确保两个用户相同 `session_id` 时 `.claude/skills` 不共享
- [x] 11.6 `list_chat_sessions` 叠加 active run overlay 时只查询当前用户 owner_scope 下的 running run
- [x] 11.7 后端测试：两个用户使用相同 `session_id` 同时启动 run，各自 active-run lookup 命中自己的 run，互不 409
- [x] 11.8 后端测试：user B 请求 user A 的 run snapshot/stream/cancel/permission resolve 均被拒绝，且 user A run 不受影响
