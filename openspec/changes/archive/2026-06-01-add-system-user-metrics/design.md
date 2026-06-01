## Context

现有后端已经有一条很窄的 metrics 链路：`app/utils/metrics.py` 定义了 Prometheus counter/gauge，`app/api/metrics.py` 暴露 `GET /metrics`。这条链路只覆盖 agent trace event 数量和 Redis trace buffer byte size，适合 Prometheus scrape，但没有历史事件表，也没有用户维度。

AI Token 用量目前分散在多个地方：

- `LogAnalysisAgent`、`ProjectExpertAgent`、`PackageSearchAgent` 通过 SDK message usage 累加 `input_tokens/output_tokens/cache_read_tokens`，并把结果放在 result payload 里。
- `DeviceAgent` 复用 log-analysis 的 `_RunState`，内部已有 token 累加，但终态事件和 `ChatAgentRun` 没有持久化统一 usage。
- `GeneralAgent` 与 `title_generator_service` 使用 Claude Agent SDK 小模型，但当前只提取文本，没有统一累计 SDK usage。
- 日志分析的历史结果保存在 `LogRecord.metadata_json.extra_fields.ai_analysis_result`；主聊天 run 元数据保存在 `chat_agent_runs`；包检索返回 `usage`，但没有用户归属与后台汇总。

系统已有用户、会话、聊天消息、后台 run、日志上传、Raven 包管理、设备连接与项目专家等业务域。metrics 需要覆盖这些域的核心运营指标，同时重点保证 Token 消耗可以按系统和用户准确查询。

约束：

- `/metrics` 不能使用 `user_id/session_id/run_id/task_id` 等高基数 labels。
- 业务流程不能因为 metrics 写入失败而失败。
- metrics 不得保存 prompt、answer、tool output、Authorization/Cookie、带 token 的仓库 URL 等敏感内容。
- 当前项目同时存在 async FastAPI 服务、后台 asyncio task、同步 Celery/脚本式任务，采集接口需要兼容这些调用路径。

## Goals / Non-Goals

**Goals:**

- 系统级 Token 统计：按时间范围、时间桶、Agent/source、provider、model、status、token_type 汇总。
- 用户级 Token 统计：按用户、时间范围、Agent/source、provider、model 汇总，并支持用户列表排行和单用户详情。
- AI run/invocation 统计：运行次数、成功/失败/取消/stale、错误类型、耗时、工具调用数、trace event 数。
- 业务统计：用户/会话/消息活跃度、日志上传与 AI 分析状态、包数量/上传/下载/检索、设备连接摘要。
- 保留并扩展 Prometheus `/metrics`，用于系统级监控和告警。
- 提供后台 API 和用户自查 API，且权限边界清晰。
- 新采集点幂等，避免同一次 run 在重试、重连、终态持久化时重复计费。

**Non-Goals:**

- 不在本变更内实现前端可视化大屏；只提供后端 API 和数据契约。
- 不引入外部时序数据库、数据仓库或消息队列。
- 不硬编码 Anthropic、DeepSeek 或 custom provider 的实时价格；价格由配置提供，未配置时成本字段为 `null`。
- 不回填所有历史 Token 明细到事件表；只做 best-effort 历史派生和上线后的准确采集。
- 不把每一次普通 HTTP 请求都持久化为用户级事件；HTTP 请求指标走 Prometheus。

## Decisions

### Decision 1: 使用持久化 metric event 表作为用户级统计事实源

新增 SQLAlchemy model，建议命名 `MetricEvent`，表名 `metric_events`。一行代表一次可审计事件，AI 调用以一次 invocation/run 终态为粒度。

核心字段：

- `id: String(36)` UUID 主键。
- `idempotency_key: String(255) UNIQUE`，例如 `ai_usage:chat_run:<run_id>`、`ai_usage:log_task:<task_id>`、`ai_usage:package_search:<session_id-or-uuid>`。
- `occurred_at: DateTime`，事件发生时间，独立于 row 创建时间。
- `event_type: String(64)`，首批值：`ai_usage`、`chat_activity`、`log_activity`、`package_activity`、`device_activity`。
- `source: String(64)`，如 `general_agent`、`device_agent`、`log_analysis_agent`、`project_expert_agent`、`package_search_agent`、`title_generator`、`log_upload`、`package_download`。
- `user_id: String(36) | NULL`，登录用户填充；匿名或系统任务为空。
- `owner_scope: String(128) | NULL`，仅用于归属审计和匿名聚合，不返回给普通用户。
- `session_id/run_id/task_id/log_id/project_repo_id: nullable`，用于后台排查，API 默认只在 raw event 审计中返回。
- `agent_kind/provider/model/status/error_kind: nullable`。
- `duration_ms: Integer | NULL`。
- `input_tokens/output_tokens/cache_read_tokens/cache_write_tokens/total_tokens: Integer NOT NULL DEFAULT 0`。
- `cost_microusd: Integer | NULL`，按配置估算的百万分之一美元，未配置价格时为空。
- `metadata_json: Text | NULL`，只允许保存低敏摘要，例如 `tool_call_count`、`trace_event_count`、`log_type`、`package_type`、`result_count`。

索引：

- `idx_metric_events_occurred_at`
- `idx_metric_events_user_time (user_id, occurred_at)`
- `idx_metric_events_event_source_time (event_type, source, occurred_at)`
- `idx_metric_events_agent_model_time (agent_kind, provider, model, occurred_at)`
- `idx_metric_events_status_time (status, occurred_at)`
- `idempotency_key UNIQUE`

Rationale: 用户级查询需要历史事实源，Prometheus 不适合作为用户账单或审计系统。单表事件模型比一开始就引入多张 rollup 表简单，足以支撑当前 SQLite/PostgreSQL 双环境。

Alternative considered: 只从 `chat_agent_runs`、`log_records.metadata_json`、package JSON 即时聚合。该方案无需迁移，但 Token usage 分布不完整，package/title/general usage 无法稳定归属，查询逻辑会散落在各业务表里。

### Decision 2: Prometheus 只暴露低基数系统指标

扩展 `app/utils/metrics.py`，保留 soft import 和 no-op fallback 风格。新增指标建议：

- `raven_ai_tokens_total{source,agent_kind,provider,model,token_type}`
- `raven_ai_invocations_total{source,agent_kind,provider,model,status}`
- `raven_ai_invocation_duration_seconds{source,agent_kind,provider,model,status}`
- `raven_ai_errors_total{source,agent_kind,error_kind}`
- `raven_http_requests_total{method,route,status_code}`
- `raven_http_request_duration_seconds{method,route,status_code}`
- `raven_log_uploads_total{log_type,status}`
- `raven_log_uploaded_bytes_total{log_type}`
- `raven_package_activity_total{action,package_type,status}`
- `raven_device_connections{state}` gauge

不得加入 `user_id`、`username`、`owner_scope`、`session_id`、`run_id`、`task_id`、`log_id`、`project_repo_id` 等 labels。HTTP route label 使用 FastAPI route template，如 `/api/v1/logs/{log_id}`，不能使用原始 path。

Rationale: Prometheus 用于告警和系统趋势，低基数是稳定性的底线。用户级统计放入数据库 API。

Alternative considered: 为用户 Token 使用 Prometheus labels。这样查询方便，但用户数和 run 数会导致 series 爆炸，也会泄露用户标识。

### Decision 3: 统一 metrics service，业务代码只调用 record helper

新增 `app/services/metrics_service.py`，提供：

- `record_ai_usage(...)`
- `record_ai_usage_sync(...)` 或内部兼容 sync session 的 helper
- `record_business_event(...)`
- `aggregate_system_metrics(...)`
- `aggregate_user_metrics(...)`
- `list_metric_events(...)`

`record_ai_usage` 的输入以结构化字段为主：

```python
record_ai_usage(
    source="device_agent",
    agent_kind="device",
    provider=provider,
    model=model,
    status=status,
    usage={"input_tokens": 1, "output_tokens": 2, "cache_read_tokens": 3},
    user_id=user_id,
    owner_scope=owner_scope,
    session_id=session_id,
    run_id=run_id,
    duration_ms=duration_ms,
    error_kind=error_kind,
    idempotency_key=f"ai_usage:chat_run:{run_id}",
    metadata={"tool_call_count": 5, "trace_event_count": 42},
)
```

Helper 行为：

- 自动规范化 token 字段，缺失视为 0。
- 自动计算 `total_tokens = input + output + cache_read + cache_write`。
- 根据配置计算 `cost_microusd`，未命中价格返回 `None`。
- 使用 `idempotency_key` 做 insert-if-not-exists；已存在则不重复累计 Prometheus counter。
- 捕获并记录 warning/debug，不向调用方抛出导致业务失败的异常。

Rationale: 采集点多，统一入口可减少重复逻辑，后续新增模型价格、metadata allowlist、Prometheus 同步都只改一处。

Alternative considered: 让各 Agent 直接操作 `MetricEvent` model。短期代码少，但会导致字段规范、幂等和隐私过滤不一致。

### Decision 4: AI usage 在服务终态层记录，Agent 负责产出 usage

采集边界采用“Agent 产出 usage，业务服务终态入账”：

- `DeviceAgent` 在 `run_complete` 事件中增加 `token_usage`、`duration_seconds`、`provider`、`model`；`ChatRunService._persist_terminal` 在写 `chat_agent_runs` 终态时记录 metrics。
- `GeneralAgent` 新增 SDK usage 累加，并在 `run_complete` 中带 `token_usage`；`ChatRunService._persist_terminal` 同样入账。
- `LogAnalysisAgent` 和 `ProjectExpertAgent` 已返回 `token_usage`，分别由 `LogAnalysisChatService` / `ProjectExpertChatService` 终态持久化处入账；独立日志 AI Celery 流程在 `app/tasks/ai_analysis.py` 保存结果后入账。
- `PackageSearchAgent` 已返回 `usage`，由 `app/api/packages.py::agent_search_packages` 在非流式响应和流式 final 结束后入账。若请求可解析登录用户，则写 `user_id`，否则只写 session/source。
- `title_generator_service` 新增 usage 累加，返回内部 result 对象或在 helper 内直接使用 `source="title_generator"` 记录；若调用方有 `user_id/session_id` 则传入，否则作为 system usage。

Rationale: Agent 本身不应该依赖数据库 session；终态服务层已经知道 user/session/run/status，最适合做归属与幂等。

Alternative considered: 在 `_emit_for_message` 每收到 usage 就立刻入账。这样实时性更好，但中途失败、重试和流式断开会制造大量部分事件，不利于用户账单口径。

### Decision 5: API 聚合由 metrics service 组合事件表与现有业务表

新增后台 API，建议放在 `app/api/admin_metrics.py` 或并入 `app/api/admin.py`：

- `GET /admin/metrics/overview?from=&to=&bucket=hour|day`
  - 总 Token、输入/输出/cache 分解、AI invocation 数、成功率、错误数、平均/分位耗时、活跃用户数、会话/消息数、日志/包/设备摘要、time series。
- `GET /admin/metrics/users?from=&to=&page=&per_page=&sort=total_tokens`
  - 用户列表：`user_id`、`username`、`display_name`、`role`、`total_tokens`、`input_tokens`、`output_tokens`、`run_count`、`success_count`、`failure_count`、`message_count`、`last_active_at`、`top_agent_kind`。
- `GET /admin/metrics/users/{user_id}?from=&to=&bucket=day`
  - 单用户详情：Token 时间序列、Agent/model/provider 分布、status/error 分布、最近 AI events。
- `GET /admin/metrics/events?from=&to=&event_type=&source=&user_id=&page=&per_page=`
  - 原始事件分页，供审计排查。

新增用户自查：

- `GET /api/v1/users/me/metrics?from=&to=&bucket=day`
  - 只返回当前登录用户自己的 Token、run、message 和时间序列摘要。

业务统计来源：

- Token 和 AI run：`metric_events WHERE event_type='ai_usage'`。
- 用户/会话/消息：`users`、`chat_sessions`、`chat_messages`、`chat_agent_runs`。
- 日志：`log_records` 的上传数量、文件大小、状态、log_type、AI 分析状态和结果字段。
- 包：`raven_package_service.get_all_packages()` 的包数量、总大小、类型分布；新增上传/下载/agent-search event 用于趋势。
- 设备：`device_link_manager` 当前连接状态 gauge；设备 Agent run 与 tool counts 来自 AI usage metadata。

Rationale: 不强迫所有历史业务数据先转成 metrics event，避免大规模回填。API 可以把事实事件与已有领域表组合成更完整的 overview。

Alternative considered: 所有业务统计都只依赖 `metric_events`。这会让历史日志、包和会话数据在上线前不可见，也要求过多写入点。

### Decision 6: 价格估算使用配置映射，默认不估价

新增配置项，名称可调整：

- `ai_metrics_pricing_json`
- 或 `AI_METRICS_PRICING_JSON='{"anthropic":{"claude-sonnet-4-6":{"input_per_million":3.0,"output_per_million":15.0}}}'`

支持按 `provider/model/token_type` 查价。字段单位使用 “每 100 万 token 的美元价格”，计算后以 `cost_microusd` 整数保存，API 可同时返回 `estimated_cost_usd` 字符串/数字。

未配置价格、model 未命中、custom provider 未声明价格时：

- `cost_microusd = null`
- API 明确返回 `cost_estimated=false`

Rationale: 模型价格会变化，也可能使用 DeepSeek/custom provider。硬编码价格会很快过期，且容易造成错误成本承诺。

Alternative considered: 不做成本字段。Token 是核心诉求，但运维通常还会追踪成本；保留可选估算字段不影响没有价格配置的部署。

### Decision 7: 隐私过滤采用 allowlist

`metadata_json` 只允许保存预定义 key：

- `tool_call_count`
- `trace_event_count`
- `log_type`
- `package_type`
- `result_count`
- `project_code` 可选，但不得包含 repo URL 或 token
- `error_kind`

禁止保存：

- 用户 prompt、assistant answer、日志内容、tool input/output。
- `Authorization`、`Cookie`、`Set-Cookie`。
- 带 token 的 URL 或 git token。
- 任意高维文本 blob。

Rationale: metrics 数据通常保留更久、访问面更宽，必须默认低敏。

Alternative considered: 保存完整 request/result JSON 方便排查。项目已有 `trace_events_json` 和业务结果存储，metrics 不应成为第二份敏感数据副本。

## Risks / Trade-offs

- [Risk] SQLite 上按长时间范围聚合 `metric_events` 可能变慢。→ Mitigation: 首版加时间和用户/来源复合索引，API 默认限制时间范围；若数据量增长，再新增日级 rollup 表。
- [Risk] 同一 AI run 在不同终态路径重复入账。→ Mitigation: 每个采集点必须提供稳定 `idempotency_key`，metrics service 使用唯一约束做幂等。
- [Risk] 某些 SDK message 没有 usage 字段，导致 Token 为 0。→ Mitigation: usage 缺失时记录 invocation/run count 和 model/status，Token 字段为 0；测试覆盖缺失 usage 不报错。
- [Risk] Prometheus labels 中 model 名称仍可能偏多。→ Mitigation: 只允许 provider/model/source/status 等低中基数维度；后续如 custom model 太多，可增加配置把未知 model 归一到 `custom`.
- [Risk] 成本估算被误认为账单。→ Mitigation: 字段命名使用 `estimated_cost`，未配置价格返回 `null`，API 返回 `cost_estimated` 标志。
- [Risk] metrics 写入失败掩盖真实消耗。→ Mitigation: 记录 warning 并暴露 `raven_metrics_record_failures_total{source}`，同时不影响主业务。

## Migration Plan

1. 新增 `metric_events` model、Alembic migration 与启动时 additive column backfill（如对 `chat_agent_runs` 增加 token summary 字段）。
2. 新增 metrics service 和 Prometheus 指标，保持现有 `/metrics` 测试通过。
3. 按 source 逐步接入 AI usage：package search、chat run、log analysis、project expert、title generator。
4. 新增后台 API 和用户自查 API。
5. 可选 best-effort 历史派生：
   - 从 `chat_agent_runs.trace_events_json` / `LogRecord.metadata_json.extra_fields.ai_analysis_result.token_usage` 生成一次性 `metric_events`，使用 `historical=true` metadata。
   - 仅在明确运行管理脚本时执行，不在服务启动时自动回填。
6. 回滚策略：
   - 删除采集调用后业务仍可运行。
   - 新表不影响旧表；回滚代码时保留表即可。
   - Prometheus 新指标消失只影响监控面板，不影响 API 主流程。

## Open Questions

- 用户自查 API 是否需要展示成本估算，还是只展示 Token？默认建议展示 Token 和 `estimated_cost_usd`，但明确标注为估算。
- 匿名用户是否需要在后台用户排行中单独按 owner_scope 展示？默认建议只汇总为 `anonymous`，raw event 审计可按 owner_scope 过滤。
- 是否需要在本变更同时做前端后台页面？本提案只定义后端能力，前端页面可作为后续 OpenSpec change。
