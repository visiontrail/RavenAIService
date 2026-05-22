## Context

现状里有两套相互不一致的运行模型：

- **DeviceAgent chat**：`AIChatService.chat_stream()` 在当前 HTTP SSE 请求里直接 `async for ev in DeviceAgent().run_stream(ctx)`。请求断开即取消这次 run；事件没有统一缓冲，完成前也不会把用户消息/助手占位写入可恢复状态。
- **主对话 LogAnalysisAgent**：`LogAnalysisChatService` 已经有 `AgentJob`、后台 task、事件 replay、cancel 和结果轮询，但前端仍由 `AIChat.vue` 的单例 `isSending/sessionId/chatHistory` 驱动，用户切会话后状态会串线。

前端侧，`WorkbenchLayout.vue` 的历史列表只知道 `ChatSessionSummary`，没有 active run 字段；`AIChat.vue` 只有一个当前 panel 状态。用户在 A 会话发送后切到 B 会话，A 的 SSE reader 仍会调用 `applyStreamEvent(answerId)` 写入共享 `chatHistory`，而 B 会话也因为 `isSending=true` 不能发送。

本设计把“运行中的 Agent loop”抽象为 **Chat Agent Run**。会话是用户看到的对话容器；run 是某一轮用户输入触发的后台任务。多个会话可以同时各自有一个 active run；同一用户的同一会话同一时间只允许一个 active run。所有 run lookup 都带 owner scope，避免不同用户碰巧使用相同 `session_id` 时发生串线。

## Goals / Non-Goals

**Goals:**

- 用户发送后可以离开当前对话窗口；后台 Agent loop 不因 SSE 断开而取消。
- 侧边栏会话历史能显示每个 running session 的 spinner / running 状态。
- 点击 running session 可以恢复完整上下文：已持久化历史 + 本轮用户消息 + assistant 占位 + 已产生 trace/HITL 状态 + 后续实时事件。
- 多个不同会话、不同用户可以并发运行 Agent loop，事件、权限请求、工作目录和最终持久化互不串线。
- DeviceAgent 每个 run 使用独立工作目录；LogAnalysisAgent 不同 session 使用不同持久分析工作区。
- 兼容现有 `/chat/stream` SSE 帧格式，旧客户端忽略新增字段仍可工作。

**Non-Goals:**

- 不支持同一个 session 内并行跑多轮 user turn。active run 未结束时，输入框禁用；后端对同 session 新消息返回 HTTP 409。
- 不把 in-memory Agent loop 做成跨进程可恢复执行。进程重启后，DB 中未终态 run 标记为 `failed/stale`，前端展示可重试。
- 不把 PackageAgent 非流式检索强行改造成后台 run；若后续 package search 需要并发/恢复，可复用本设计。
- 不改变 DeviceLinkManager 到上位机的工具调用协议。

## Decisions

### Decision 1: 后端 run manager 拥有 Agent 生命周期，SSE 只是订阅者

新增 `app/services/chat_run_service.py`：

```python
@dataclass
class ChatRunJob:
    run_id: str
    session_id: str
    user_id: Optional[str]
    owner_scope: str
    agent_kind: Literal["device", "log_analysis"]
    status: Literal["queued", "running", "succeeded", "failed", "cancelled", "stale"]
    started_at: float
    updated_at: float
    events: list[dict[str, Any]]
    trace_events: list[dict[str, Any]]
    task: Optional[asyncio.Task]
    answer: str = ""
    model: str = ""
    error: Optional[str] = None
```

`ChatRunService.start_device_run(...)` 创建 `ChatRunJob` 并 `asyncio.create_task(_run_device_job(job, ctx))`。`POST /chat/stream` 的响应只调用 `subscribe(job)`，先 replay `job.events`，再轮询新事件直到终态。客户端断开时只结束当前 subscriber，不取消 `job.task`。

LogAnalysisAgent 可以分两步接入：

1. 保留 `LogAnalysisChatService.AgentJob` 的内部执行；在创建/完成/cancel 时同步写 `chat_agent_runs` 状态，并让前端使用统一 session state。
2. 后续将 `LogAnalysisChatService.AgentJob` 收敛到 `ChatRunService` 的同一 `ChatRunJob` 类型。

实现时优先完成 DeviceAgent 的生命周期解耦，再把 LogAnalysis 的前端全局状态迁移到 per-session store。

`owner_scope` 规则：

- 登录用户：`user:<user_id>`。
- 匿名用户：`anon:<server_generated_client_scope>`，该 scope 由首次创建 run 时服务端生成并随 `session`/`run_start` 返回；匿名 run 仅承诺在当前进程 retention 内恢复，不跨刷新持久恢复。
- 任何内存 registry 的 key 都不得只用裸 `session_id`；必须用 `(owner_scope, session_id)` 或 `run_id`。

### Decision 2: `chat_agent_runs` 表记录可恢复元数据

新增 SQLAlchemy model `ChatAgentRun` 与 Alembic migration。为兼容当前项目的数据库风格，复杂结构用 `Text` 存 JSON。

建议字段：

- `id: String(36)` run_id，主键。
- `session_id: String(36)`，索引。
- `user_id: String(36) | NULL`，索引；匿名用户为空。
- `owner_scope: String(128)`，索引；用于内存 registry 与匿名 run 隔离。
- `agent_kind: String(32)`：`device` / `log_analysis`。
- `status: String(24)`：`queued` / `running` / `succeeded` / `failed` / `cancelled` / `stale`。
- `user_message: Text`，本轮输入快照。
- `request_json: Text`，目标设备、目标 agent、文件名、project_repo_id、前端传入 options 等。
- `workspace_path: Text | NULL`，运行时工作目录。
- `answer: Text | NULL`，终态助手答案。
- `model: String(128) | NULL`。
- `error: Text | NULL`。
- `trace_events_json: Text | NULL`，完成后写入完整 `AgentTraceEvent[]`；运行中以内存为准。
- `started_at / finished_at / created_at / updated_at`。

索引建议：

- `(owner_scope, session_id, status)`：查当前用户当前会话 active run。
- `(user_id, status, updated_at)`：会话列表叠加 running overlay。
- `run_id` 主键全局唯一，但任何返回 run 内容的 API 仍必须校验 owner。

服务启动时扫描 `status IN ('queued','running')` 的 run，将其标记为 `stale` 并写入 `error="server restarted before run completed"`。这样侧边栏不会无限转圈。

### Decision 3: 用户消息在 run 启动时立即持久化，助手消息在终态持久化

现有 `chat_history_service.save_exchange()` 一次写 user+ai 两条消息，不适合“发送后离开并恢复”的场景。新增两个低层 helper：

- `append_message(db, user_id, session_id, role, content) -> ChatMessage`
- `touch_session_activity(db, user_id, session_id, *, delta_count, title_hint=None)`

运行开始时：

1. `ensure_session(...)`
2. 写入本轮 `role="user"` 消息。
3. 创建 `chat_agent_runs` 记录，`status="running"`。
4. 更新 `ChatSession.last_message_at` 和 `message_count += 1`。

运行中：

- DB 历史只包含已落库消息。
- active run snapshot 提供虚拟 assistant 消息：
  - `id = "run:<run_id>:assistant"`
  - `role = "ai"`
  - `content = answer_so_far or "正在思考..."`
  - `traceEvents = job.trace_events`
  - `traceRunning = true`

运行成功/失败/取消时：

1. 写入 `role="ai"` 终态消息（成功为 final answer；失败/取消为可读错误或取消说明）。
2. `chat_agent_runs.status` 更新为终态，写 `answer/model/error/trace_events_json/finished_at`。
3. `ChatSession.message_count += 1`，`last_message_at = now`。
4. 若这是该 session 第一轮，照旧触发标题生成。

这样用户点击 running session 时无需等待终态，也能看到本轮用户消息；终态后刷新页面则只从 DB 历史恢复，无需 run overlay。

### Decision 4: API 保持兼容，同时增加 run 原语

保留现有 `POST /api/v1/ai-chat/chat/stream`，但语义改为 create-or-subscribe：

- 带 `message` 且 session 无 active run：创建新 run 并订阅。
- 带 `message` 但 session 已有 active run：返回 HTTP 409，body 包含 `active_run_id`。
- 不带新消息或 `message=""` 且 session 有 active run：订阅并重放现有 run。

新增端点：

- `GET /api/v1/ai-chat/chat/sessions/{session_id}/active-run`
  - 200：`{run_id, status, agent_kind, events, trace_events, answer_so_far, pending_permissions}`
  - 404：无 active run。
- `GET /api/v1/ai-chat/chat/runs/{run_id}`
  - 返回完整快照；终态 run 可从 DB `trace_events_json` 回放。
- `GET /api/v1/ai-chat/chat/runs/{run_id}/stream`
  - SSE，先 replay，再接续实时；终态后关闭。
- `POST /api/v1/ai-chat/chat/runs/{run_id}/cancel`
  - 对 DeviceAgent 通过 `asyncio.Task.cancel()` + `cancelled` trace；对 LogAnalysis 调用已有 cancel_event。

所有 read/subscribe/cancel 都校验 `run.owner_scope == owner_scope(current_user, client_scope)`。登录用户必须满足 `run.user_id == current_user.id`；匿名 run 必须匹配服务端发放的匿名 owner scope。未匹配时返回 404（避免泄露 run 是否存在），管理后台另行审计接口不在本变更范围内。

### Decision 5: 事件缓冲按 `run_id + seq` 隔离

DeviceAgent 当前 trace 的 `task_id` 通常等于 `session_id`。并发恢复下应改为：

- `task_id = run_id`，保证不同 run 的 seq 空间天然隔离。
- 每条 SSE payload 增加 `run_id` 与 `session_id`。
- 前端按 `run_id + seq` 去重，不能只按 `seq`。

`ChatRunService.subscribe(job)` 逻辑参考 `LogAnalysisChatService._subscribe`：

- `sent = 0` replay `job.events`。
- 每 200ms 轮询新事件。
- 15s 无新事件时 emit `system_notice{kind:"heartbeat", run_id, session_id}`。
- job 终态后 emit `done` 或 terminal error 并返回。
- finished job 保留内存 30 分钟；之后仍可从 `chat_agent_runs.trace_events_json` 提供终态回放。

### Decision 6: PermissionBroker 改为 run-scoped

现有 `AIChatService.permission_broker_registry: Dict[str, PermissionBroker]` 按 `session_id` 注册，会在同一 session 仅一条 run 时工作，但不利于恢复/定位。

改为：

```python
permission_broker_by_run_id: dict[str, PermissionBroker]
active_run_by_owner_session: dict[tuple[str, str], str]
```

`tool_permission_request` 事件必须包含 `run_id`、`session_id`、`request_id`。前端提交时优先传 `run_id`：

```json
{"decision":"allow","updated_args":{...},"run_id":"...","session_id":"..."}
```

解析顺序：

1. `run_id` 精确定位 broker。
2. `(owner_scope, session_id)` fallback 查 active run。
3. 最后为了兼容旧前端可扫描当前 registry，但扫描结果也必须过滤 `broker.owner_scope == current_owner_scope`；不得跨用户扫描命中。

权限弹窗属于 run，而不是当前页面。前端切到其它会话后，原会话的 pending permission 保存在 store；回到该会话时弹窗恢复。如果用户一直不回来，后端按 timeout deny 并继续/结束 loop。

### Decision 7: DeviceAgent 工作区包含 run_id

修改 `app/agents/device_agent/workspace.py`：

```python
def prepare_session(
    session_id: Optional[str],
    run_id: Optional[str] = None,
    owner_scope: Optional[str] = None,
) -> Path:
    safe_owner = sanitize(owner_scope or "anon")
    safe_session = sanitize(session_id)
    safe_run = sanitize(run_id or uuid.uuid4().hex)
    workspace = base / "device_agent" / safe_owner / safe_session / safe_run
```

`DeviceAgentContext` 增加 `run_id`、`owner_scope` 和可选 `workspace_path`。`DeviceAgent.run_stream(ctx)` 使用 `ctx.run_id` 作为 trace `task_id`，并把 workspace path 记录到 `chat_agent_runs.workspace_path`。

并发保证：

- user 1 / A session run: `.../device_agent/user_<user1>/<sessionA>/<runA>/`
- user 2 / A session run（即使 session_id 相同）: `.../device_agent/user_<user2>/<sessionA>/<runB>/`
- 即便两个 session 同时命中同一个设备，也不会共享 `.claude/skills`、临时文件或 trace state。

默认终态清理 workspace；若新增 `device_agent_retain_workspace_seconds > 0`，可在调试环境短期保留并由 lazy cleanup 删除。

### Decision 8: 前端用 session-scoped store 替代 AIChat.vue 单例状态

新增（命名可调整）`frontend/src/stores/conversationRuns.ts`：

```ts
type ConversationState = {
  sessionId: string
  messages: ChatEntry[]
  activeRunId?: string
  runStatus?: 'running' | 'succeeded' | 'failed' | 'cancelled'
  isSending: boolean
  subscription?: AbortController
  pendingPermissions: PendingPermission[]
}
```

核心行为：

- `selectSession(id)`：
  1. abort 当前页面对旧 session 的 SSE subscription（只断开订阅，不 cancel run）。
  2. load DB messages。
  3. 调 `active-run`；若存在，merge virtual assistant message 并订阅 `run_id/stream`。
- `startRun(sessionId, payload)`：
  1. 本地立即 append user message + assistant placeholder。
  2. 调 `/chat/stream` 或 `/chat/runs` 创建后台 run。
  3. 把返回的 `session/run` 事件写入该 session 的 state。
- `applyRunEvent(sessionId, runId, event)`：
  - 只更新匹配 session/run 的 state；如果当前 UI 正在看别的 session，不触碰它。
  - terminal 后标记 `isSending=false` 并刷新 `sessionStore.load()`。

`AIChat.vue` 只计算：

```ts
const currentConversation = computed(() => conversationStore.bySession[currentSessionId])
const chatHistory = computed(() => currentConversation.messages)
const isSending = computed(() => currentConversation.isSending)
```

这样 A 会话 running 时，用户切到 B 会话，B 的 `isSending` 为 false，可以继续发送并创建 B run。

### Decision 9: 侧边栏从 session summary 和本地 overlay 显示 running spinner

后端 `ChatSessionSummary` 增加 optional 字段：

```python
active_run_id: Optional[str] = None
run_status: Optional[str] = None
run_agent_kind: Optional[str] = None
run_started_at: Optional[datetime] = None
run_updated_at: Optional[datetime] = None
```

`chatSession` store 还维护本地 overlay：

```ts
const runningBySessionId = computed(() => new Set([
  ...sessions.value.filter(s => s.run_status === 'running').map(s => s.id),
  ...conversationStore.localRunningSessionIds,
]))
```

`WorkbenchLayout.vue` 在 `.rw-chat-row` 内、标题前或右侧渲染小 spinner。删除菜单按钮 hover 时不遮挡 spinner；spinner 有 `title="正在运行"` 但不引入多余说明文案。

会话列表刷新策略：

- run start/terminal 时主动 `sessionStore.load()`。
- 有任意 running session 时每 5s 轻量刷新一次 list，避免当前浏览器没订阅的 run 状态滞后。
- 刷新失败不影响已存在的本地 overlay。

### Decision 10: 日志分析前端也迁移到 per-session running state

`runLogAnalysisAgent` 目前有全局 `activeLogAnalysisSessionId` / `cancelInFlight` / `isSending`。改造后：

- `activeLogAnalysisSessionId` 被 `conversationState.activeRunId` / `agentKind='log_analysis'` 替代。
- 取消按钮只在当前 session 有 active log-analysis run 时显示。
- 离开该 session 时取消按钮消失，但后台分析继续；侧边栏 spinner 保持。
- 回到该 session 时通过 active-run snapshot 恢复 trace 与取消按钮。

后端短期可继续使用 `LogAnalysisChatService._jobs` 作为实际执行源，但需要暴露 run snapshot 并把状态投影到 `chat_agent_runs` / `ChatSessionSummary`。这能避免一次变更同时重写日志分析文件上传和工作区逻辑。

## Failure Modes

- **客户端关闭标签页**：订阅断开，后台 run 继续。用户重新打开后，登录态用户从 DB + run snapshot 恢复；匿名用户只能在同进程 retention 内恢复。
- **服务进程重启**：启动时把 running run 标记 stale，侧边栏停止 spinner；用户点击会话看到本轮 user message 和 stale 错误，可重新发送。
- **两个请求同时给同一用户的同一 session 发消息**：后端以 `active_run_by_owner_session` + DB 查询双重检查返回 409；前端禁用当前 session 输入。不同用户即便提交相同 `session_id`，因 owner_scope 不同，也必须创建各自 run。
- **权限请求无人处理**：timeout 后后端 emit deny resolved，loop 继续或结束；侧边栏仍保持 running 直到终态。
- **事件缓冲过大**：内存 events 上限 2000；超限保留最近事件并在 terminal done 中标记 `trace_truncated=true`。DeviceAgent 正常 trace 远低于上限。
