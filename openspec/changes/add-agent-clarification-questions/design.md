## Context

DeviceAgent 已基于 Claude Agent SDK 重建，并落地了完整的 **HITL 工具审批**管线：

- `PermissionBroker`（`app/agents/device_agent/permissions.py`）：per-run 协调器，内部维护 `Dict[request_id, asyncio.Future]`，提供 `open/resolve/cancel/close`。
- `can_use_tool` 工厂阻塞 agent loop，发出 `tool_permission_request` trace，等待 Future。
- `POST /chat/permissions/{request_id}/resolve`（`app/api/ai_chat.py`）按 `run_id → session_id → 全表扫描` 查找 broker 并做 `owner_scope` 归属校验。
- `ChatRunService` 持有 broker 注册表（`register_broker`/`get_broker_by_run_id`），并在 snapshot 中回放 `pending_permissions`；`cancel(run_id, owner_scope)` 通过 `job.task.cancel()` 终止后台 run。
- 前端 `stores/conversationRuns.ts` 按 `session_id` 存 `pendingPermissions`，`AgentTraceStream.vue` 渲染、`submitPermission` 回写。

澄清提问与工具审批在结构上**同构**：都是"agent loop 阻塞 → 发事件 → 等用户 HTTP 回写 → Future resolve → loop 继续"。区别仅在于触发方（模型主动调工具 vs SDK 拦截工具）与回写载荷（结构化答案 vs allow/deny）。因此本设计的核心是**复用而非新建**这套管线。

约束：
- 触发权归模型 —— 用户明确要求"Agent 自行决定是否询问"，不要做强制前置分类。
- 必须支持多问题、每问 2–4 预设选项 + 自由输入。
- 必须支持断线/切会话/刷新后恢复未答问题（与 pending_permissions 一致）。
- 超时行为可配置，默认取消本轮。

## Goals / Non-Goals

**Goals:**
- 以 in-process MCP 工具 `AskUserQuestion` 暴露澄清能力，由模型在推理中自行调用。
- 单次调用支持 1..N 个问题，每问 `header` + `question` + 2–4 `options` + 自由输入；答案结构化回喂模型。
- 复用 `PermissionBroker`、broker 注册表、resolve 端点模式、snapshot 回放、前端 per-session 存储等既有管线。
- 提供可配置超时策略（默认 `cancel`，可选 `continue`），并落到用户设置项。
- 工具/事件/端点/前端组件按可复用方式实现，使其它 SDK agent 后续可低成本接入。

**Non-Goals:**
- 不在本期为 log_analysis / project_expert / package_search 接入（只保证设计可推广）。
- 不做强制前置"是否需要澄清"分类器（preflight gate）。
- 不实现澄清答案的长期存储/分析（答案随 run trace 持久化即可，不建独立表）。
- 不实现富媒体问题（图片/文件选择）；本期仅文本选项 + 文本自由输入。
- 不改动工具审批（permission）现有行为。

## Decisions

### Decision 1：用 in-process MCP 工具 `AskUserQuestion` 触发（而非前置分类 / 纯提示词）
模型在 system prompt 指引下，**自行决定**指令是否不清晰；不清晰时调用 `AskUserQuestion` 工具。工具是 SDK 一等公民，调用即天然阻塞 loop，结果天然回喂模型，与 Claude Code 行为一致。
- **备选 A（preflight 分类）**：每轮先跑一次"是否需澄清"判定 —— 多一次 LLM 调用与提示词维护，且与"agent 自行决定"语义相悖。否决。
- **备选 B（仅靠提示词让模型在正文里提问）**：无法阻塞 loop、无法结构化选项、前端无法渲染交互。否决。

`AskUserQuestion` 通过 `create_sdk_mcp_server` 注册（与 `build_device_mcp_server` 同机制），SDK 全名 `mcp__ask__AskUserQuestion`，加入 `allowed_tools`。其 `inputSchema` 见 spec：`questions: [{header, question, options:[{label, description}], multiSelect?}]`。

### Decision 2：复用 `PermissionBroker`，不新建 broker
broker 本质是 `request_id → Future` 的通用协调器，与"决策语义"无关。澄清复用同一 broker 实例（同一 run 内 permission 与 clarification 共享），`open(request_id, tool_name="AskUserQuestion", risk="clarify")`；resolve 写入的 payload 改为 `{"answers": [...]}`。`risk="clarify"` 仅作标记，不参与风险分级。
- **备选（独立 ClarificationBroker）**：重复 90% 代码、需第二套注册表与端点查找。否决；仅当未来语义分叉时再拆分。

为类型清晰，`PermissionBroker.open` 的 `risk` 放宽接受 `"clarify"`（或新增轻量 `open_clarification` 包装，行为同 `open`）。

### Decision 3：新增专用事件 `clarification_request` / `clarification_resolved`
不复用 `tool_permission_request`，因为载荷（questions 数组）与前端渲染（多问题表单 vs allow/deny）差异大，复用会让前端分支判断混乱。两事件遵循 `AgentTraceEvent` 基座（`type/task_id/seq/timestamp`），经现有 `agent_trace` SSE 通道下发，**对旧客户端可忽略**（与 device 权限事件不在 log-analysis 枚举内是同一处理范式）。
- `clarification_request`：`request_id`、`questions`（含选项）、`run_id`、`session_id`。
- `clarification_resolved`：`request_id`、`outcome`（`answered`/`timeout`/`cancelled`）、（可选）回显 `answers` 摘要、`reason`。

### Decision 4：resolve 端点镜像 permission 端点
新增 `POST /api/v1/ai-chat/chat/clarifications/{request_id}/resolve`，请求体 `{run_id?, session_id?, answers: [{question_index, selected_labels[], custom_text?}]}`。查找/归属逻辑与 permission resolve 完全一致（`run_id → session_id → owner_scope 过滤后扫描`）。校验：每个被标记必答的问题必须有 `selected_labels` 或非空 `custom_text`；否则 400。成功后把 `{"answers": [...]}` 写回 broker Future。

### Decision 5：工具返回值 —— 结构化文本回喂模型
`AskUserQuestion` 工具拿到答案后，按 SDK 约定返回 `{"content":[{"type":"text","text": <answers_json>}]}`。`text` 为人类可读 + 结构化的答案块（每问：问题、用户所选 label（们）、自定义文本），便于模型直接消费并继续。

### Decision 6：超时策略可配置，默认取消本轮
新增设置 `device_agent_clarification_on_timeout ∈ {cancel, continue}`，默认 `cancel`；等待时长复用 `device_agent_permission_timeout_seconds` 量级（可单列 `device_agent_clarification_timeout_seconds`，缺省回退到 permission 超时值）。该开关同时下发为用户可改的设置项（运行期生效，沿用 runtime settings）。
- `continue`：超时后 `broker.cancel` + 工具返回 `{status:"timeout", note:"用户未在限定时间内回答；请基于已知信息给出最合理的处理或最佳猜测"}` → 模型继续。发 `clarification_resolved{outcome:"timeout"}`。
- `cancel`（默认）：超时后发 `clarification_resolved{outcome:"cancelled", reason:"timeout"}`，并通过注入的 `cancel_run` 回调（由 `ChatRunService` 提供，内部 `self.cancel(run_id, owner_scope)` → `job.task.cancel()`）终止本轮 run；DeviceAgent 既有 `CancelledError` 兜底将本轮 finalize 为 `cancelled`。
  - **为何走 run 级 cancel 而非工具内抛异常**：在 SDK 工具 proxy 内 `raise` 会被当作工具失败回喂模型、无法可靠终止 loop；run 级 cancel 复用既有、确定性的取消路径。
  - 兼容：旧 `ai_chat_service` 非 run 路径无 `cancel_run` 注入时，降级为 `continue` 语义（仅 legacy 端点，可接受）。

### Decision 7：snapshot 回放与 per-session 存储，镜像 pending_permissions
`ChatRunJob` 增加 `pending_clarifications: Dict[request_id, event]`；`chat_run_service` 在回放循环里对 `clarification_request` 入栈、`clarification_resolved` 出栈；snapshot 增加 `pending_clarifications` 列表。前端 `conversationRuns.ts` 增加 `pendingClarifications`（按 session 隔离）、`submitClarification`，`mergeSnapshot` 恢复未答问题。断线/切会话/刷新后问题卡片可恢复。

### Decision 8：前端独立 `ClarificationCard.vue`
在 `AgentTraceStream.vue` 内，当存在该 run 的未决澄清时渲染 `ClarificationCard`：逐问渲染 `header`/`question`、选项为可点按钮（`multiSelect` 时多选、否则单选）、末尾恒有"自定义输入"文本框；多问题统一在一个卡片内、底部单个"提交"按钮，提交前做必答校验。提交调用 `api/chat.ts#resolveChatClarification`，成功后本地移除。文案/占位符走 i18n，问题与选项文本来自模型（已按 `locale` 生成）。

## Risks / Trade-offs

- **[模型过度/过少提问]** → system prompt 明确"仅在缺关键参数/存在多解/目标不明时提问，能合理推断就不要打断"；并给正/反例。可观测：trace 里 `clarification_request` 频次。
- **[permission 与 clarification 共享 broker 致 request_id 混淆]** → request_id 全 UUID 唯一；两类事件/端点分离；resolve 时按 request_id 精确命中，互不影响。
- **[cancel 模式下并发 resolve 与 timeout 竞态]** → `broker.resolve/cancel` 已对 `future.done()` 做幂等保护，先到者生效；timeout 与用户回答二选一，事件以先发者为准。
- **[多问题表单 UX 复杂度]** → 单卡片聚合 + 必答校验 + 一次提交，避免多次往返；自由输入恒在，保证"总能作答"。
- **[超时 cancel 误伤长思考用户]** → 默认值虽为 cancel，但提供用户级 `continue` 开关；超时时长可配置并取 permission 量级（分钟级）。
- **[可推广性 vs 当期范围]** → 工具注册、事件常量、broker、端点、前端组件均与 device 解耦命名（`ask`/`clarification`），但本期仅 wire 到 DeviceAgent，避免一次性改动面过大。

## Migration Plan

1. 后端：新增工具/事件常量/端点/snapshot 字段/设置项；DeviceAgent 组装时把 `AskUserQuestion` server 加入 `mcp_servers` 与 `allowed_tools`，并注入 `cancel_run` 回调（`ChatRunService` 路径）。
2. 前端：新增类型、store 状态与 action、`ClarificationCard.vue`、API、i18n、设置开关。
3. 灰度：默认超时 `cancel`；system prompt 的提问指引可先保守（少提问）再调。
4. 回滚：从 `allowed_tools`/`mcp_servers` 摘除 `AskUserQuestion` 即可彻底禁用（事件/端点保留不影响旧行为）；属纯增量、无 schema 迁移。

## Open Questions

- 设置项的粒度：仅"超时行为(cancel/continue)"开关，是否还需要"全局禁用澄清"用户开关？（倾向先只做超时行为，禁用通过移除工具实现。）
- 是否限制单轮最多澄清次数（防止模型反复提问）？（倾向加一个软上限，如每 run ≤ 2 次 `AskUserQuestion`，超出后工具返回提示让模型自行决断。）
- `device_agent_clarification_timeout_seconds` 是否单列，还是直接复用 permission 超时值？（倾向单列但缺省回退。）
