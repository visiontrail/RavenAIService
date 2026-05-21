## MODIFIED Requirements

### Requirement: Agent loop 消息处理

`LogAnalysisAgent.run()` SHALL 在异步处理 Claude Agent SDK `query()` 返回的每条消息时，除了将事件写入本地结构化日志（`_log_workflow`）并累积 `tool_trace` 之外，**额外**通过可选注入的 `trace_emitter: Callable[[AgentTraceEvent], None] | None` 把每条 SDK 消息转换为一条或多条 `AgentTraceEvent` 并外发。

`trace_emitter` MUST 满足：

- 类型为同步函数（非协程），返回值忽略；调用方在不同 event loop / 不同线程间共享同一 agent 实例时无需额外适配；
- 不传 emitter（`None`）时，Agent 行为 MUST 与现状一致（向后兼容），即仅写日志与累积 `tool_trace`；
- emitter 内部抛出异常 MUST NOT 中断 agent 主流程，仅 logger.warning 记录。

每条 SDK 消息按以下映射转化为事件：

- 进入 loop 前发 `run_start`（携带 `model`、`provider`）；
- 退出 loop 后发 `run_complete`（携带 `trace_summary`、`final_text`）或 `cancelled`（取消时）或 `error`（异常时）；
- assistant 文本块：拆分为 `thinking_start` / `thinking_delta`*（按 ≤ 4 KB 切片）/ `thinking_end`；
- tool_use 块：发 `step_start{tool_name, tool_input}`；
- tool_result 块：先发若干 `step_delta{output_chunk}`（按 ≤ 4 KB 切片），再发 `step_end{status, output_excerpt, duration_seconds}`；
- system / 其他 subtype 消息：发 `system_notice{subtype, detail}`。

#### Scenario: 不传 emitter 行为不变

- **WHEN** 调用方以 `LogAnalysisAgent().run(ctx)` 调用（不传 `trace_emitter`）
- **THEN** Agent MUST 完成分析并返回与现状结构一致的 result dict，且 NOT 因为缺失 emitter 报错

#### Scenario: emitter 收到完整事件序列

- **WHEN** 调用方传入收集型 emitter `collected = []; trace_emitter=collected.append`
- **THEN** `collected` MUST 以 `run_start` 起、以 `run_complete` / `cancelled` / `error` 之一止，期间包含本次分析全部 tool / thinking / system 事件，按 `seq` 严格递增

#### Scenario: emitter 抛错不影响主流程

- **WHEN** 调用方传入会随机抛错的 emitter
- **THEN** Agent loop MUST 继续运行至自然结束，最终 result dict MUST 与传入正常 emitter 时具有相同 `status` 和 `summary`

### Requirement: result dict 扩展字段

`LogAnalysisAgent.run()` 返回的 result dict SHALL 在现有字段基础上**新增**：

- `trace_events: List[AgentTraceEvent]` — 本次 agent loop 产生的完整事件流（含 `run_start`、`run_complete` 等终态）；
- `trace_summary: Dict` — 至少包含 `thought_duration_seconds: float`、`tool_call_count: int`、`thinking_chars: int`。

现有字段 `tool_trace` SHALL 继续被填充，且 MUST 由 `trace_events` 派生（仅保留 tool_use 类条目，结构 `{name, input, output_excerpt}`），以保证旧消费者不感知本次变更。

#### Scenario: 新字段被填充

- **WHEN** Agent 正常完成
- **THEN** 返回 dict MUST 同时包含非空的 `trace_events` 列表、`trace_summary` 字典以及由其派生的 `tool_trace` 列表

#### Scenario: tool_trace 派生一致性

- **WHEN** result 同时包含 `trace_events` 与 `tool_trace`
- **THEN** `tool_trace` 中的条目 MUST 与 `trace_events` 中所有 `step_end` 事件一一对应（按 step_id 关联），`name == tool_name`、`input == tool_input`、`output_excerpt == output_excerpt`

### Requirement: 取消时的事件语义

当 `cancel_event` 被外部设置后，Agent SHALL 在下一次 SDK 消息到达前的检查点：

1. 立即通过 emitter 发出 `system_notice{kind: "cancel_requested"}`（如果之前未发过同 kind 事件）；
2. 抛出内部 `AgentCancelled`，触发外层捕获；
3. 在退出 loop 前发 `cancelled` 终态事件，并在返回的 result dict 中携带 `trace_events` 与 `trace_summary`。

#### Scenario: 取消两阶段反馈

- **WHEN** 外部在第 5 次 tool_use 进行中 set 了 cancel_event
- **THEN** 收集型 emitter 收到的事件序列 MUST 满足：先一条 `system_notice{kind: "cancel_requested"}`，再一条 `cancelled`，且 `cancelled` 后无任何额外事件

#### Scenario: 取消结果仍带 summary

- **WHEN** Agent 因 cancel_event 退出
- **THEN** 返回 dict MUST 包含 `trace_summary`，其 `tool_call_count` 不少于已发出 `step_end` 的次数
