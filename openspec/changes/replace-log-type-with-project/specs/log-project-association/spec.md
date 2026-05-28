## ADDED Requirements

### Requirement: LogRecord uses project_id FK instead of log_type enum

The `LogRecord` database model SHALL replace the `log_type` enum column with a nullable `project_id` integer column that is a foreign key to `project_repo.id` with `ON DELETE SET NULL`. The `LogType` enum class SHALL be removed from the codebase.

#### Scenario: New LogRecord has project_id column

- **WHEN** a new `LogRecord` is created with `project_id=3`
- **THEN** the record is persisted with `project_id=3` referencing the `project_repo` row
- **AND** the `log_type` column does not exist

#### Scenario: LogRecord with NULL project_id

- **WHEN** a new `LogRecord` is created without specifying `project_id`
- **THEN** the record is persisted with `project_id=NULL`
- **AND** the record is queryable and fully functional

#### Scenario: Referenced project is deleted

- **WHEN** a `project_repo` entry is deleted that is referenced by existing `LogRecord` rows
- **THEN** those `LogRecord` rows have `project_id` set to `NULL` (ON DELETE SET NULL)

### Requirement: Alembic migration backfills project_id from log_type and drops log_type

The system SHALL provide an Alembic migration that: (1) adds `project_id` nullable integer FK column to `log_records`, (2) ensures `project_repo` entries exist for `stack`, `oam_antenna`, and `full`, (3) backfills `project_id` by mapping each `log_type` value to the corresponding `project_repo.id`, (4) drops the `log_type` column, (5) drops the `logtype` PostgreSQL enum type.

#### Scenario: Migration on existing data

- **WHEN** the migration runs on a database with `log_records` containing `log_type='stack'` rows
- **THEN** those rows have `project_id` set to the `project_repo.id` where `project_code='stack'`
- **AND** the `log_type` column no longer exists
- **AND** the `logtype` enum type no longer exists

#### Scenario: Migration seeds "full" project if missing

- **WHEN** the migration runs and no `project_repo` entry exists with `project_code='full'`
- **THEN** a new entry is created with `project_code='full'`, `project_name='Full Log'`, `repo_url=''`, `enabled=true`

#### Scenario: Downgrade migration restores log_type

- **WHEN** the downgrade migration runs
- **THEN** the `log_type` enum column is re-added to `log_records`
- **AND** values are backfilled from `project_id` → `project_code` mapping

### Requirement: Upload API accepts project_code or project_id instead of log_type

The upload endpoints (`POST /api/v1/logs/upload`, `POST /api/v1/logs/upload-simple`) SHALL accept optional `project_code` (string) or `project_id` (integer) form fields instead of `log_type`. The `log_type` parameter SHALL be removed. Resolution order: (1) `project_id` if provided, validated against enabled entries; (2) `project_code` if provided, resolved via case-insensitive lookup; (3) inferred from filename patterns; (4) NULL if unresolvable.

#### Scenario: Upload with project_code

- **WHEN** a client uploads a file with `project_code="stack"`
- **THEN** the created `LogRecord` has `project_id` matching the `project_repo` entry with `project_code='stack'`

#### Scenario: Upload with project_id

- **WHEN** a client uploads a file with `project_id=5`
- **AND** `project_repo` id=5 exists and is enabled
- **THEN** the created `LogRecord` has `project_id=5`

#### Scenario: Upload with invalid project_id

- **WHEN** a client uploads a file with `project_id=999` and no such entry exists
- **THEN** the API returns HTTP 400 with an error message indicating the project was not found

#### Scenario: Upload with no project parameter infers from filename

- **WHEN** a client uploads a file named `stack_log_20240101.tar.gz` with no `project_code` or `project_id`
- **THEN** the system infers `project_code='stack'` from the filename
- **AND** the created `LogRecord` has `project_id` matching the `stack` project entry

#### Scenario: Upload with unrecognized filename and no project parameter

- **WHEN** a client uploads a file named `unknown_data.zip` with no `project_code` or `project_id`
- **THEN** the created `LogRecord` has `project_id=NULL`

### Requirement: T04 batch upload resolves project from filename or explicit parameter

The `POST /api/v1/logs/upload-t04-batch` endpoint SHALL resolve project association using the same logic as the single upload endpoint. Individual files within the batch MAY resolve to different projects based on their filenames. An optional `project_code` form field SHALL serve as the default for files whose project cannot be inferred.

#### Scenario: T04 batch with mixed file types

- **WHEN** a T04 batch zip contains files matching both `stack` and `oam_antenna` patterns
- **THEN** each resulting `LogRecord` has `project_id` matching its individually inferred project

#### Scenario: T04 batch with explicit default project_code

- **WHEN** a T04 batch upload includes `project_code="stack"` and contains files with unrecognizable names
- **THEN** unrecognizable files use the `stack` project as default
- **AND** recognizable files still use their inferred project

### Requirement: Log list API filters by project_id instead of log_type

The `GET /api/v1/logs` endpoint SHALL replace the `log_type` query parameter with `project_id` (integer, optional). When `project_id` is provided, only logs with that `project_id` are returned. A value of `project_id=0` or `project_id=none` SHALL return logs with `project_id IS NULL`.

#### Scenario: Filter by project_id

- **WHEN** a client requests `GET /api/v1/logs?project_id=3`
- **THEN** only `LogRecord` rows with `project_id=3` are returned

#### Scenario: Filter for unclassified logs

- **WHEN** a client requests `GET /api/v1/logs?project_id=0`
- **THEN** only `LogRecord` rows with `project_id IS NULL` are returned

#### Scenario: No project filter returns all logs

- **WHEN** a client requests `GET /api/v1/logs` without a `project_id` parameter
- **THEN** all non-deleted `LogRecord` rows are returned regardless of `project_id`

### Requirement: Log response includes project_code and project_name

The `LogFileInfo` Pydantic response model SHALL include `project_id` (optional int), `project_code` (optional string), and `project_name` (optional string) fields instead of `log_type`. These are populated by joining with `project_repo` when the log has a non-null `project_id`.

#### Scenario: Log with associated project

- **WHEN** the API returns a `LogFileInfo` for a log with `project_id=3` referencing project `{project_code: "stack", project_name: "Stack"}`
- **THEN** the response includes `project_id: 3`, `project_code: "stack"`, `project_name: "Stack"`
- **AND** the response does not include a `log_type` field

#### Scenario: Log without project

- **WHEN** the API returns a `LogFileInfo` for a log with `project_id=NULL`
- **THEN** the response includes `project_id: null`, `project_code: null`, `project_name: null`

### Requirement: Filename inference resolves to project_repo entry

The system SHALL provide a function `infer_project_from_filename(filename: str, db: Session) -> Optional[ProjectRepo]` that applies filename pattern matching (same rules as the former `_infer_log_type_from_filename`) and resolves the result to an enabled `project_repo` entry. If no match is found or the matched project_code has no enabled entry, it SHALL return `None`.

#### Scenario: Filename containing "stack"

- **WHEN** `infer_project_from_filename("stack_20240101.tar.gz", db)` is called
- **AND** an enabled `project_repo` entry with `project_code='stack'` exists
- **THEN** it returns that `ProjectRepo` object

#### Scenario: Filename matching no pattern

- **WHEN** `infer_project_from_filename("random_file.zip", db)` is called
- **THEN** it returns `None`

### Requirement: AI analysis pipeline uses project_id instead of log_type

The AI analysis task (`ai_analysis.py`), log processing task (`log_processing.py`), log analysis agent, and workspace context SHALL use `project_id` and resolve to `project_repo` data instead of referencing `LogType` enum values. The `_resolve_project_code_for_analysis()` function SHALL look up the project via `project_id` on the `LogRecord` rather than deriving it from `log_type`.

#### Scenario: AI analysis resolves project from log record

- **WHEN** an AI analysis task starts for a `LogRecord` with `project_id=3`
- **THEN** the analysis context includes the project's `project_code` and `project_name` from `project_repo`
- **AND** no `log_type` value is referenced

#### Scenario: AI analysis with NULL project_id

- **WHEN** an AI analysis task starts for a `LogRecord` with `project_id=NULL`
- **THEN** the analysis proceeds without project-specific context
- **AND** code search capabilities are unavailable (no repo URL)

### Requirement: Frontend displays and filters by project instead of log type

The frontend log list SHALL replace the hardcoded log-type dropdown with a dynamic project selector populated from `GET /api/v1/project-repos`. The log detail view SHALL display `project_name` instead of the log type label. The frontend type definitions and store SHALL use `project_id`/`project_code`/`project_name` instead of `log_type`.

#### Scenario: Log list shows project filter dropdown

- **WHEN** the log list page loads
- **THEN** a project filter dropdown is populated with all enabled projects from the API
- **AND** selecting a project filters the list to logs with that `project_id`

#### Scenario: Log detail shows project name

- **WHEN** a user views a log detail page for a log associated with project "Stack"
- **THEN** the detail view displays "Stack" as the project name where log type was previously shown

#### Scenario: Log list handles logs without project

- **WHEN** a log has `project_id=null`
- **THEN** the log list displays "Unclassified" or equivalent text for the project column
