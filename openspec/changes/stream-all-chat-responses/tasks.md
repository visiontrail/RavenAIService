## 1. 依赖与协议定义

- [x] 1.1 将 `requirements.txt` 中 `claude-agent-sdk>=0.1` 提升为 `>=0.2`，在目标环境确认已装 ≥0.2.82 且 `include_partial_messages` / `StreamEvent` 可导入
- [x] 1.2 在 `app/agents/log_analysis/trace.py` 新增事件常量 `ANSWER_DELTA = "answer_delta"`，并让 `build_event` / 事件类型校验接受 `answer_delta`（携带 `text_chunk`）
- [x] 1.3 在 `docs/agent_trace_protocol.md` 事件表中新增 `answer_delta` 行（字段 `text_chunk` ≤ 4 KB，语义=最终答复正文增量），并补充"按 seq 拼接等价于 final_text"的说明
- [x] 1.4 在 `frontend/src/types/agentTrace.ts` 中新增 `answer_delta` 事件的 TypeScript 类型镜像，保持与后端字段一致

## 2. 后端开启分块流式

- [x] 2.1 在 `app/agents/anthropic_client.py` 的 `build_options` 增加可选入参（默认开启）以设置 `ClaudeAgentOptions.include_partial_messages=True`；provider profile 不支持时静默不传并记日志
- [x] 2.2 在 `trace.py`（或共享 helper）新增 `StreamEvent` → `answer_delta` 的解析函数：从 `event["delta"]`（`type == "text_delta"`）抽取 `text`，累积并发出 `answer_delta`；非文本增量忽略
- [x] 2.3 DeviceAgent（`app/agents/device_agent/agent.py`）的 `_emit_for_message` / 消息循环增加 `StreamEvent` 分支，调用 2.2 的 helper 发出 `answer_delta`；确认完整 `TextBlock` 仍写入 `state.final_text`
- [x] 2.4 日志分析 Agent（`app/agents/log_analysis/agent.py`）同样接入 `StreamEvent` → `answer_delta`
- [x] 2.5 重构包 Agent（`app/agents/package_search/agent.py`）同样接入 `StreamEvent` → `answer_delta`，确认其 `stream()` SSE 在 `final` 事件前先发 `answer_delta`
- [x] 2.6 确认 `run_complete.final_text` 仍为权威全文（脱敏/裁剪后），未因分块流式而改变

## 3. 重连重放覆盖 answer_delta

- [x] 3.1 确认 chat 入口（`app/api/ai_chat.py` 的 run 快照 / Redis 缓冲）将 `answer_delta` 与 `step_delta` / `thinking_delta` 一同持久化并纳入按 seq 重放集合
  - 已确认：`chat_run_service.py` 的 DeviceAgent/GeneralAgent 驱动循环对所有事件类型统一 `append_trace(ev)` + `append_event(payload_out)`（保留 `seq`，仅将 `type` 改写为 `event`）；终态持久化到 `trace_events_json`。无任何按类型过滤，`answer_delta` 自动纳入。
- [x] 3.2 验证断线重连同一 session_id 时 `answer_delta` 按 seq 完整重放、不重复、不丢段
  - 已确认：`_subscribe` 重放整个 `job.events` buffer（按位置，含 `answer_delta`），SSE 帧保留 `seq`；不重复由前端按 seq 去重保证（见 4.2 / 6.2）。

## 4. 前端增量渲染答复

- [x] 4.1 在 `frontend/src/stores/conversationRuns.ts` 的流式事件白名单中加入 `answer_delta`
- [x] 4.2 实现 `answer_delta` 消费：按 seq 去重，首条到达时清除"正在思考..."占位，随后 `target.content += text_chunk`
- [x] 4.3 调整 `run_complete` 处理：以 `final_text` 做收尾校正覆盖；本轮无 `answer_delta` 时回退为整段渲染（保持现有行为）

## 5. 重构包 Agent 接入对话框流式

- [x] 5.1 在 `frontend/src/views/AIChat.vue` 将 `runPackageAgent` 从 `searchPackagesByAgent`（阻塞）改为 `streamPackagesAgentSearch`（`stream: true`）
- [x] 5.2 将重构包 Agent 的 SSE 事件接入与 Device/日志分析相同的 `conversationRuns` 渲染管线（trace + `answer_delta`）
- [x] 5.3 保留 `final` 事件结构化结果用于推荐包卡片展示与登录态会话持久化（`recommended_package_ids` → `getRavenPackageDetail` → `formatPackageAgentAnswer` 等价路径）
- [x] 5.4 确认阻塞式非流式 `agent-search` 端点与 `searchPackagesByAgent` 仍保留供非对话场景调用（`searchPackagesByAgent` 仍导出于 `frontend/src/api/raven.ts`，后端 `stream=false` 分支不变）

## 6. 验证

- [x] 6.1 后端单测：`StreamEvent` 解析产出预期 `answer_delta`，拼接等价于 `final_text`；provider 不支持时不发 `answer_delta`（`tests/agents/package_search/test_answer_delta.py`）
- [x] 6.2 前端单测（`conversationRuns.spec.ts`）：`answer_delta` 增量追加、去重、`final_text` 收尾校正、无 delta 时回退整段
- [x] 6.3 端到端手测：三个 Agent 在对话框中均逐字流式呈现答复，重构包 Agent 不再停留"正在思考..."占位
- [x] 6.4 兼容性验证：旧前端连接时忽略 `answer_delta` 仍能从 `run_complete` 拿到全文
