## Why

当前主对话框中三个 Agent 的输出行为不一致，用户感知不到统一的"流式"体验：

- **重构包 Agent** 走阻塞式 REST（`searchPackagesByAgent`，`stream: false`），全程只显示静态"正在思考..."占位符，直到结果一次性返回——尽管后端 `/packages/agent-search` 与前端 `streamPackagesAgentSearch` 早已支持 SSE。
- **DeviceAgent / 日志分析 Agent** 虽已走 SSE 流式（思考与工具轨迹实时透传），但**最终答复文本**仍在 `run_complete` 事件中一次性整段渲染（`target.content = finalText`），用户看到的是"长时间无字 → 突然整段出现"，并非逐字流式。

目标是让对话框中**所有 AI 返回内容**——包括最终答复正文——都以逐字流式呈现，三个 Agent 行为对齐。

## What Changes

- **新增 `answer_delta` trace 事件**：扩展 `AgentTraceEvent` 协议，新增 `answer_delta` 事件类型（携带 `text_chunk`），用于增量推送助手最终答复正文。`run_complete.final_text` 仍保留为权威全文（用于持久化/重放校正）。
- **后端开启 SDK 分块流式**：在 `build_options` 中启用 `include_partial_messages=True`，让 `claude_agent_sdk.query()` 产出 `StreamEvent`（承载原生 Anthropic `text_delta`）。三个 Agent 的 `_emit_for_message` 处理 `StreamEvent` → 抽取文本增量 → 发出 `answer_delta`。
- **重构包 Agent 拉齐流式路径**：`AIChat.vue` 的 `runPackageAgent` 从阻塞 `searchPackagesByAgent` 迁移到既有的 `streamPackagesAgentSearch`，其 trace 与 `answer_delta` 经统一渲染管线增量呈现，与另外两个 Agent 一致。
- **前端增量渲染答复**：`conversationRuns.ts` 识别 `answer_delta`，将 `text_chunk` 增量追加到答复消息；`run_complete` 时以 `final_text` 做最终校正（兜底/去抖）。
- 断线重连重放路径同步支持 `answer_delta`（按 `seq` 去重，与现有 `step_delta` / `thinking_delta` 一致）。

## Capabilities

### New Capabilities
<!-- 无新增能力；本变更扩展现有 trace 流式协议与 UI。 -->

### Modified Capabilities
- `agent-trace-stream`: 在 `AgentTraceEvent` 协议中新增 `answer_delta` 事件类型，并要求 Agent 开启 SDK 分块流式以逐字发出最终答复；重连重放须覆盖 `answer_delta`。
- `agent-trace-ui`: 前端须按 `answer_delta` 增量渲染最终答复正文（而非在 `run_complete` 整段渲染），并在收到 `final_text` 时做最终校正。
- `package-search-agent`: 主对话框对重构包 Agent 的调用须走 SSE 流式（`stream: true`）路径，使其 trace 与答复与其他 Agent 一致地实时呈现。

## Impact

- **后端**：`app/agents/anthropic_client.py`（`build_options` 开启 `include_partial_messages`）、`app/agents/log_analysis/trace.py`（新增事件常量 + `build_event` 支持）、`app/agents/device_agent/agent.py`、`app/agents/log_analysis/agent.py`、`app/agents/package_search/agent.py`（三处 `_emit_for_message` / 消息处理处理 `StreamEvent`）。
- **协议文档**：`docs/agent_trace_protocol.md`（新增 `answer_delta` 行）、`frontend/src/types/agentTrace.ts`（TypeScript 镜像）。
- **前端**：`frontend/src/stores/conversationRuns.ts`（流式事件白名单 + 增量答复渲染）、`frontend/src/views/AIChat.vue`（`runPackageAgent` 改用 `streamPackagesAgentSearch`）。
- **依赖**：依赖 `claude-agent-sdk>=0.2`（`include_partial_messages` / `StreamEvent` 已在 0.2.82 提供，requirements 现声明 `>=0.1`，需提升下限）。
- **兼容性**：`answer_delta` 为新增事件类型，旧客户端不识别时静默忽略并仍能从 `run_complete` 拿到全文；非破坏性。
