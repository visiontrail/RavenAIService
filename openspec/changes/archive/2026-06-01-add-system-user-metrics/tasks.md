## 1. Data Model And Configuration

- [x] 1.1 Add a `MetricEvent` SQLAlchemy model with id, idempotency key, event/source fields, ownership fields, AI usage fields, duration, estimated cost, sanitized metadata, and timestamps
- [x] 1.2 Add an Alembic migration for `metric_events` with unique `idempotency_key` and indexes for time, user/time, event/source/time, agent/model/time, and status/time queries
- [x] 1.3 Add Pydantic response models for system overview, user metrics rows, user metrics detail, self metrics summary, raw metric events, and time series buckets
- [x] 1.4 Add optional pricing settings for provider/model/token-type cost estimates, defaulting to no configured prices
- [x] 1.5 If needed for run snapshots, add optional token summary columns to `chat_agent_runs` and backfill them through the existing additive-column startup path (deferred: `metric_events.run_id` covers run-scoped queries; revisit only if run-snapshot UI needs inline token columns)

## 2. Metrics Service And Prometheus

- [x] 2.1 Create `app/services/metrics_service.py` with token normalization, total-token calculation, cost estimation, and metadata allowlist sanitization
- [x] 2.2 Implement async metric event insertion with idempotency and best-effort failure handling
- [x] 2.3 Implement sync-compatible metric event insertion for Celery/synchronous task paths or provide a safe bridge used by `app/tasks/ai_analysis.py`
- [x] 2.4 Implement system aggregation queries for token totals, invocation counts, status/error groups, duration summaries, and time series buckets
- [x] 2.5 Implement user aggregation queries for user list rows, single-user detail, self metrics, and recent sanitized events
- [x] 2.6 Extend `app/utils/metrics.py` with low-cardinality AI token, invocation, duration, error, HTTP, log, package, device, and metrics-failure Prometheus metrics
- [x] 2.7 Add helpers that update Prometheus only after a metric event insert succeeds, so duplicate idempotency keys do not double count
- [x] 2.8 Instrument `RequestLoggingMiddleware` or a dedicated middleware to record Prometheus HTTP request count and duration using route templates rather than raw paths

## 3. AI Usage Instrumentation

- [x] 3.1 Add or reuse a shared SDK usage accumulator that handles input, output, cache read, and cache write token fields across Agent implementations
- [x] 3.2 Extend `GeneralAgent` to accumulate SDK usage and include `token_usage`, provider, model, and duration in terminal events/results
- [x] 3.3 Extend `DeviceAgent` terminal `run_complete` events to include token usage, provider, model, and duration
- [x] 3.4 Record `general_agent` and `device_agent` usage from `ChatRunService._persist_terminal` with authenticated user/session/run ownership and stable idempotency keys
- [x] 3.5 Record `log_analysis_agent` usage from `LogAnalysisChatService` terminal persistence and from the standalone `app/tasks/ai_analysis.py` completion path
- [x] 3.6 Record `project_expert_agent` usage from `ProjectExpertChatService` terminal persistence with project repository metadata when available
- [x] 3.7 Record `package_search_agent` usage for both non-streaming and streaming `/packages/agent-search` responses, including result counts in sanitized metadata
- [x] 3.8 Extend `title_generator_service` to accumulate usage and record `title_generator` metrics with caller-provided user/session context when available
- [x] 3.9 Ensure failed, cancelled, stale, timeout, and schema-mismatch terminal states still record an invocation event with status/error metadata and any available tokens

## 4. Business Metrics Integration

- [x] 4.1 Add business event recording for log uploads, including log type, status, and uploaded bytes without storing file contents
- [x] 4.2 Add business event recording for package uploads, downloads, batch downloads, and type downloads with package type/status metadata
- [x] 4.3 Add package inventory aggregation from `raven_package_service.get_all_packages()` for package count, total bytes, and type distribution
- [x] 4.4 Add log aggregation from `log_records` for upload count, uploaded bytes, status counts, log type counts, and AI analysis terminal counts
- [x] 4.5 Add chat/user aggregation from `users`, `chat_sessions`, `chat_messages`, and `chat_agent_runs`
- [x] 4.6 Add device connection summary aggregation from `device_link_manager` and update the Prometheus device gauge

## 5. Metrics APIs

- [x] 5.1 Add an admin metrics router or extend `app/api/admin.py` with `/admin/metrics/overview`
- [x] 5.2 Add `/admin/metrics/users` with sorting, pagination, time filtering, and per-user token/activity rows
- [x] 5.3 Add `/admin/metrics/users/{user_id}` with single-user token time series, distributions, status/error groups, and recent events
- [x] 5.4 Add `/admin/metrics/events` with raw sanitized event filtering and bounded pagination
- [x] 5.5 Add `/api/v1/users/me/metrics` that returns only the current authenticated user's metrics
- [x] 5.6 Register the metrics router in `app/main.py` and ensure admin routes use the existing admin bearer authentication
- [x] 5.7 Implement shared parsing/validation for `from`, `to`, `bucket`, `page`, and `per_page`, including sensible defaults and bounds

## 6. Privacy, Safety, And Performance

- [x] 6.1 Enforce metadata allowlist so metrics never persist prompts, assistant answers, tool inputs/outputs, logs, headers, cookies, git tokens, or token-bearing URLs
- [x] 6.2 Add tests or assertions that Prometheus samples never expose user, owner, session, run, task, log, package, or project identifiers as labels
- [x] 6.3 Ensure metrics recording exceptions are logged and counted but never fail chat, log analysis, project expert, package search, title generation, upload, or download flows
- [x] 6.4 Add default time range and maximum page-size protections to prevent accidental full-table scans through API calls
- [x] 6.5 Add best-effort historical backfill script or management command for existing log analysis token usage, guarded so it only runs when explicitly invoked

## 7. Tests

- [x] 7.1 Add unit tests for token normalization, total-token calculation, metadata sanitization, pricing estimates, and missing-pricing behavior
- [x] 7.2 Add service tests proving idempotency prevents duplicate metric rows and duplicate token totals
- [x] 7.3 Extend Prometheus tests to cover new counters/histograms, no-op fallback, metrics failure counter, and forbidden high-cardinality labels
- [x] 7.4 Add Agent/service tests for `GeneralAgent`, `DeviceAgent`, log analysis, project expert, package search, and title generator usage recording using fake SDK messages/results
- [x] 7.5 Add admin API tests for overview aggregation, user list sorting, single-user detail, raw events filtering, and time bucket output
- [x] 7.6 Add user self API tests proving users can read only their own metrics and cannot infer another user's usage
- [x] 7.7 Add resilience tests proving metrics insertion failures do not break primary business responses or terminal persistence

## 9. Admin Console Metrics Dashboard (Frontend)

- [x] 9.1 Add TypeScript response types for the metrics overview, user list rows, user detail, and raw events mirroring `app/models/metrics.py`
- [x] 9.2 Add `metricsApi` admin client methods (overview, users, user detail, events) that reuse the existing admin bearer token client
- [x] 9.3 Add an `AdminMetrics.vue` view rendering system overview KPIs, time series, business summaries, per-user ranking, single-user detail drill-in, and raw events, with shared time-range/bucket controls
- [x] 9.4 Register the `/admin/metrics` route and add a "数据指标" item to the admin navigation

## 8. Documentation And Operational Notes

- [x] 8.1 Document the new metrics APIs, date range semantics, bucket options, and response field meanings
- [x] 8.2 Document Prometheus metric names and labels, including the rule that user/session/run identifiers are intentionally excluded
- [x] 8.3 Document optional pricing configuration and clarify that returned cost is an estimate rather than a provider bill
- [x] 8.4 Document the explicit historical backfill command and rollback behavior
