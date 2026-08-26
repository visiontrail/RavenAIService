## Context

Raven stores AI-analysis state inside `LogRecord.metadata_json`. AI Chat results already include a `triggered_by` snapshot, and log detail can backfill some older AI Chat runs from `chat_agent_runs`, but the list conversion intentionally skips that enrichment. The standalone `POST /logs/{id}/analyze` path records task state without the authenticated user. The responsive list therefore has no consistent attribution value to render.

## Goals / Non-Goals

**Goals:**

- Return one normalized latest-trigger object on each log API record.
- Capture a bounded user snapshot at enqueue time for standalone analysis.
- Preserve that snapshot when the Celery result replaces the latest analysis result.
- Recover legacy AI Chat attribution where persisted run data permits it.
- Render useful desktop and mobile attribution states in both supported locales.

**Non-Goals:**

- Adding ownership or authorization semantics to log records.
- Requiring authentication for currently anonymous-compatible analysis endpoints.
- Adding a new database column or reconstructing identity when no durable evidence exists.
- Adding attribution-based filtering or sorting.

## Decisions

1. Add `ai_analysis_triggered_by` to `LogFileInfo` as the normalized presentation field. It retains the existing trigger structure (`source`, optional run/task identifiers, optional user snapshot, timestamps) and avoids making the frontend inspect result/task storage details.

2. Resolve the latest trigger with explicit precedence. While a standalone task is queued or running, its trigger snapshot wins over an older completed result. Otherwise the latest result trigger wins, followed by the task snapshot. This prevents a newly queued analysis from temporarily displaying the previous analyst.

3. Persist standalone attribution in `extra_fields.ai_analysis_task.triggered_by`. The current optional user is captured at enqueue time; no user object or credentials leave the request process. The synchronous Celery metadata writer copies this snapshot into a result that lacks its own trigger before persisting that result.

4. Reuse `chat_agent_runs` only as a best-effort compatibility fallback for AI Chat records that lack an embedded trigger. List enrichment is restricted to records with analysis evidence, avoiding lookups for ordinary uploaded logs. A missing/deleted user degrades to an ID-only snapshot or unavailable attribution.

5. Render the display name with `display_name -> username -> email -> id`. A trigger with no user identity is labelled as anonymous; a record without trigger evidence displays `-`. Mobile cards receive a labelled metadata item rather than a literal table column.

## Risks / Trade-offs

- [Legacy enrichment can add database queries for old AI Chat list rows] → Restrict fallback queries to analysis-bearing records and keep embedded snapshots authoritative for all new runs.
- [User profile details can change after analysis] → Treat attribution as an audit snapshot; legacy backfill uses the current profile only when no snapshot exists.
- [Anonymous and unavailable attribution can be confused] → Render anonymous only when a trigger exists with no identified user; render `-` when no trigger can be established.
- [Old standalone Celery runs cannot be attributed retroactively] → Preserve the unknown state rather than inventing an identity.

## Migration Plan

No schema migration is required. Deploy backend and frontend together; new standalone runs immediately persist snapshots and old AI Chat rows are enriched on read. Rollback consists of reverting the code; added JSON keys remain backward-compatible.

## Open Questions

None.
