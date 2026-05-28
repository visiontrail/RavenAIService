## Context

The current log system classifies every `LogRecord` using a hardcoded `LogType` enum with three values: `stack`, `oam_antenna`, `full`. This enum is baked into the DB schema (SQLAlchemy `Enum` column), the upload API, the list/filter API, the frontend UI, and the AI analysis pipeline. Adding a new project type today requires a code change + migration + deploy.

Meanwhile, the `project_repo` table (introduced by the `project-repo-registry` spec) already provides a dynamic, admin-managed registry of projects with `project_code`, `project_name`, and associated git repo info. The registry was designed for code-search during AI analysis, but it is the natural authority for "what projects exist."

Key stakeholders: the upload API (used by automated tooling and manual drag-drop), the log list UI, and the AI analysis pipeline.

## Goals / Non-Goals

**Goals:**
- Replace the static `log_type` enum with a dynamic FK to `project_repo`, so new project types need only an admin DB entry
- Maintain backwards-compatible inference: filenames containing known patterns (e.g. `stack`, `oam`, `full`) still auto-resolve to the correct project
- Provide a smooth migration path for existing data (backfill `project_id` from `log_type` values)
- Keep the upload API simple: callers can pass `project_code` (string) or `project_id` (int); if omitted, the system infers from filename

**Non-Goals:**
- Enforcing that every log MUST belong to a project (the FK is nullable to handle unknown/unrecognized logs)
- Changing the `project_repo` admin CRUD or git-related features
- Modifying the AI analysis agent's core logic (only updating how it receives project context)
- Supporting multi-project logs (one log → one project)

## Decisions

### 1. Nullable FK instead of required FK

Add `project_id: Optional[int]` as a nullable FK to `project_repo.id`. Nullable because:
- Legacy logs uploaded before a project existed should not break
- Automated uploads from unknown sources should still succeed (inference may fail)
- Alternative considered: required FK with a sentinel "unknown" project row — rejected because it adds a fake project to the registry and complicates queries

### 2. Accept both `project_code` and `project_id` on upload

The upload API will accept an optional `project_code` (string) or `project_id` (int). Resolution order:
1. If `project_id` is provided, use it directly (validate it exists and is enabled)
2. If `project_code` is provided, resolve via `project_repo_service.get_by_project_code()`
3. If neither is provided, infer from filename using the existing pattern-matching logic, but resolve to a `project_repo` record instead of an enum
4. If inference fails, leave `project_id` as NULL

Alternative considered: only accept `project_code` — rejected because `project_id` is more efficient for programmatic callers that already have it.

### 3. Seed a "full" project entry in migration

The existing migration already seeds `stack` and `oam_antenna` projects from legacy config. This change adds a `full` project entry (representing full/combined logs) so that existing `log_type=full` records can be backfilled.

### 4. Two-phase migration (add column → backfill → drop column)

Single Alembic migration with three steps:
1. `ADD COLUMN project_id INTEGER REFERENCES project_repo(id)` (nullable)
2. `UPDATE log_records SET project_id = (SELECT id FROM project_repo WHERE project_code = log_records.log_type)` for each known mapping
3. `DROP COLUMN log_type` and `DROP TYPE logtype` enum

Alternative considered: keep `log_type` column alongside `project_id` during a transition period — rejected because it creates dual-source-of-truth confusion and the system is not yet in wide production.

### 5. Frontend uses project-repos dropdown for filtering

Replace the hardcoded log-type select with a dynamic dropdown populated from `GET /api/v1/project-repos`. The dropdown shows `project_name` and filters by `project_id`. An "All" option shows all logs regardless of project.

### 6. Filename inference maps to project_code lookup

The current `_infer_log_type_from_filename()` returns an enum. The replacement `_infer_project_from_filename()` will:
1. Apply the same filename pattern matching
2. Map the result to a `project_code` string (e.g. `"stack"`, `"oam_antenna"`, `"full"`)
3. Look up the project via `project_repo_service.get_by_project_code()`
4. Return the `ProjectRepo` object or `None`

This keeps inference logic centralized and testable.

## Risks / Trade-offs

- **[Data loss on failed migration]** → The migration is additive first (add column, backfill) then destructive (drop column). If backfill fails, the old column still exists. Rollback: reverse migration re-adds the column and re-populates from `project_id`.
- **[API breaking change]** → Callers sending `log_type` in upload requests will get a validation error. → Mitigation: document the change; the API is internal and the only consumers are the frontend and the T04 upload script, both of which we control.
- **[Orphan project_id if project deleted]** → If an admin deletes a `project_repo` entry, logs referencing it have a dangling FK. → Mitigation: use `SET NULL` on delete (the FK constraint uses `ON DELETE SET NULL`), so logs become "unclassified" rather than failing.
- **[Performance]** → Adding a FK column and index on a modest-sized table is negligible. The JOIN to `project_repo` on list queries adds minimal overhead.

## Migration Plan

1. Create Alembic migration: add `project_id` column, seed "full" project, backfill, drop `log_type`
2. Update backend models, services, and API endpoints
3. Update frontend components and stores
4. Update AI analysis pipeline references
5. Update and run tests
6. Deploy backend first (migration runs), then frontend

Rollback: revert the Alembic migration (re-adds `log_type` column, re-populates from `project_id` mapping, drops `project_id`)

## Open Questions

- Should the T04 batch upload endpoint (`/api/v1/logs/upload-t04-batch`) auto-detect project from the zip structure, or require explicit `project_code`? Current proposal: keep auto-detection with fallback to explicit parameter.
