## ADDED Requirements

### Requirement: AgentTraceEvent 事件协议

系统 SHALL 定义统一的 `AgentTraceEvent` 协议，作为 Claude Agent SDK 内部消息流向前端透传的唯一事件 schema。该协议 MUST 同时被 chat 入口 (`/ai-chat/log-analysis/stream`) 和日志详情入口 (`/logs/{log_id}/ai-analysis/trace/stream`) 使用，且字段定义在 chat 与日志详情两侧 MUST 完全一致。

每条事件 MUST 至少携带：`type`、`task_id`、`seq`（单调递增整数）、`timestamp`（epoch 秒，6 位小数）。事件类型 MUST 为以下之一：`run_start`、`run_complete`、`cancelled`、`step_start`、`step_delta`、`step_end`、`thinking_start`、`thinking_delta`、`thinking_end`、`system_notice`、`error`。

同一步骤的 `step_start` / `step_delta` / `step_end` MUST 共享同一个 `step_id`（UUIDv4）；同一段思考的 `thinking_start` / `thinking_delta` / `thinking_end` MUST 共享同一个 `step_id`。

所有事件中可能出现的 URL token（形如 `https://<token>@host/...`）MUST 在发出前被脱敏为 `https://***@host/...`。

#### Scenario: 协议字段在两条传输通道上保持一致

- **WHEN** chat 路径与日志详情路径同时分析同一份日志数据
- **THEN** 两条通道发出的 `AgentTraceEvent` 在相同事件类型上 MUST 拥有完全相同的字段集合（包括字段名与含义），且前端使用同一份 TypeScript 类型即可解析

#### Scenario: 步骤 start/delta/end 共享 step_id

- **WHEN** Agent 调用 `Bash` 工具一次，产生 1 个 `step_start` 与 N 个 `step_delta` 与 1 个 `step_end`
- **THEN** 这 N+2 条事件 MUST 拥有相同的 `step_id`，且 `step_end.seq > 所有 step_delta.seq > step_start.seq`

#### Scenario: token URL 脱敏

- **WHEN** Agent 执行 `git clone https://abc123@example.com/repo.git`，工具输入或输出包含原始 URL
- **THEN** 通过 `AgentTraceEvent` 推送给前端的 `tool_input` 与 `output_chunk` / `output_excerpt` 中 MUST 不包含明文 token，原始 URL MUST 被替换为 `https://***@example.com/repo.git`

### Requirement: chat 入口实时透传

`POST /api/v1/ai-chat/log-analysis/stream` 的 SSE 流 SHALL 在已有的 `log_analysis_status` / `log_analysis_context` / `done` / `error` 事件之外，**新增**事件类型 `agent_trace`，其 payload 为一条 `AgentTraceEvent`。

新增事件 MUST NOT 替代或修改任何现有事件类型；现有客户端在不识别 `agent_trace` 时 MUST 仍能正常解析其余事件并收到最终 `done`。

从 Agent loop 收到 SDK 消息到对应 `agent_trace` 事件被推送给 SSE 客户端的端到端延迟 MUST `<= 500ms`（不计网络往返）。

#### Scenario: 老客户端兼容

- **WHEN** 仅识别 `log_analysis_status` / `done` / `error` 三种事件的旧前端连接 `/ai-chat/log-analysis/stream`
- **THEN** 旧前端 MUST 仍然能收到分析结果，所有 `agent_trace` 帧被静默忽略而不报错

#### Scenario: 新客户端接收完整 trace

- **WHEN** 新前端连接 SSE 并发起一次日志分析
- **THEN** 客户端 MUST 按 seq 顺序收到 `run_start`、若干 `step_*` / `thinking_*` / `system_notice` 事件、最终 `run_complete`，且每条 `agent_trace` 在 Agent 内部产生后 500ms 内到达

### Requirement: chat 入口断线重连重放

当客户端在分析过程中断开并重新发起 SSE 订阅同一 `session_id` 时，系统 SHALL 从头按序重放本次任务已产生的全部 `agent_trace` 事件，再接续推送新事件，直至任务结束。

重放期间事件 `seq` MUST 保持与首次推送一致；前端按 `seq` 去重。

#### Scenario: 中途断线重连

- **WHEN** 客户端在收到 seq=50 时断开，2 秒后用同一 session_id 重连
- **THEN** 重连流 MUST 从 seq=1 开始按序重放全部历史事件，包含断线期间产生的新事件，直到收到 `run_complete`

### Requirement: 日志详情入口 SSE 端点

系统 SHALL 提供 `GET /api/v1/logs/{log_id}/ai-analysis/trace/stream` SSE 端点（`text/event-stream`）用于在日志详情页订阅 trace。响应 MUST 仅由 `AgentTraceEvent` 帧组成（不夹带 `log_analysis_status` 等 chat 专用事件）。

端点 MUST 支持三种状态：

- 任务运行中：实时推送，断线重连重放；
- 任务已完成（`succeeded` / `failed`）：从 `LogRecord.ai_analysis_result.trace_events` 一次性回放全部事件 + 终态事件后关闭流；
- 任务不存在或当前 `log_id` 无 `ai_analysis_task_id`：返回 HTTP 404。

权限 MUST 复用现有日志可见性规则。

#### Scenario: 任务运行中订阅

- **WHEN** 任务在 Celery worker 中运行，前端连接该 SSE 端点
- **THEN** 客户端 MUST 收到从 seq=1 开始的全部历史事件，并继续接收新事件直到 `run_complete`

#### Scenario: 任务已完成后订阅

- **WHEN** 任务已写入 `LogRecord.ai_analysis_result.trace_events` 且状态为 `succeeded`
- **THEN** 客户端 MUST 收到完整事件流（来源是持久化字段）后立即收到 `run_complete` 并被服务端关闭

#### Scenario: 任务不存在

- **WHEN** `log_id` 对应的 `LogRecord` 没有 `ai_analysis_task_id`
- **THEN** 服务端 MUST 返回 HTTP 404 并 NOT 建立 SSE 流

### Requirement: 跨进程 trace 缓冲（Redis）

当 Agent 在 Celery worker 进程中运行时，系统 SHALL 把每条 `AgentTraceEvent` 写入 Redis 有界 list `ai_analysis:trace:{task_id}`。该 list MUST：

- 通过 `LTRIM` 限制长度上限 ≤ 2000 条；
- 通过 `EXPIRE` 设置 TTL 默认 3600 秒（任务结束后留存供短期重连）；
- 写入失败 MUST 仅 logger.warning 不中断 Agent 主流程。

SSE 端点 SHALL 通过 `LRANGE` 增量拉取（轮询间隔 ≤ 250ms），不使用 `BLPOP` 等会消耗事件的命令。

#### Scenario: 单任务事件不丢失

- **WHEN** 一次分析任务在 worker 中产生 1500 条事件
- **THEN** Redis list 中 MUST 至少保留按时间顺序最近的 2000 条以内全部事件，SSE 客户端可拉取到全部 1500 条

#### Scenario: Redis 写入失败不影响主流程

- **WHEN** Redis 暂时不可用导致 emitter 写入抛错
- **THEN** Agent loop MUST NOT 中断，错误 MUST 被 logger.warning 记录，本地 `tool_trace` 仍正常累积

### Requirement: 任务结束 trace_summary 与持久化

任务结束（包括正常完成、取消、错误）时，Agent SHALL 生成 `trace_summary` 字段（包含至少 `thought_duration_seconds: float`、`tool_call_count: int`、`thinking_chars: int`）并通过 `run_complete` / `cancelled` / `error` 事件下发，同时写入返回 dict 的 `ai_analysis_result.trace_summary`。

完整事件流 SHALL 写入 `ai_analysis_result.trace_events` 字段（List[AgentTraceEvent]）以支撑刷新页面后的回放。

旧字段 `ai_analysis_result.tool_trace` SHALL 由后端从 `trace_events` 派生（仅保留 tool_use 类条目），保证旧前端不受影响。

#### Scenario: 正常完成的 summary

- **WHEN** Agent 完成分析，共发起 22 次工具调用、累计思考用时 42.3s
- **THEN** `run_complete` 事件 payload 中 MUST 包含 `trace_summary.tool_call_count == 22` 与 `trace_summary.thought_duration_seconds == 42.3`，并写入 `ai_analysis_result`

#### Scenario: 取消后仍生成 summary

- **WHEN** 用户在第 5 次工具调用进行中取消任务
- **THEN** `cancelled` 事件 payload MUST 包含 `trace_summary`，`tool_call_count` 不少于已完成的 4 次

#### Scenario: 旧 tool_trace 字段保留

- **WHEN** 前端只识别 `ai_analysis_result.tool_trace`（旧字段）
- **THEN** 该字段 MUST 仍由后端从 `trace_events` 派生写入，包含每次 tool_use 的 `{name, input, output_excerpt}`

### Requirement: keep-alive 心跳

SSE 通道 SHALL 在 Agent 长时间未产生 SDK 消息时（≥ 15 秒），主动 emit 至少一条 `system_notice` 事件作为心跳，防止反向代理 / 浏览器空闲超时关闭流。

#### Scenario: 长时间无新消息

- **WHEN** Agent 在执行长耗时工具（如 `git clone`）期间 30 秒没有 SDK 新消息
- **THEN** 客户端 MUST 在这 30 秒内至少收到 1 条 `system_notice` 事件以保持连接活跃
