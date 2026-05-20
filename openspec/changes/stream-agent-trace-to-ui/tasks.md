## 1. 事件协议与 Agent 改造

- [x] 1.1 新建 `app/agents/log_analysis/trace.py`：`AgentTraceEvent` TypedDict（含 `type` 枚举、`seq`、`step_id` 等所有字段）；`build_event(...)` 工厂函数（自动分配 `seq` / `timestamp` / `task_id`）；`coerce_chunk(text, max_bytes=4096)` 切片工具；事件类型常量；`derive_tool_trace(events)` 用于派生旧字段
- [x] 1.2 单测 `tests/agents/log_analysis/test_trace.py`：seq 单调、切片长度边界、URL 脱敏、`derive_tool_trace` 行为
- [x] 1.3 重构 `app/agents/log_analysis/agent.py` 的 `_handle_stream_message`：拆为 `_emit_for_message(msg, *, emitter, seq_counter, step_state)`，按 SDK 消息类型映射成 1~N 条 `AgentTraceEvent`，emitter 不传时仍按原方式 `_log_workflow` + append `tool_trace`
- [x] 1.4 `LogAnalysisAgent.run` 增加 `trace_emitter: Optional[Callable[[AgentTraceEvent], None]]` 参数；emit 异常用 try/except logger.warning 包裹；`_cancelled_result` / 正常返回路径都附加 `trace_events` 与 `trace_summary` 字段；旧 `tool_trace` 由 `derive_tool_trace` 生成
- [x] 1.5 `LogAnalysisAgent.run_sync` 同步包装层把 emitter 透传
- [x] 1.6 单测 `tests/agents/log_analysis/test_agent_trace.py`：构造 fake `query()` async generator 注入若干 SDK message 类型，验证 emitter 收到的事件序列、`run_start` / `run_complete` 终态、取消两阶段事件、emitter 抛错不中断
- [x] 1.7 取消语义：在 `cancel_event.is_set()` 检测点先发 `system_notice{kind: "cancel_requested"}`（仅一次）再 raise `AgentCancelled`

## 2. Chat 入口实时透传

- [x] 2.1 `app/services/log_analysis_chat_service.py` 的 `AgentJob` dataclass 增加 `trace_events: List[Dict] = field(default_factory=list)`；保留 `events` 用于 SSE 帧
- [x] 2.2 `_run_job_async` 构造同步 emitter `lambda ev: (job.trace_events.append(ev), job.events.append({"event": "agent_trace", **ev}))`，传给 `LogAnalysisAgent().run_sync`
- [x] 2.3 `_subscribe` 已有的 buffer 重放机制覆盖 `agent_trace` 帧；新增重连时若 `job.events` 已包含 `agent_trace`，按 seq 顺序整体回放（验证现有 `sent` 游标兼容）
- [x] 2.4 `done` 事件附加 `trace_summary` 与 `trace_events`（供老客户端忽略、新客户端可直接拿历史）
- [x] 2.5 keep-alive 心跳：在 `_subscribe` 内若 ≥ 15s 没有任何新事件且任务运行中，自动 yield 一条 `system_notice{kind: "heartbeat"}` 帧
- [x] 2.6 集成测试 `tests/api/test_log_analysis_chat_stream_trace.py`：用 monkeypatch 注入伪 Agent 推送固定事件序列；通过 TestClient 订阅 SSE，断言收到 `agent_trace` 帧顺序与去重一致

## 3. Celery / 日志详情入口

- [x] 3.1 新建 `app/services/agent_trace_redis.py`：`TraceBuffer.write(task_id, event)` 用 pipeline `rpush + ltrim + expire`；`TraceBuffer.iter_events(task_id, *, from_seq)` 阻塞前 LRANGE；写入失败 logger.warning 不抛
- [x] 3.2 `app/tasks/ai_analysis.py`：构造 emitter 写入 Redis（同时维护 in-memory seq counter），并把完整 `trace_events`、`trace_summary` 写入 `LogRecord.ai_analysis_result`（commit 时一并 update_state PROGRESS meta 只放 summary 不放全部事件，避免 broker 膨胀）
- [x] 3.3 任务正常完成 / 异常 / 取消三种路径都保证 `trace_events` 落库；任务异常时仍生成 `trace_summary`（按已发事件统计）
- [x] 3.4 `app/api/logs.py` 新增 `GET /logs/{log_id}/ai-analysis/trace/stream` SSE endpoint：分三种状态（任务运行中走 Redis 轮询、任务完成走 DB 持久化字段、任务不存在 404）；权限沿用现有 `get_log_for_user`；从 query param 支持 `?from_seq=N` 让客户端断线重连只取增量
- [x] 3.5 集成测试 `tests/api/test_log_trace_stream.py`：mock Redis + DB，三种状态各覆盖一个用例；断线重连用例

## 4. 前端：组件与 composable

- [x] 4.1 新建 `frontend/src/types/agentTrace.ts`：`AgentTraceEvent` TypeScript 类型（discriminated union by `type`），与后端 schema 完全对齐
- [x] 4.2 新建 `frontend/src/composables/useAgentTraceStream.ts`：输入 `eventsRef: Ref<AgentTraceEvent[]>`，输出 `steps: ComputedRef<TraceStepView[]>`、`thinkings`、`runningRef`、`summaryRef`；内部按 `step_id` 维护 map、按 `seq` 排序去重、`step_delta.output_chunk` 增量拼接、收到 `step_end` / `thinking_end` 把状态切到终态
- [x] 4.3 新建 `frontend/src/components/AgentTraceStream.vue`：props `events: AgentTraceEvent[]`、`running: boolean`、可选 `onCancel: () => void`、可选 `toolNameMap?`；渲染卡片列表（每张卡片单独 `<TraceStepCard>` 子组件维持自身 expand 状态）；最终汇总条覆盖逻辑（默认折叠，点击展开）
- [x] 4.4 工具名映射表 `frontend/src/composables/useToolDisplayName.ts`：内置 `Bash`、`Read`、`Grep`、`Glob`、`Skill`、`mcp__project_repo__lookup_project_repo` 默认映射；未匹配回退原名
- [x] 4.5 Storybook / fixtures：`frontend/src/components/__fixtures__/agentTrace.fixture.ts` 包含 normal / cancel / error / 大量 thinking 四组事件流；本地手工回放验证四态与折叠行为
- [ ] 4.6 单测 `frontend/src/composables/useAgentTraceStream.spec.ts`：seq 乱序去重、`step_delta` 累积、终态切换、`trace_summary` 优先级（end vs computed fallback）

## 5. 前端：双入口接入

- [x] 5.1 `frontend/src/views/AIChat.vue`：消息 dataclass 新增 `traceEvents: AgentTraceEvent[]`；`processChunk` 中 `payload.event === "agent_trace"` 时把 payload append 到当前 assistant 消息的 `traceEvents`；assistant 气泡上方挂载 `<AgentTraceStream :events=... :running=... :onCancel=...>`；`done` 事件触发 `running=false`
- [x] 5.2 `AIChat.vue` 重连场景：已有重连逻辑会重放 `_subscribe` 缓冲，前端按 seq 去重即可（已由 composable 兜底）；手工验证一次断线
- [x] 5.3 `frontend/src/views/LogDetail.vue`：AI 分析模块挂载 `<AgentTraceStream>`；新建 SSE consumer 指向 `/api/v1/logs/{log_id}/ai-analysis/trace/stream`，运行态打开、终态/卸载关闭；任务已完成或刷新进入时从 `ai_analysis_result.trace_events` 一次性 seed
- [x] 5.4 LogDetail 暂不暴露取消按钮（后端无对应 cancel API）；隐藏即可
- [ ] 5.5 视觉验证：用 fixture 在两侧手工跑一次，确认渲染一致

## 6. 向后兼容与回滚

- [ ] 6.1 验证旧前端（不识别 `agent_trace`）仍能正常解析 `done` / `error` / `log_analysis_status`：用 `curl` 模拟订阅，肉眼检查
- [x] 6.2 验证 `LogRecord.ai_analysis_result.tool_trace` 仍然非空且结构与旧版本一致（写一个 snapshot 测试）
- [x] 6.3 文档：在 `docs/` 下补一篇 `docs/agent_trace_protocol.md`（schema 表 + 事件序列示例 + 两条 SSE 通道说明）

## 7. 监控与上线

- [ ] 7.1 新增 metric `ai_analysis_trace_events_emitted_total{kind}`（counter）与 `ai_analysis_trace_redis_bytes`（gauge）；接入现有 Prometheus 暴露面
- [ ] 7.2 Loadtest：本地用 fake agent emitter 模拟一次 1500 事件的 trace，分别走 chat 与 log detail 两条通道，统计端到端 P99 延迟（目标 ≤ 500ms）
- [x] 7.3 Runbook：在 `docs/runbook/` 增加 trace 通道排错条目（Redis 不可用、SSE 早断、事件丢失三种症状的定位步骤）
- [ ] 7.4 灰度：先把后端字段写入与 Redis 缓冲合入，再合前端组件；分两次发布
