# System & User Metrics

Auditable AI-token-usage and business-activity metrics for the Raven backend.

Every AI invocation and selected business event is persisted as one row in the
`metric_events` table — the single auditable fact source — and exposed through
admin/self HTTP APIs plus a low-cardinality Prometheus `/metrics` endpoint.

- Model / API schemas: [app/models/metrics.py](../app/models/metrics.py)
- Aggregation + recording service: [app/services/metrics_service.py](../app/services/metrics_service.py)
- HTTP APIs: [app/api/admin_metrics.py](../app/api/admin_metrics.py)
- Prometheus collectors: [app/utils/metrics.py](../app/utils/metrics.py)
- Historical backfill: [scripts/backfill_metric_events.py](../scripts/backfill_metric_events.py)
- Admin dashboard page: `/admin/metrics` in the web console
  ([frontend/src/views/AdminMetrics.vue](../frontend/src/views/AdminMetrics.vue))

---

## 1. Metrics HTTP APIs

Five read-only endpoints. The four `/admin/metrics/*` endpoints reuse the
existing **admin bearer** auth (`require_admin`); the self endpoint reuses the
**user bearer** auth (`get_current_user`) so a user can never read another
user's usage.

| Method & path | Auth | Purpose |
| --- | --- | --- |
| `GET /admin/metrics/overview` | admin | System-wide token / invocation rollup + business summaries |
| `GET /admin/metrics/users` | admin | Per-user ranking with sorting + pagination |
| `GET /admin/metrics/users/{user_id}` | admin | Single-user detail (series, distributions, recent events) |
| `GET /admin/metrics/events` | admin | Raw (sanitized) event audit feed |
| `GET /api/v1/users/me/metrics` | user | The caller's own metrics only |

A request to any `/admin/metrics/*` endpoint without a valid admin bearer token
returns `401`/`403` and no metrics payload. An unknown `user_id` on the detail
endpoint returns `404`.

### 1.1 Shared query parameters

All endpoints share the same parsing/validation helpers in
[app/api/admin_metrics.py](../app/api/admin_metrics.py), so defaults and bounds
are enforced uniformly and a single call can never trigger an unbounded
full-table scan.

| Param | Type | Default | Notes |
| --- | --- | --- | --- |
| `from` | ISO-8601 | `to - 7d` | Inclusive lower bound. Trailing `Z` accepted; tz-aware values are converted to naive UTC to match the persisted `occurred_at`. |
| `to` | ISO-8601 | now (UTC) | Exclusive upper bound. |
| `bucket` | `hour` \| `day` | `day` | Time-series granularity (overview / detail / self only). Any other value falls back to `day`. |
| `page` | int ≥ 1 | `1` | Pagination (users / events). |
| `per_page` | int | `20` users / `50` events | Clamped to `[1, 200]`. |
| `sort` | string | `total_tokens` | Ranking key for the users list. |
| `event_type`, `source`, `user_id` | string | — | Optional equality filters on `GET /admin/metrics/events`. |

#### Date range semantics

- The window is **`[from, to)`** — `from` inclusive, `to` exclusive — so
  adjacent windows tile without double-counting an event on the boundary.
- Omitting both `from` and `to` yields **the last 7 days**.
- Omitting only `from` defaults it to `to - 7 days`.
- `from` **must** be earlier than `to`, otherwise `400`.
- The maximum queryable window is **366 days**. A wider request is silently
  clamped to the last 366 days measured back from `to` (not rejected), so an
  over-broad call still returns a bounded, well-defined result.
- All timestamps in requests and responses are **UTC**. `occurred_at` is
  persisted naive-UTC; a tz-aware `from`/`to` is normalized to naive UTC before
  comparison.

#### Bucket options

`bucket` controls the granularity of `time_series` only (it does not affect
totals or distributions):

- `day` — one bucket per UTC calendar day (default).
- `hour` — one bucket per UTC hour. Prefer this only for short windows; over a
  366-day range it produces up to ~8,784 buckets.

Each `time_series` entry (`TimeSeriesBucket`) carries `bucket_start` plus the
four token counters, `total_tokens`, and `invocation_count` / `success_count` /
`failure_count` for that bucket.

### 1.2 Response field meanings

All endpoints return the standard `BaseResponse` envelope with the payload under
`data`.

**Token breakdown** (`TokenBreakdown`, present on every aggregate):

| Field | Meaning |
| --- | --- |
| `input_tokens` | Prompt / input tokens. |
| `output_tokens` | Generated / completion tokens. |
| `cache_read_tokens` | Tokens served from the provider prompt cache. |
| `cache_write_tokens` | Tokens written to the provider prompt cache. |
| `total_tokens` | `input + output + cache_read + cache_write`. Missing usage normalizes every counter to `0`. |

**Cost** (see [§3](#3-optional-cost-estimates)):

- `estimated_cost_usd` — estimated USD cost, or `null` when no pricing is
  configured for the relevant provider/model. **An estimate, not a bill.**
- `cost_estimated` — `true` when at least one contributing event had a usable
  price.

**Overview** (`GET /admin/metrics/overview` → `SystemOverview`):

- `tokens`, `estimated_cost_usd`, `cost_estimated`.
- `invocation_count`, `status_counts` (`succeeded` / `failed` / `cancelled` /
  `stale` / `timeout` / `other`), `error_count`.
- `duration_ms_avg`, `duration_ms_p95` (null when no durations recorded).
- `invocations_by_source` / `_by_agent_kind` / `_by_provider` / `_by_model` /
  `_by_status` — each a list of `{key, invocation_count, total_tokens}`
  (`key == null` means unknown).
- `time_series` — list of `TimeSeriesBucket` for the requested bucket.
- Business summaries: `chat`, `logs`, `packages`, `devices` (see below).

**Users list** (`GET /admin/metrics/users` → rows of `UserMetricsRow`):
`user_id`, `username`, `display_name`, `role`, token breakdown,
`estimated_cost_usd`, `run_count`, `success_count`, `failure_count`,
`message_count`, `last_active_at`, `top_agent_kind`. Rows are sorted by `sort`;
`page` / `per_page` / `total` describe the page.

**User detail** (`GET /admin/metrics/users/{user_id}` → `UserMetricsDetail`):
identity + token breakdown + cost, `invocation_count`, `status_counts`,
`message_count`, `last_active_at`, the four `invocations_by_*` distributions,
`errors_by_kind`, `time_series`, and `recent_events` (sanitized `RawMetricEvent`
list).

**Self** (`GET /api/v1/users/me/metrics` → `SelfMetricsSummary`):
the caller's own `user_id`, token breakdown + cost, `invocation_count`,
`status_counts`, `message_count`, `last_active_at`, `invocations_by_agent_kind`,
and `time_series`. It exposes **no other user's** id, username, events, or
totals, and accepts no `user_id` parameter.

**Raw events** (`GET /admin/metrics/events` → `RawMetricEvent` list): one row per
event with token counters, `source`, `status`, `model`, `occurred_at`, the
audit-only ownership identifiers, and a sanitized `metadata` object. It never
includes prompt text, assistant answers, tool input/output, or secrets.

**Business summaries** embedded in the overview:

- `chat` — `total_users`, `active_users`, `chat_session_count`,
  `chat_message_count`, `run_counts_by_status`.
- `logs` — `upload_count`, `uploaded_bytes`, `counts_by_log_type`,
  `counts_by_status`, `ai_analysis_counts`.
- `packages` — `package_count`, `total_bytes`, `counts_by_type`,
  `activity_counts`, `search_count`.
- `devices` — `counts_by_state` (current connection snapshot).

---

## 2. Prometheus metrics

`GET /metrics` returns Prometheus text exposition when `prometheus_client` is
installed. If it is unavailable the endpoint returns **HTTP 503** with an
explicit message (never a silently empty scrape), and all collectors degrade to
no-op stubs so imports stay safe.

> **Cardinality rule.** New metric labels are restricted to low/medium-cardinality
> dimensions only. `user_id`, `username`, `owner_scope`, `session_id`, `run_id`,
> `task_id`, `log_id`, and `project_repo_id` **MUST NEVER** appear as Prometheus
> labels. Per-user / per-run attribution lives exclusively in the database fact
> source and its APIs, never in Prometheus. A defensive `_label()` helper also
> coerces empty/None label values to `unknown`.

AI-usage collectors are bumped **only after a `metric_events` insert succeeds**,
so a duplicate idempotency key never double-counts in Prometheus.

| Metric | Type | Labels |
| --- | --- | --- |
| `raven_ai_tokens_total` | Counter | `source`, `agent_kind`, `provider`, `model`, `token_type` |
| `raven_ai_invocations_total` | Counter | `source`, `agent_kind`, `provider`, `model`, `status` |
| `raven_ai_invocation_duration_seconds` | Histogram | `source`, `agent_kind`, `provider`, `model`, `status` |
| `raven_ai_errors_total` | Counter | `source`, `agent_kind`, `error_kind` |
| `raven_http_requests_total` | Counter | `method`, `route`, `status_code` |
| `raven_http_request_duration_seconds` | Histogram | `method`, `route`, `status_code` |
| `raven_log_uploads_total` | Counter | `log_type`, `status` |
| `raven_log_uploaded_bytes_total` | Counter | `log_type` |
| `raven_package_activity_total` | Counter | `action`, `package_type`, `status` |
| `raven_device_connections` | Gauge | `state` |
| `raven_metrics_record_failures_total` | Counter | `source` |

Notes:

- `token_type` is one of `input` / `output` / `cache_read` / `cache_write`.
- `route` is always a **route template** (e.g. `/api/packages/{id}`), never a raw
  path, to keep HTTP cardinality bounded.
- `raven_metrics_record_failures_total` is incremented whenever best-effort
  metrics recording fails for a `source` (see [§5](#5-failure-isolation)).
- Pre-existing trace collectors `ai_analysis_trace_events_emitted_total{kind}`
  and `ai_analysis_trace_redis_bytes` remain unchanged.

---

## 3. Optional cost estimates

Cost is **optional, configuration-driven, and always an estimate** — it is
computed from configured unit prices, not from any provider invoice.

Configure prices via the `AI_METRICS_PRICING_JSON` setting
(`ai_metrics_pricing_json`). The value is a JSON string mapping
`provider → model → token-type price`, where each unit is **USD per 1,000,000
tokens**:

```json
{
  "anthropic": {
    "claude-opus-4-8": {
      "input_per_million": 15.0,
      "output_per_million": 75.0,
      "cache_read_per_million": 1.5,
      "cache_write_per_million": 18.75
    }
  }
}
```

Behavior:

- When pricing **is** configured for an event's provider + model, the event is
  persisted with a non-null `cost_microusd` (integer micro-USD) and the APIs
  expose `estimated_cost_usd` (= `cost_microusd / 1_000_000`, rounded to 6 dp)
  with `cost_estimated = true`.
- When pricing is **absent** or the JSON fails to parse, recording still
  succeeds with full token counters, `cost_microusd` is `null`, and the APIs
  return `estimated_cost_usd = null` / `cost_estimated = false`. Missing pricing
  never blocks metrics. Default: no prices configured (no cost estimation).
- Treat `estimated_cost_usd` as a planning estimate, not a billing figure;
  actual provider charges may differ.

---

## 4. Historical backfill

[scripts/backfill_metric_events.py](../scripts/backfill_metric_events.py) is an
**explicit, manually-invoked** maintenance script. It never runs on service
startup and never auto-runs. It derives one `ai_usage` event per historical log
analysis from the token usage already stored in
`log_records.metadata_json.extra_fields.ai_analysis_result`.

It uses the **same idempotency key the live Celery path uses**
(`ai_usage:log_task:<log_id>`), so inserts are idempotent: rows already recorded
by the live path are never duplicated and re-running is safe. Backfilled rows
carry `metadata.historical = true` so they are distinguishable from
live-recorded events. Prometheus counters are intentionally **not** bumped —
those are cumulative, timestamp-free totals and backfill must not retroactively
inflate live dashboards.

```bash
# Dry run (default): report what would be inserted, write nothing.
python scripts/backfill_metric_events.py

# Apply: actually insert the derived metric events.
python scripts/backfill_metric_events.py --apply

# Limit how many log records are scanned (useful for a first pass).
python scripts/backfill_metric_events.py --apply --limit 500
```

Output reports `scanned`, `candidates`, `inserted`, and `skipped_existing`
tallies.

**Rollback.** Deleting backfilled rows is safe and affects no business table:

```sql
DELETE FROM metric_events
WHERE event_type = 'ai_usage'
  AND metadata_json LIKE '%"historical": true%';
```

(Review the matched rows before running.)

---

## 5. Failure isolation

Metrics recording is **best-effort** for primary business flows. A metrics
storage or Prometheus update failure is logged and counted
(`raven_metrics_record_failures_total{source}`) but never causes the original
chat, log analysis, project expert, package search, title generation, upload, or
download operation to fail.

## 6. Privacy contract

The `metric_events` table and every export honor an **allowlist**:
`metadata_json` may only ever contain these keys — `tool_call_count`,
`trace_event_count`, `log_type`, `package_type`, `result_count`, `project_code`,
`error_kind`, `historical`. Everything else is dropped silently at sanitize
time. Metrics never persist or export prompts, assistant answers, raw tool
input/output, log content, credentialed headers, cookies, git tokens, or
token-bearing URLs. Project attribution is limited to non-sensitive identifiers
(e.g. `project_code`, `project_repo_id`), never a raw clone URL.
