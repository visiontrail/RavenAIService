## MODIFIED Requirements

### Requirement: AgentTraceEvent 事件协议

系统 SHALL 定义统一的 `AgentTraceEvent` 协议，作为 Claude Agent SDK 内部消息流向前端透传的唯一事件 schema。该协议 MUST 同时被 chat 入口 (`/ai-chat/log-analysis/stream`) 和日志详情入口 (`/logs/{log_id}/ai-analysis/trace/stream`) 使用，且字段定义在 chat 与日志详情两侧 MUST 完全一致。

每条事件 MUST 至少携带：`type`、`task_id`、`seq`（单调递增整数）、`timestamp`（epoch 秒，6 位小数）。事件类型 MUST 为以下之一：`run_start`、`run_complete`、`cancelled`、`step_start`、`step_delta`、`step_end`、`thinking_start`、`thinking_delta`、`thinking_end`、`answer_delta`、`system_notice`、`error`。

`answer_delta` MUST 携带 `text_chunk`（≤ 4 KB UTF-8），语义为助手面向用户的**最终答复正文**的增量片段。同一轮答复内可有 N 条 `answer_delta`，按 `seq` 升序拼接 MUST 等价于 `run_complete.final_text`（脱敏一致前提下）。`answer_delta` MUST NOT 用于思考内容（`thinking_delta`）或工具输出（`step_delta`）。

同一步骤的 `step_start` / `step_delta` / `step_end` MUST 共享同一个 `step_id`（UUIDv4）；同一段思考的 `thinking_start` / `thinking_delta` / `thinking_end` MUST 共享同一个 `step_id`。

所有事件中可能出现的 URL token（形如 `https://<token>@host/...`）MUST 在发出前被脱敏为 `https://***@host/...`。

#### Scenario: 协议字段在两条传输通道上保持一致

- **WHEN** chat 路径与日志详情路径同时分析同一份日志数据
- **THEN** 两条通道发出的 `AgentTraceEvent` 在相同事件类型上 MUST 拥有完全相同的字段集合（包括字段名与含义），且前端使用同一份 TypeScript 类型即可解析

#### Scenario: 步骤 start/delta/end 共享 step_id

- **WHEN** Agent 调用 `Bash` 工具一次，产生 1 个 `step_start` 与 N 个 `step_delta` 与 1 个 `step_end`
- **THEN** 这 N+2 条事件 MUST 拥有相同的 `step_id`，且 `step_end.seq > 所有 step_delta.seq > step_start.seq`

#### Scenario: answer_delta 拼接等价于 final_text

- **WHEN** 一轮答复产生 [answer_delta{text_chunk:"你好"}, answer_delta{text_chunk："，世界"}] 后收到 `run_complete{final_text:"你好，世界"}`
- **THEN** 按 seq 升序拼接全部 `answer_delta.text_chunk` MUST 等于 `run_complete.final_text`（脱敏一致前提下）

#### Scenario: token URL 脱敏

- **WHEN** Agent 执行 `git clone https://abc123@example.com/repo.git`，工具输入或输出包含原始 URL
- **THEN** 通过 `AgentTraceEvent` 推送给前端的 `tool_input` 与 `output_chunk` / `output_excerpt` 中 MUST 不包含明文 token，原始 URL MUST 被替换为 `https://***@example.com/repo.git`

### Requirement: chat 入口断线重连重放

当客户端在分析过程中断开并重新发起 SSE 订阅同一 `session_id` 时，系统 SHALL 从头按序重放本次任务已产生的全部 `agent_trace` 事件（包含 `answer_delta`），再接续推送新事件，直至任务结束。

重放期间事件 `seq` MUST 保持与首次推送一致；前端按 `seq` 去重。`answer_delta` 与 `step_delta` / `thinking_delta` 一样纳入同一持久化与去重集合，重连后增量答复 MUST 不重复、不丢段。

#### Scenario: 中途断线重连

- **WHEN** 客户端在收到 seq=50 时断开，2 秒后用同一 session_id 重连
- **THEN** 重连流 MUST 从 seq=1 开始按序重放全部历史事件，包含断线期间产生的新事件，直到收到 `run_complete`

#### Scenario: 重连后答复不重复

- **WHEN** 客户端在已收到部分 `answer_delta`（seq 截至 30）后断开并用同一 session_id 重连
- **THEN** 重连流 MUST 从 seq=1 重放含全部 `answer_delta`，前端按 seq 去重后渲染出的答复正文 MUST 与不断线时完全一致（无重复字符、无缺段）

## ADDED Requirements

### Requirement: Agent 最终答复逐字流式

参与主对话框的 Agent（DeviceAgent、日志分析 Agent、重构包 Agent）SHALL 在生成最终答复正文时逐字（增量）发出 `answer_delta` 事件，而非仅在 `run_complete` 一次性下发全文。

实现 MUST 通过开启 Claude Agent SDK 的分块流式（`ClaudeAgentOptions.include_partial_messages`）获取原生文本增量，并将其翻译为 `answer_delta`。当激活的 provider 不支持分块流式时，系统 MUST 静默降级：不发 `answer_delta`，仍在 `run_complete.final_text` 提供权威全文，行为不退化。

`run_complete.final_text` MUST 始终为本轮答复的权威全文（已脱敏 / 已裁剪），用于持久化与重连重放的最终校正。

#### Scenario: 支持分块流式的 provider 逐字下发

- **WHEN** provider 支持分块流式，Agent 生成一段较长答复
- **THEN** 客户端 MUST 在 `run_complete` 之前按 seq 顺序收到多条 `answer_delta`，每条在 SDK 产出该文本增量后 ≤ 500ms 到达

#### Scenario: 不支持分块流式的 provider 降级

- **WHEN** 激活的 provider 不支持 `include_partial_messages`
- **THEN** 系统 MUST NOT 发出任何 `answer_delta`，但 MUST 仍在 `run_complete.final_text` 中提供完整答复，客户端据此整段渲染
