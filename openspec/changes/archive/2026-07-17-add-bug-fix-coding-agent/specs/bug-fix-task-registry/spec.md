## ADDED Requirements

### Requirement: Bug fix task and merge request tables persist the repair workflow

The system SHALL provide two database tables (managed via alembic migration):

`bug_fix_task` with at minimum: `id` (PK), `project_repo_id` (FK → `project_repo.id`, not null), `source_log_id` (nullable), `source_analysis_task_id` (nullable), `title` (not null), `summary` (text), `proposed_fixes_json` (text), `status` (not null; one of `pending`/`running`/`succeeded`/`partial`/`failed`/`cancelled`), `error` (nullable), `celery_task_id` (nullable), `started_at` (nullable), `finished_at` (nullable), `created_at`, `updated_at`.

`bug_fix_merge_request` with at minimum: `id` (PK), `task_id` (FK → `bug_fix_task.id`, not null), `title` (not null), `description` (text), `branch_name` (not null), `base_branch` (not null), `mr_url` (nullable), `mr_iid` (nullable), `commit_sha` (nullable), `changed_files_json` (text), `diff_stat_json` (text), `status` (not null), `created_at`, `updated_at`.

A `bug_fix_task` SHALL have a one-to-many relationship to `bug_fix_merge_request`.

#### Scenario: Migration creates both tables

- **WHEN** the alembic migration runs against a fresh database
- **THEN** the `bug_fix_task` and `bug_fix_merge_request` tables exist with all listed columns
- **AND** `bug_fix_merge_request.task_id` references `bug_fix_task.id`

#### Scenario: Merge request rows never store tokens

- **WHEN** a `bug_fix_merge_request` row is written after a successful MR creation
- **THEN** the stored `mr_url` contains no embedded credentials

### Requirement: Completed log analysis dispatches a bug fix task when a code fix is required

When `run_ai_analysis_task` finishes writing a `completed` analysis result whose `requires_code_fix` is true and whose `proposed_fixes` is non-empty, and a repository was resolved (`repo_info` present), the system SHALL create a `bug_fix_task` (status `pending`) capturing the task title, summary, `proposed_fixes`, source log id, and source analysis task id, and SHALL enqueue the Bug Fix Coding Agent via a Celery task `run_bug_fix_task`. Dispatch SHALL be best-effort: any failure during task creation or enqueue SHALL be logged and SHALL NOT affect persistence of the analysis result itself.

#### Scenario: Code-fix signal triggers dispatch

- **WHEN** an analysis completes with `requires_code_fix: true`, a non-empty `proposed_fixes`, and a resolved repo
- **THEN** a `bug_fix_task` is created with status `pending` referencing the source log and analysis
- **AND** `run_bug_fix_task` is enqueued for that task

#### Scenario: No dispatch when no code fix is needed

- **WHEN** an analysis completes with `requires_code_fix: false` or an empty `proposed_fixes`
- **THEN** no `bug_fix_task` is created and no Bug Fix task is enqueued

#### Scenario: Dispatch failure does not break analysis result

- **WHEN** creating or enqueuing the bug fix task raises an exception
- **THEN** the analysis result remains persisted on the `LogRecord` and the error is logged

### Requirement: Bug fix task status reflects merge request outcomes

`run_bug_fix_task` SHALL move the task to `running` at start and to a terminal status at completion: `succeeded` when every attempted fix produced a Merge Request, `partial` when at least one but not all succeeded, and `failed` when no Merge Request was produced. Each produced Merge Request SHALL be persisted as a `bug_fix_merge_request` row regardless of the overall terminal status. The task `error` field SHALL capture a typed reason when the terminal status is `failed`.

#### Scenario: All fixes succeed

- **WHEN** the agent opens Merge Requests for all `proposed_fixes` items
- **THEN** the task status becomes `succeeded` and one `bug_fix_merge_request` row exists per Merge Request

#### Scenario: Some fixes fail

- **WHEN** the agent opens a Merge Request for one of two problems and fails on the other
- **THEN** the task status becomes `partial`, the successful Merge Request is persisted, and `error` describes the failed item

#### Scenario: No fix produced

- **WHEN** the agent produces no Merge Request
- **THEN** the task status becomes `failed` with a typed `error`
