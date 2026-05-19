## Context

`LogAnalysisAgent` 已经迁移到 Claude Agent SDK 的 `query()` async iterator，loop 内部每一条消息（assistant_text / tool_use / tool_result / thinking / system / result）在 `_handle_stream_message` 里都被解构了，但目前只做两件事：

1. `_log_workflow(ctx.task_id, "event", ...)` — 写本地结构化日志（仅运维可见）；
2. `tool_trace.append(...)` — 累积成最终 result 的一个数组字段。

结果是：用户在两个入口（`AIChat.vue` 的 SSE 通道、`LogDetail.vue` 的 Celery 任务轮询）都**等到任务跑完才能看到结果**，而 SDK 内部的流式属性被完全浪费掉。

两个入口的传输基础不同：

- **Chat 入口** (`/ai-chat/log-analysis/stream`)：`LogAnalysisChatService` 已经把 agent 跑在一个长生 asyncio task 里，并通过 in-process `AgentJob.events` 给 SSE `_subscribe` 做事件 buffer + 客户端断线重连。trace 事件直接 append 到 `job.events` 即可。
- **日志详情入口**：分析在 **Celery worker 进程**里跑，FastAPI 进程没法直接拿到 worker 的内存事件。需要一个跨进程缓冲（Redis）+ 一个新的 SSE 端点从 Redis 读取。

两条路径**事件 schema 必须完全一致**，否则前端组件要写两套渲染。这是本次设计最重要的边界约束。

## Goals / Non-Goals

**Goals:**
- Agent loop 内部的每条 SDK 消息（assistant_text、thinking、tool_use、tool_result、system_notice、lifecycle）都能以 `<= 500ms` 的端到端延迟流到浏览器。
- Chat 与日志详情两个入口共享同一个事件 schema 和同一个前端渲染组件。
- 断线重连后能完整重放当前任务的所有历史事件（不丢步骤）。
- 任务结束后页面刷新仍能看到完整 trace（持久化到 `ai_analysis_result.trace_events`）。
- 不破坏现有客户端：旧前端只识别 `log_analysis_status` / `done` 时仍能正常工作。

**Non-Goals:**
- 不优化 SDK loop 内部的延迟或并发；只做"透传"。
- 不引入新的实时基础设施（WebSocket、gRPC streaming、Redis Pub/Sub 等），坚持 SSE + Redis list 的简单组合。
- 不实现非日志分析 chat 链路（`chat_agent.py`）的 trace 化。
- 不引入新的数据库表；trace 持久化只扩展现有 `ai_analysis_result` JSON。
- 不实现 trace 事件级别的权限控制；沿用现有 chat / log 的可见性。
- 不为 trace 实现独立的搜索 / 全文索引。

## Decisions

### Decision 1: 统一事件协议 `AgentTraceEvent`

定义一个 discriminated union，所有事件类型共享 `type`、`task_id`、`seq`、`timestamp`：

```python
# app/agents/log_analysis/trace.py
class AgentTraceEvent(TypedDict, total=False):
    type: Literal[
        "run_start", "run_complete", "cancelled",
        "step_start", "step_delta", "step_end",
        "thinking_start", "thinking_delta", "thinking_end",
        "system_notice", "error",
    ]
    task_id: str           # ctx.task_id
    seq: int               # 单调递增，前端按 seq 排序去重
    timestamp: float       # epoch seconds, 6 位小数

    # step_* 携带
    step_id: str           # uuid4，同一步骤的 start/delta/end 共用
    tool_name: str         # e.g. "Bash", "Read", "mcp__project_repo__lookup_project_repo"
    tool_input: dict       # 已脱敏（token URL 处理）
    output_chunk: str      # step_delta 时的增量文本
    output_excerpt: str    # step_end 时的最终截断文本（<= 4 KB）
    status: Literal["ok", "error"]
    duration_seconds: float

    # thinking_* 携带
    text_chunk: str        # 增量
    text: str              # thinking_end 时的完整文本

    # run_complete 携带
    trace_summary: dict    # {thought_duration_seconds, tool_call_count, ...}
    final_text: str        # 最终结论文本（fenced JSON 内的 raw）
```

**为什么不用 SDK 原生 message 直接外抛**：原生 message 是 Anthropic SDK 的内部类（`AssistantMessage` / `ResultMessage`），强耦合 SDK 版本；自定义 schema 能让 SDK 升级时只改一个适配层。

**为什么用 `step_id` 而不是按 `seq` 关联 start/delta/end**：前端 Vue 组件按 `step_id` 直接做 key，做"原位更新"，比按 seq 排表更简单；同时也允许后端在某些场景跳过 delta 直接发 start+end。

**Alternatives considered**：
- Server-Sent Events 直接转发 SDK 的 raw message JSON — 否决：前端要重新解析 Anthropic SDK 内部格式，SDK 升级即破坏。
- WebSocket 双向通道 — 否决：现有所有流式接口都用 SSE，没必要引入双向通道（cancel 走单独 HTTP 即可）。

### Decision 2: Agent 注入 `trace_emitter` 而非全局发布订阅

```python
class LogAnalysisAgent:
    async def run(
        self,
        ctx: WorkspaceContext,
        cancel_event: Optional[threading.Event] = None,
        trace_emitter: Optional[Callable[[AgentTraceEvent], Awaitable[None]]] = None,
    ) -> Dict[str, Any]: ...
```

- 没传 emitter → 行为与现状一致（Celery 老代码不报错）。
- 传了 emitter → `_handle_stream_message` 在写日志的同时 `await trace_emitter(event)`。
- emitter 内部异常**不传播**，只 logger.warning，避免单条事件失败拖垮整个 agent。

**Alternatives considered**：
- 全局 `asyncio.Queue` / pub-sub — 否决：跨 task 上下文混乱，且 Celery worker 跑同步桥（`asyncio.run`），全局 queue 还要解决跨事件循环转发。
- Hook 注入到 `claude_agent_sdk.query()` 的 options — 否决：SDK 没有暴露 message-level hook API，必须在我们自己的处理层做。

### Decision 3: Chat 路径直接走 in-process buffer

`LogAnalysisChatService._run_job_async` 构造的 emitter 直接 `job.events.append(event)`：

```python
async def emit(event):
    job.events.append({"event": "agent_trace", **event})

await asyncio.to_thread(
    LogAnalysisAgent().run_sync, ctx, job.cancel_event, emit  # via partial
)
```

但是 `run_sync` 走 `asyncio.run`，它和外层 chat service 的 event loop 不是一个 loop —— `await` 一个外部 loop 的协程会 deadlock。**取舍**：

- 方案 A（采用）：emitter 设计为**同步函数** `Callable[[AgentTraceEvent], None]`，内部只做 list.append（`AgentJob.events` 是 thread-safe 的纯 list，GIL 保证 single-writer 场景安全），让 chat 路径和 Celery 路径都能直接用。
- 方案 B：emitter 是协程，agent 内部用 `asyncio.run_coroutine_threadsafe` 跨 loop 投递 — 否决：复杂度高，对一个只追加的 buffer 而言过度设计。

**采用方案 A**。`AgentTraceEvent` 是 plain dict，emitter 是普通函数。

### Decision 4: 日志详情路径用 Redis 有界 list

Celery worker 进程里的 emitter：

```python
def emit(event):
    r = redis.from_url(settings.redis_url)
    key = f"ai_analysis:trace:{ctx.task_id}"
    pipe = r.pipeline()
    pipe.rpush(key, json.dumps(event))
    pipe.ltrim(key, -MAX_TRACE_EVENTS, -1)   # 默认 2000，超过截断旧的
    pipe.expire(key, TRACE_TTL_SECONDS)      # 默认 3600
    pipe.execute()
```

新 SSE 端点 `GET /logs/{log_id}/ai-analysis/trace/stream` 的拉取语义：

1. 通过 `log_id` 查 `LogRecord.ai_analysis_task_id`；若任务已 `succeeded` / `failed`，直接从 `ai_analysis_result.trace_events` 一次性 yield 全部事件 + `run_complete` / `cancelled` 关闭。
2. 任务运行中：循环 `LRANGE key cursor -1`，把新事件 yield 出去，记录已发的 `seq`；用 `BLPOP` 不合适（消耗事件），改用 `LRANGE` + 短 sleep（200ms）轮询。客户端断开重新 `GET` 即从头重放，与 chat 路径语义一致。
3. 任务完成后再多 yield 一次终态事件（`run_complete` / `cancelled` / `error`），然后关闭流。

**为什么不用 Redis Pub/Sub**：
- Pub/Sub 不保留历史，客户端断连或晚到都拿不到已发事件，与"刷新页面重放"的需求冲突。
- List + LTRIM 提供天然的"最近 N 条"语义，TTL 处理孤儿任务。

**为什么不用 Celery `update_state` meta 累积**：`update_state` 是"最新一次状态覆盖"，无法承载事件流；硬塞会引入巨大的 `meta` 字段并被频繁覆写。

### Decision 5: 任务结束后把 trace 持久化到 `ai_analysis_result`

`run_complete` 时，agent 把累积的 `trace_events` 整体写入返回 dict：

```python
return {
    ...,
    "tool_trace": [...],            # 旧字段保留，从 trace_events 派生
    "trace_events": [...],           # 新字段：完整事件流
    "trace_summary": {
        "thought_duration_seconds": 42.3,
        "tool_call_count": 22,
        "thinking_chars": 1853,
    },
}
```

- `LogRecord.ai_analysis_result` 是 JSON 列，无 schema 变更。
- `trace_events` 的体积上限：单事件 ≤ 4 KB（excerpt 截断），单任务 ≤ 2000 条 → 上限约 8 MB；实际典型任务 < 200 条，约 800 KB。可接受。

### Decision 6: 前端单组件双入口

`AgentTraceStream.vue` 输入是响应式 `events: AgentTraceEvent[]`，不关心 SSE 是从 chat 还是 log detail 来的。事件源各自由各页面用 `useAgentTraceStream.ts` composable 封装：

- chat 入口：复用 `AIChat.vue` 已有的 SSE 读取循环（在 `processChunk` 里识别 `event === 'agent_trace'` 并 append）；
- 日志详情入口：新建一个 SSE consumer 指向 `/api/v1/logs/{log_id}/ai-analysis/trace/stream`，组件挂载时打开、卸载时关闭，任务结束后从 `ai_analysis_result.trace_events` 加载历史。

**组件状态机**：

每个 step 卡片状态由 `step_start` → `step_delta*` → `step_end` 推进；运行中默认展开+流式 append；`step_end` 后默认折叠为一行 `<tool_name> · <input 摘要> · <duration>s · <status>`。点击展开后状态持久（直到下次组件销毁）。

最终（`run_complete` / `cancelled` / `error`），所有卡片整体被一个外层"汇总条"覆盖（不销毁内部卡片，只在顶层显示一行 + 折叠 chevron）。顶层一行文案：

- 正常完成：`Thought for {trace_summary.thought_duration_seconds.toFixed(1)}s · {trace_summary.tool_call_count} tool calls`
- 取消：`Cancelled after {duration}s · {tool_call_count} tool calls`
- 错误：`Failed after {duration}s · {tool_call_count} tool calls`

下方副标题统一：`Generated by AI and can make mistakes`。点击外层一行 → 展开还原所有 step 卡片（每张卡片仍维持自己的折叠态）。

### Decision 7: 旧前端兼容

- chat SSE 中**新增**的 `{ event: "agent_trace", ... }` 帧对老前端是未知 event type，老前端的 `processChunk` 命中默认分支静默跳过 → 不破坏。
- `LogRecord.ai_analysis_result` 中新增字段对老前端是未知 JSON key → 不破坏。
- 旧 `tool_trace` 字段继续由后端从 `trace_events` 派生写入（仅保留 tool_use 类事件，按现有结构 `{name, input, output_excerpt}`）。

## Risks / Trade-offs

- **Redis 内存膨胀**：高并发分析任务下 trace key 累积。
  → 缓解：`LTRIM` 限定单 key ≤ 2000 条事件、`EXPIRE` TTL 1 小时；新增 metric `ai_analysis_trace_redis_bytes`，超过阈值告警。

- **事件顺序**：SSE 队列里 `agent_trace` 与 `log_analysis_status` 是同一条流，但前端按到达顺序解析；如果某条 `agent_trace` 事件因网络抖动晚到，前端按 `seq` 排序去重即可。
  → 缓解：组件维护 `lastSeq` 水位线，乱序 / 重复直接丢弃。

- **客户端 long-running SSE**：trace 流可能持续 60s+，受代理 / 浏览器 idle 超时影响。
  → 缓解：服务端每 15s 至少发一个事件（即使是空 `system_notice`，类似 keep-alive），与现有 `_AGENT_PROGRESS_INTERVAL_SECONDS = 15` 对齐。

- **取消时事件丢失**：用户点击取消后，agent loop 在下一条 SDK 消息到达前不会感知 cancel；这期间 trace 仍在追加。
  → 缓解：cancel 触发时立刻 emit `system_notice {kind: "cancel_requested"}`，agent loop 退出时再 emit `cancelled`，让用户看到两阶段反馈。

- **大 thinking 块**：Claude 思考 token 可能一次推 10 KB+，全文塞进 SSE 帧会撑大单帧。
  → 缓解：emitter 内部把单事件 `text_chunk` / `output_chunk` 切片 ≤ 4 KB 后再发，多次 delta。

- **`run_sync` 跨 loop 问题**：emitter 是同步函数避开这个问题（Decision 3）；但如果未来要让 emitter 做异步 I/O（例如直接写 WebSocket），需重新评估。
  → 缓解：当前 chat 路径用 list append、Celery 路径用同步 redis client，都是同步 I/O，OK。未来若需要异步 sink，再引入 `run_coroutine_threadsafe` 适配层。

- **trace 持久化体积**：单条结果可能 1–2 MB，影响 LogRecord 行大小与查询 P99。
  → 缓解：`LogRecord.ai_analysis_result` 已是 JSON 列；如果发现性能退化，下一个变更把 `trace_events` 拆到独立表（本变更不动表结构以减少 blast radius）。

- **测试基础设施**：streaming 行为难做单元测试。
  → 缓解：Agent 单测注入 fake emitter 收集事件序列、断言 schema；前端组件用 storybook + 一组手工 fixture 事件流回放。

## Migration Plan

1. 后端先发：`AgentTraceEvent` 协议、`trace_emitter` 注入、Redis 缓冲、新 SSE 端点；`AgentJob.events` 同步追加 `agent_trace`。此阶段老前端不受影响。
2. 前端 `AgentTraceStream.vue` 组件落地，先接入 `AIChat.vue`。
3. 前端接入 `LogDetail.vue`，并实现"页面刷新后从 `ai_analysis_result.trace_events` 回放"。
4. 监控 Redis 用量 + SSE 连接稳定性 1 周后，把旧的 `tool_trace` 字段在前端废弃（仅后端继续派生填入，下一个变更再删）。

**回滚**：把前端组件挂载条件回到 `false`、关掉新 SSE 端点路由、`trace_emitter` 传 `None`。后端事件协议、Redis key、JSON 字段写入都是惰性新增，不会破坏旧路径。

## Open Questions

- 取消按钮目前是否对所有 log 入口都开放？日志详情页 Celery 任务取消的现有 API 是什么？需在 tasks.md 阶段确认 `app/api/logs.py` 是否已经暴露 cancel 接口，否则本变更要顺手补一个；不补则前端取消按钮在日志详情入口隐藏。
- 是否需要把 `mcp__project_repo__lookup_project_repo` 的工具显示名做白名单友好渲染（"项目仓库查询"）？后端只下发 raw `tool_name`，前端做名称映射比较简单——但映射表放前端会让后端新增工具时需要前端同步发版。**初步决策**：前端维护一份 fallback 映射，未匹配的工具名直接展示原名。
