## MODIFIED Requirements

### Requirement: Project repository registry persists project_code → repo URL mappings in DB

The system SHALL provide a `project_repo` database table (managed via alembic migration) with at minimum the columns: `id` (PK), `project_code` (unique, not null), `project_name` (not null), `repo_url` (not null), `default_branch` (not null, default `"main"`), `git_token` (nullable; per-repo override of the global `code_repo_git_token`), `description` (nullable), `enabled` (boolean, default true), `created_at`, `updated_at`.

The `repo_url` field SHALL allow empty string values to support project entries that are used solely for log categorization without an associated git repository.

#### Scenario: Migration creates the table

- **WHEN** the alembic migration runs against a fresh database
- **THEN** the `project_repo` table exists with all listed columns
- **AND** a unique index covers `project_code`

#### Scenario: Migration seeds from legacy settings

- **WHEN** the alembic migration runs and `settings.code_repo_oam_url` is non-empty
- **THEN** a row is inserted with `project_code == "oam_antenna"`, `project_name == "OAM Antenna"`, `repo_url == settings.code_repo_oam_url`
- **AND** the same applies to `code_repo_stack_url` with `project_code == "stack"`

#### Scenario: Migration seeds "full" project entry

- **WHEN** the log-type-to-project migration runs
- **THEN** a `project_repo` entry with `project_code='full'`, `project_name='Full Log'`, `repo_url=''` exists
- **AND** the entry has `enabled=true`

#### Scenario: Project entry without repo URL

- **WHEN** a project entry has `repo_url=''`
- **THEN** the entry is valid and usable for log categorization
- **AND** code search tools report "no repository configured" when the AI agent attempts repo-based operations

## ADDED Requirements

### Requirement: Admin cannot delete a project_repo entry that has associated logs without confirmation

The admin `DELETE /admin/project-repos/{id}` endpoint SHALL check if any `LogRecord` rows reference the project. If references exist, the endpoint SHALL return HTTP 409 with a count of affected logs and require a `force=true` query parameter to proceed. When forced, the deletion proceeds and affected logs have `project_id` set to NULL (via FK ON DELETE SET NULL).

#### Scenario: Delete project with associated logs without force

- **WHEN** an admin DELETEs a project_repo entry that is referenced by 15 log records
- **AND** the `force` parameter is not set or is `false`
- **THEN** the API returns HTTP 409 with `{"affected_logs": 15, "message": "Project has associated logs. Use force=true to delete."}`

#### Scenario: Force delete project with associated logs

- **WHEN** an admin DELETEs a project_repo entry with `force=true` that is referenced by 15 log records
- **THEN** the project_repo entry is deleted
- **AND** all 15 log records have `project_id` set to NULL
