## ADDED Requirements

### Requirement: Metrics events are persisted as an auditable fact source

The system SHALL persist metrics events for AI usage and selected business activities in a database-backed event table. Each persisted event MUST include `event_type`, `source`, `occurred_at`, and an `idempotency_key`. AI usage events MUST additionally include `status`, token counters, and enough non-sensitive ownership fields to aggregate by system and by user.

The system MUST normalize missing token counters to `0` and MUST compute `total_tokens` from `input_tokens`, `output_tokens`, `cache_read_tokens`, and `cache_write_tokens`.

#### Scenario: AI usage event is recorded at run terminal state

- **WHEN** a chat Agent run reaches a terminal state
- **THEN** the system MUST write one `metric_events` row with `event_type == "ai_usage"`
- **AND** the row MUST include `source`, `agent_kind`, `provider`, `model`, `status`, `user_id` when authenticated, `owner_scope`, `session_id`, `run_id`, token counters, and duration when available

#### Scenario: Duplicate idempotency key does not double count

- **WHEN** the same AI run terminal persistence path attempts to record metrics twice with the same `idempotency_key`
- **THEN** the system MUST keep only one persisted metrics event for that key
- **AND** token totals returned by metrics APIs MUST NOT increase on the duplicate attempt

#### Scenario: Missing SDK usage is represented safely

- **WHEN** an AI invocation completes but the SDK messages contain no usage object
- **THEN** the system MUST still record the invocation event
- **AND** all token counters MUST be `0`
- **AND** the event MUST remain queryable by source, status, provider, and model

### Requirement: Token usage is captured for every backend AI entry point

The system SHALL capture Token usage for all backend AI entry points that call the Claude Agent SDK or compatible provider API. This MUST cover at least `general_agent`, `device_agent`, `log_analysis_agent`, `project_expert_agent`, `package_search_agent`, and `title_generator`.

For Agent runs with existing `ChatAgentRun` or task identifiers, metrics MUST be recorded when the service persists the terminal result. Agents SHALL expose or return token usage in their terminal result or terminal event so the service layer can record it with correct user/session ownership.

#### Scenario: Chat run records user-scoped Token usage

- **WHEN** an authenticated user completes a `general_agent` or `device_agent` chat run
- **THEN** the system MUST record an `ai_usage` event linked to that user's `user_id`
- **AND** the event MUST include `session_id`, `run_id`, `agent_kind`, `model`, `status`, and token counters

#### Scenario: Log analysis records task-scoped Token usage

- **WHEN** a log analysis Agent task completes, fails, is cancelled, or becomes stale with a terminal result
- **THEN** the system MUST record an `ai_usage` event with `source == "log_analysis_agent"`
- **AND** the event MUST include `task_id` or `run_id` when available, `log_id` when available, terminal `status`, `model`, and token counters from the analysis result

#### Scenario: Project expert records project-scoped Token usage

- **WHEN** a Project Expert chat job reaches terminal state
- **THEN** the system MUST record an `ai_usage` event with `source == "project_expert_agent"`
- **AND** the event MUST include the authenticated `user_id`, `session_id`, `run_id`, `project_repo_id` when available, `model`, `status`, and token counters

#### Scenario: Package search records search Token usage

- **WHEN** `/api/packages/agent-search` or `/raven/api/packages/agent-search` completes in non-streaming or streaming mode
- **THEN** the system MUST record an `ai_usage` event with `source == "package_search_agent"`
- **AND** the event MUST include `session_id` when provided, `model`, `status`, returned `usage`, and result counts in sanitized metadata

#### Scenario: Title generation records small-model Token usage

- **WHEN** the title generator completes an SDK-backed title or summary request
- **THEN** the system MUST record an `ai_usage` event with `source == "title_generator"`
- **AND** the event MUST include `model`, `status`, token counters, and `user_id/session_id` when the caller supplied them

### Requirement: Admin system metrics API provides system-level overview

The system SHALL expose admin-authenticated metrics APIs under `/admin/metrics`. The overview API MUST aggregate metrics over a requested time range and bucket size, returning system-level Token totals, AI invocation counts, success and failure counts, error counts, duration summaries, active user counts, and selected business-domain summaries.

The API MUST require the existing admin bearer authentication.

#### Scenario: Admin reads system overview

- **WHEN** an authenticated admin calls `GET /admin/metrics/overview?from=<start>&to=<end>&bucket=day`
- **THEN** the response MUST include total `input_tokens`, `output_tokens`, `cache_read_tokens`, `cache_write_tokens`, and `total_tokens`
- **AND** the response MUST include AI invocation totals grouped by `source`, `agent_kind`, `provider`, `model`, and `status`
- **AND** the response MUST include a time series using the requested bucket

#### Scenario: Non-admin cannot read system overview

- **WHEN** a request without a valid admin bearer token calls any `/admin/metrics/*` endpoint
- **THEN** the system MUST return HTTP 401 or HTTP 403
- **AND** it MUST NOT return any metrics payload

#### Scenario: Time range filters are applied

- **WHEN** an admin requests an overview with `from` and `to`
- **THEN** only metrics with `occurred_at` inside that inclusive-exclusive range MUST contribute to totals and time series

### Requirement: Admin user metrics API provides per-user Token and activity statistics

The system SHALL expose admin APIs that aggregate metrics by user. User list statistics MUST include Token totals, AI run counts, status counts, message counts, last active time, and top Agent/source distribution for each user in the requested time range.

#### Scenario: Admin lists users by Token usage

- **WHEN** an authenticated admin calls `GET /admin/metrics/users?from=<start>&to=<end>&sort=total_tokens`
- **THEN** the response MUST include one row per matching user
- **AND** each row MUST include `user_id`, `username`, `display_name`, `role`, `total_tokens`, token breakdown, AI invocation counts, status counts, `message_count`, and `last_active_at`
- **AND** rows MUST be sorted by the requested metric

#### Scenario: Admin reads one user's metrics detail

- **WHEN** an authenticated admin calls `GET /admin/metrics/users/{user_id}?from=<start>&to=<end>&bucket=day`
- **THEN** the response MUST include only that user's metrics
- **AND** the response MUST include Token time series, source/model/provider distribution, status/error distribution, and recent sanitized AI usage events

#### Scenario: Unknown user returns not found

- **WHEN** an authenticated admin requests metrics for a `user_id` that does not exist
- **THEN** the system MUST return HTTP 404

### Requirement: Users can read only their own metrics summary

The system SHALL expose a user-authenticated self metrics endpoint under `/api/v1/users/me/metrics`. This endpoint MUST return only the current user's Token and AI activity summary, and MUST NOT accept a user_id parameter that allows reading another user's data.

#### Scenario: User reads own metrics

- **WHEN** an authenticated user calls `GET /api/v1/users/me/metrics?from=<start>&to=<end>&bucket=day`
- **THEN** the response MUST include that user's Token totals, AI invocation counts, status counts, and time series
- **AND** all returned metric events and aggregates MUST have `user_id` equal to the current user

#### Scenario: User cannot read another user's metrics

- **WHEN** user A calls the self metrics endpoint
- **AND** user B has higher Token usage in the same time range
- **THEN** the response MUST NOT include user B's `user_id`, username, events, totals, or inferred activity

### Requirement: Raw metric events are available for admin audit

The system SHALL expose an admin-authenticated raw event query API. The API MUST support filters for time range, `event_type`, `source`, `user_id`, `status`, and pagination. Raw event responses MUST use sanitized metadata and MUST NOT include sensitive text fields.

#### Scenario: Admin queries raw AI usage events

- **WHEN** an authenticated admin calls `GET /admin/metrics/events?event_type=ai_usage&source=device_agent&page=1&per_page=20`
- **THEN** the response MUST include at most 20 matching events
- **AND** each event MUST include token counters, source, status, model, occurred time, and ownership identifiers allowed for admin audit
- **AND** each event MUST omit prompt text, assistant answer text, tool input, tool output, and secrets

#### Scenario: Pagination bounds are enforced

- **WHEN** an admin requests `per_page` larger than the configured maximum
- **THEN** the system MUST cap or reject the request
- **AND** the response MUST NOT return more than the maximum allowed number of events

### Requirement: Business-domain metrics summarize current system activity

The system SHALL include non-Token business metrics in admin system overview responses using existing domain data and newly recorded business events. At minimum, the overview MUST include user/chat activity, log upload and AI analysis activity, package inventory and package activity, and device connection summary.

#### Scenario: Overview includes chat and user activity

- **WHEN** an admin reads the system overview
- **THEN** the response MUST include total users, active users in range, chat session count, chat message count, and chat Agent run counts by status

#### Scenario: Overview includes log activity

- **WHEN** an admin reads the system overview
- **THEN** the response MUST include log upload count, uploaded bytes, counts by `log_type`, counts by processing status, and AI analysis terminal counts when available

#### Scenario: Overview includes package activity

- **WHEN** an admin reads the system overview
- **THEN** the response MUST include Raven package count, package total bytes, package type distribution, package upload/download activity when recorded, and package search AI usage counts

#### Scenario: Overview includes device activity

- **WHEN** an admin reads the system overview
- **THEN** the response MUST include current device connection counts by state when available
- **AND** DeviceAgent invocation and Token usage MUST be included in AI metrics groups

### Requirement: Prometheus metrics expose low-cardinality system signals

The system SHALL continue to expose `GET /metrics` in Prometheus text format when `prometheus_client` is available. New Prometheus metrics MUST use low-cardinality labels only and MUST NOT include user, session, run, task, log, package, or project identifiers as labels.

#### Scenario: Prometheus output includes AI Token counters

- **WHEN** an AI usage event is recorded
- **AND** Prometheus support is available
- **THEN** `GET /metrics` MUST include AI Token counter samples grouped by low-cardinality labels such as `source`, `agent_kind`, `provider`, `model`, and `token_type`

#### Scenario: Prometheus labels exclude user and run identifiers

- **WHEN** `/metrics` is rendered after user-owned AI runs
- **THEN** no sample label set MUST contain `user_id`, `username`, `owner_scope`, `session_id`, `run_id`, `task_id`, `log_id`, or `project_repo_id`

#### Scenario: Metrics endpoint fallback remains explicit

- **WHEN** `prometheus_client` is unavailable
- **THEN** `GET /metrics` MUST continue to return HTTP 503 with an explicit text message

### Requirement: Sensitive data is excluded from persisted and exported metrics

The system SHALL sanitize metrics metadata using an allowlist. Metrics MUST NOT persist or export prompts, assistant answers, raw tool input/output, log content, request headers containing credentials, cookies, git tokens, token-injected URLs, or arbitrary free-form payloads.

#### Scenario: Prompt and answer are not stored

- **WHEN** a user sends a chat message and the Agent produces an answer
- **THEN** the persisted metrics event MUST NOT contain the user message text
- **AND** it MUST NOT contain the assistant answer text

#### Scenario: Token-bearing URL is not stored

- **WHEN** an Agent run uses a project repo clone URL containing credentials
- **THEN** the metrics event metadata MUST NOT contain the raw clone URL
- **AND** any project metadata retained for metrics MUST be limited to non-sensitive identifiers such as project code or project id

### Requirement: Optional cost estimates are configuration driven

The system SHALL support optional cost estimates for AI usage. Cost estimates MUST be computed only from configured provider/model/token-type pricing. When pricing is absent, the system MUST return Token counts with `cost_microusd == null` or equivalent API `estimated_cost_usd == null`.

#### Scenario: Configured pricing produces estimated cost

- **WHEN** pricing is configured for the event provider, model, and token types
- **AND** an AI usage event is recorded with non-zero Token counters
- **THEN** the persisted event MUST include a non-null estimated cost field
- **AND** metrics APIs MUST expose that value as an estimate

#### Scenario: Missing pricing does not block metrics

- **WHEN** no pricing is configured for the event provider or model
- **AND** an AI usage event is recorded
- **THEN** the event MUST still be persisted with Token counters
- **AND** the cost estimate MUST be null

### Requirement: Metrics recording failure does not break primary workflows

The system SHALL treat metrics recording as best-effort for primary business flows. A metrics storage or Prometheus update failure MUST be logged and counted, but MUST NOT cause the original chat, log analysis, project expert, package search, title generation, upload, or download operation to fail.

#### Scenario: Metrics database insert fails during chat completion

- **WHEN** a chat Agent run completes successfully
- **AND** metrics event insertion raises an exception
- **THEN** the chat run MUST still persist its terminal business result
- **AND** the user-facing response or SSE terminal event MUST still be delivered
- **AND** the system MUST log the metrics failure

#### Scenario: Metrics failure counter increments

- **WHEN** metrics recording fails for a source
- **THEN** the system MUST increment a low-cardinality Prometheus failure counter or equivalent internal counter for that source

### Requirement: Admin console provides a metrics dashboard page

The admin web console SHALL provide a dedicated Metrics dashboard page that consumes the admin metrics APIs (`/admin/metrics/overview`, `/admin/metrics/users`, `/admin/metrics/users/{user_id}`, `/admin/metrics/events`). The page MUST reuse the existing admin bearer authentication and admin navigation shell, and MUST expose the shared time-range and bucket controls so an admin can scope the displayed metrics.

#### Scenario: Admin views the system overview on the dashboard

- **WHEN** an authenticated admin opens the Metrics dashboard page
- **THEN** the page MUST display the system Token totals, invocation count, status breakdown, and estimated cost (or an explicit "no pricing configured" indication) for the selected time range
- **AND** the page MUST render the per-bucket time series and the business activity summaries (chat, logs, packages, devices)

#### Scenario: Admin inspects per-user usage from the dashboard

- **WHEN** an admin selects a user from the per-user ranking table
- **THEN** the page MUST request that user's detail and display their Token series, distributions, status/error groups, and recent sanitized events
- **AND** the page MUST NOT display prompt text, assistant answers, tool input/output, or secrets

#### Scenario: Dashboard reflects the selected time range and bucket

- **WHEN** an admin changes the time range or bucket control
- **THEN** the page MUST re-query the metrics APIs with the corresponding `from`, `to`, and `bucket` parameters
- **AND** the displayed aggregates and time series MUST update to match the selected window
