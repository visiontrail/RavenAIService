## Why

系统目前只有轻量的 Prometheus trace 指标，AI Token 用量则分散在部分 Agent 的运行结果、日志字段或返回 payload 中，无法稳定回答“全系统消耗了多少 Token”“某个用户消耗了多少 Token”“哪个 Agent/模型/时间段消耗最高”等运维与成本问题。

需要新增一套后端统计能力，把 AI 用量、用户活跃、Agent 运行、日志/包/设备等关键业务指标统一采集、持久化和聚合，同时继续保留 `/metrics` 作为低基数 Prometheus scrape 入口。

## What Changes

- 新增持久化 metrics 事件模型与迁移，用于记录可按时间、用户、Agent、provider、model、status 聚合的事实数据；重点覆盖 `input_tokens`、`output_tokens`、`cache_read_tokens`、`cache_write_tokens`、`total_tokens` 与可选成本估算。
- 新增 metrics 服务层，提供统一的 `record_ai_usage(...)` / `record_business_metric(...)` 等接口；记录失败不得影响主业务流程，并通过幂等 key 避免同一次 run 重复入账。
- 扩展现有 Agent 与 AI 调用入口的 Token 采集：
  - `LogAnalysisAgent`、`ProjectExpertAgent`、`PackageSearchAgent`、`DeviceAgent` 的既有 SDK usage 累加结果写入统一 metrics。
  - `GeneralAgent` 与 `title_generator_service` 补齐 SDK usage 累加。
  - `ChatRunService`、`LogAnalysisChatService`、`ProjectExpertChatService`、package search API 在终态统一落库 run/invocation metrics。
- 扩展 Prometheus 指标，但避免以 `user_id`、`session_id`、`run_id` 作为 labels；系统级指标使用低基数 labels（如 `agent_kind`、`provider`、`model`、`status`、`token_type`）。
- 新增后台 metrics API：
  - 系统 overview：总 Token、总 run、成功率、错误数、平均/分位耗时、活跃用户、日志/包/设备摘要。
  - 用户列表统计：每个用户的 Token、run 次数、消息数、最近活跃时间、按 Agent 分布。
  - 单用户详情：时间序列、Agent/model/provider 分布、最近 run 与错误。
  - 原始事件分页查询，用于审计和排查。
- 新增用户自查 API（登录用户只能查看自己的摘要），管理后台 API 继续使用现有 admin bearer 鉴权。
- 新增测试覆盖 metrics 采集幂等、Token 聚合、用户隔离、Prometheus label cardinality、API 权限与时间范围过滤。

## Capabilities

### New Capabilities

- `system-user-metrics`: 定义后端系统级与用户级 metrics 的采集、持久化、聚合查询、Prometheus 暴露、权限边界和 Token 用量统计语义。

### Modified Capabilities

- None.

## Impact

- **数据库**：新增 metrics 事件表（以及必要索引/可选日级 rollup 表）；可能在 `chat_agent_runs` 增加可选 token summary 字段以便 run 快照直接展示。
- **后端服务**：新增 `app/services/metrics_service.py`（命名可调整）与 metrics 记录 helper；改造各 Agent 终态路径和 package search/title generator 调用路径。
- **API**：新增 `/admin/metrics/*` 管理接口与 `/api/v1/users/me/metrics` 自查接口；保留并扩展现有 `/metrics` Prometheus endpoint。
- **配置**：新增可选模型价格配置（例如按 provider/model/token_type 设置单价）；默认不硬编码价格，成本字段在未配置时返回 `null`。
- **安全与隐私**：metrics 事件不得保存 prompt、assistant answer、tool output、token-bearing URL 或 Authorization/Cookie；Prometheus labels 不包含用户、会话、run 等高基数或敏感标识。
- **测试**：新增服务层、API、Agent 终态采集与 Prometheus 输出测试；回归现有 `tests/test_metrics.py`。
