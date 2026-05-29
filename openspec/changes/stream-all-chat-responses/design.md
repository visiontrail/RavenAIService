## Context

主对话框（`AIChat.vue` → `sendMessage`）分流到三个 Agent：

| Agent | 触发路径 | 当前传输 | 答复正文呈现 |
|---|---|---|---|
| 日志分析 | `runsStore.startLogAnalysisRun` | SSE（`AgentTraceEvent`） | `run_complete.final_text` 整段 |
| Device | `runsStore.startDeviceRun` | SSE（`AgentTraceEvent`） | `run_complete.final_text` 整段 |
| 重构包 | `runPackageAgent` → `searchPackagesByAgent` | **阻塞 REST** | 一次性 `targetMessage.content = aiContent` |

`AgentTraceEvent` 协议（`docs/agent_trace_protocol.md`）已定义 11 种事件，其中 `thinking_delta`（`text_chunk`）、`step_delta`（`output_chunk`）已是逐块增量，但**助手最终答复正文没有对应的增量事件**——它在 SDK 返回完整 `TextBlock` 时被存入 `state.final_text`，再于 `run_complete` 一次性下发。前端 `conversationRuns.ts:280-282` 对应地一次性写入 `target.content`。

技术前置已验证：`claude-agent-sdk` 0.2.82 的 `ClaudeAgentOptions.include_partial_messages: bool` 为 `True` 时，`query()` 会额外产出 `StreamEvent`，其 `.event` 字段承载原生 Anthropic stream 事件（`content_block_delta` / `delta.type == "text_delta"` / `delta.text`）。重构包流式所需的后端 SSE（`/packages/agent-search` `stream=true`）与前端 `streamPackagesAgentSearch` 也已存在，仅未被对话框接线。

## Goals / Non-Goals

**Goals:**
- 三个 Agent 的最终答复正文在对话框中逐字（增量）呈现，而非整段突现。
- 重构包 Agent 与另外两个 Agent 走同一条 SSE + 统一渲染管线。
- 扩展非破坏：新增事件不影响旧客户端，`run_complete.final_text` 仍是权威全文。

**Non-Goals:**
- 不改造 `step_delta` / `thinking_delta` 的现有语义。
- 不引入新的对话入口或新 Agent。
- 不改变重构包 Agent 的结构化结果格式（`recommended_package_ids` 等）与持久化字段。
- 不为匿名 `/chat/stream`（`chunk` 机制）的 general agent 路径改协议（其本就增量；仅在对齐时复用渲染）。

## Decisions

### 决策 1：新增 `answer_delta` 事件，而非复用 `thinking_delta` 或 `step_delta`
`answer_delta { step_id?, text_chunk }`，`text_chunk` ≤ 4 KB UTF-8，语义为"助手面向用户的最终答复正文增量"。
- **为何不复用 `thinking_delta`**：思考内容在 UI 中折叠展示且可被脱敏裁剪，与最终答复正文是不同渲染目标，混用会破坏前端区分。
- **为何不复用 `step_delta`**：`step_delta` 绑定工具步骤 `step_id`，答复正文不属于任何工具步骤。
- **替代方案**：仅靠 `run_complete.final_text`（被否，无法逐字）；前端模拟打字机动画（被否，是伪流式，与真实生成节奏脱节，且对长答复延迟无改善）。

### 决策 2：后端统一开启 `include_partial_messages`，由各 Agent 的消息处理函数翻译 `StreamEvent`
在 `build_options` 增加可选入参（默认 `True`，provider 不支持时静默降级），三处 `_emit_for_message` 增加 `StreamEvent` 分支：解析 `event["delta"]["text"]` → 累积 → 发出 `answer_delta`。完整 `TextBlock` 仍照旧写入 `state.final_text` 作为权威全文。
- **为何放在各 Agent**：trace 发射逻辑本就分散在各 Agent 的 `_emit_for_message`；集中化是更大重构，超出本变更范围。可将 `StreamEvent` 解析抽到 `trace.py` 共享 helper 以避免三处重复。
- **风险点**：partial 文本与最终完整 `TextBlock` 可能重叠/不完全一致 → 见决策 4 的前端校正。

### 决策 3：重构包 Agent 接入既有 SSE，而非新建端点
`runPackageAgent` 改用 `streamPackagesAgentSearch`（`stream: true`），事件经 `conversationRuns.ts` 同一管线消费。其后端 `agent.stream()` 已 yield trace 事件并以 `final` 事件携带结构化结果——`final` 中的 `answer` 仍用于落地结构化展示，而正文增量由新 `answer_delta` 提供。
- **为何如此**：后端 SSE 与前端 stream 客户端均已就绪，改动集中在对话框接线层；阻塞 REST 端点保留给非对话场景（向后兼容）。

### 决策 4：前端增量追加 + `final_text` 收尾校正
`conversationRuns.ts`：将 `answer_delta` 加入流式事件白名单；首个增量到达时清除"正在思考..."占位，随后 `target.content += text_chunk`；`run_complete` 时若 `final_text` 与累积内容不一致，以 `final_text` 为准覆盖（去抖/补全/脱敏一致）。
- **为何收尾校正**：partial 流可能丢块或与脱敏后的 `final_text` 有差异；以权威全文收尾保证持久化与展示一致。

## Risks / Trade-offs

- **[partial 与 final_text 不一致导致正文跳变]** → `run_complete` 用 `final_text` 覆盖收尾；增量阶段仅作即时呈现，最终态以全文为准。
- **[provider 不支持 partial 流式]** → `build_options` 在 profile 不支持时不传 `include_partial_messages`；无 `answer_delta` 时前端回退到原 `run_complete.final_text` 整段渲染（行为同今天，不退化）。
- **[`answer_delta` 频率过高造成 SSE/前端压力]** → `text_chunk` ≤ 4 KB 并按 SDK 自然分块发送，不额外拆分；前端追加为 O(1) 字符串拼接。
- **[重连重放遗漏 `answer_delta`]** → 重放路径与 `step_delta` / `thinking_delta` 同样按 `seq` 持久化与去重，新增类型纳入同一重放集合。
- **[SDK 版本下限]** → requirements 由 `claude-agent-sdk>=0.1` 提升到 `>=0.2`；CI/部署环境需确认已装 ≥0.2.82。

## Migration Plan

1. 提升 `requirements.txt` 中 `claude-agent-sdk` 下限并在目标环境验证 `include_partial_messages` 可用。
2. 后端先行：新增 `answer_delta` 常量 + `build_event` 支持 + `build_options` 开关 + 三处 `StreamEvent` 处理；新增事件对旧前端无害（静默忽略）。
3. 协议文档与 TS 类型镜像同步。
4. 前端：`conversationRuns.ts` 增量渲染 + `AIChat.vue` 重构包接线。
5. **回滚**：前端可独立回滚（移除 `answer_delta` 消费 + 重构包改回 `searchPackagesByAgent`），后端额外发 `answer_delta` 对回滚后的前端无副作用；`build_options` 开关可置 `False` 关闭整条链路。

## Open Questions

- `StreamEvent` 解析是否抽成 `trace.py` 共享 helper（推荐）还是三处各自实现——实现期决定，不影响协议。
- 重构包 Agent 后端 `agent.stream()` 当前是否已随 SDK partial 产出文本增量，需在实现时确认其 `_emit_for_message` 是否走与 device 相同的 `StreamEvent` 分支。
