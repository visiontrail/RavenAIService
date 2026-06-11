## ADDED Requirements

### Requirement: Project repository registry persists project_code → repo URL mappings in DB

The system SHALL provide a `project_repo` database table (managed via alembic migration) with at minimum the columns: `id` (PK), `project_code` (unique, not null), `project_name` (not null), `repo_url` (not null, but MAY be an empty string for entries used only for log classification with no associated Git repository), `default_branch` (not null, default `"main"`), `git_token` (nullable; per-repo override of the global `code_repo_git_token`), `description` (nullable), `enabled` (boolean, default true), `created_at`, `updated_at`.

#### Scenario: Migration creates the table

- **WHEN** the alembic migration runs against a fresh database
- **THEN** the `project_repo` table exists with all listed columns
- **AND** a unique index covers `project_code`

#### Scenario: Migration seeds from legacy settings

- **WHEN** the alembic migration runs and `settings.code_repo_oam_url` is non-empty
- **THEN** a row is inserted with `project_code == "oam_antenna"`, `project_name == "OAM Antenna"`, `repo_url == settings.code_repo_oam_url`
- **AND** the same applies to `code_repo_stack_url` with `project_code == "stack"`

#### Scenario: Migration seeds the "full" project entry

- **WHEN** the log-type-to-project migration runs
- **THEN** a `project_repo` entry exists with `project_code == "full"`, `project_name == "Full Log"`, `repo_url == ""`
- **AND** that entry has `enabled == true`

#### Scenario: Project entry without a repo URL

- **WHEN** a project entry has `repo_url == ""`
- **THEN** the entry is valid and usable for log classification
- **AND** code-search tools report "no repository configured" if the AI Agent attempts repo-based operations on it

### Requirement: Admin cannot delete project_repo entries with associated logs without confirmation

The admin `DELETE /admin/project-repos/{id}` endpoint SHALL check whether any `LogRecord` rows reference the project. If references exist, the endpoint SHALL return HTTP 409 with the count of affected logs, and SHALL require the `force=true` query parameter to proceed. When force-deleted, the deletion proceeds and affected logs' `project_id` is set to NULL (via the `ON DELETE SET NULL` foreign key).

#### Scenario: Delete a project with associated logs without force

- **WHEN** an admin deletes a `project_repo` entry referenced by 15 `LogRecord` rows
- **AND** the `force` parameter is unset or `false`
- **THEN** the API returns HTTP 409 with body `{"affected_logs": 15, "message": "该项目有关联的日志记录。使用 force=true 进行删除。"}`

#### Scenario: Force-delete a project with associated logs

- **WHEN** an admin deletes a `project_repo` entry referenced by 15 `LogRecord` rows with `force=true`
- **THEN** the `project_repo` entry is deleted
- **AND** all 15 `LogRecord` rows have `project_id` set to NULL

### Requirement: Admin endpoints provide CRUD and connectivity testing

The system SHALL expose under the existing `/admin` router: `GET /admin/project-repos` (list, paginated), `POST /admin/project-repos` (create), `GET /admin/project-repos/{id}` (read), `PUT /admin/project-repos/{id}` (update), `DELETE /admin/project-repos/{id}` (delete), and `POST /admin/project-repos/{id}/test-connection` (run `git ls-remote`-based check, returning `{success, message, auth_method}`). Endpoints SHALL require admin auth using the existing `app/admin_auth.yaml` mechanism. Responses SHALL never include the raw `git_token`; instead they SHALL return a boolean `git_token_set` and accept the literal placeholder `••••••••` on update to mean "do not change".

#### Scenario: Create a project repo entry

- **WHEN** an authenticated admin POSTs `{project_code:"foo", project_name:"Foo", repo_url:"https://gitlab.example/foo.git"}`
- **THEN** the response is `201` and the row exists with `enabled == true`, `default_branch == "main"`, `git_token == None`

#### Scenario: Update with masked token is no-op for token

- **WHEN** an admin PUTs `{git_token: "••••••••", project_name: "Foo Renamed"}` on an entry that already has a stored token
- **THEN** the row's `project_name` is updated and `git_token` is unchanged
- **AND** the response includes `git_token_set: true` and no plaintext token

#### Scenario: Delete unused entry

- **WHEN** an admin DELETEs an entry whose `project_code` has not been used in any in-flight log analysis
- **THEN** the row is removed and the API returns `204`

#### Scenario: Test connection returns structured result

- **WHEN** `POST /admin/project-repos/{id}/test-connection` runs against a reachable repo
- **THEN** the response body is `{success: true, message: "...", auth_method: "token_in_url"|"anonymous"|"ssh_key"}`

### Requirement: Lookup-by-project-code is case-insensitive and trims whitespace

The system SHALL provide `project_repo_service.get_by_project_code(code: str)` that normalizes the input via `.strip().lower()` before matching, and SHALL apply the same normalization to `project_code` on insert/update so that `"Foo "`, `"foo"`, and `"FOO"` resolve to the same entry.

#### Scenario: Case-insensitive lookup

- **WHEN** an entry was inserted with `project_code == "FOO"` and a caller invokes `get_by_project_code("  foo  ")`
- **THEN** the entry is returned

#### Scenario: Disabled entry not returned

- **WHEN** an entry exists with `enabled == false` and a caller invokes `get_by_project_code("foo")`
- **THEN** the function returns `None`

### Requirement: Lookup is exposed to the log analysis Agent as an in-process MCP tool

The system SHALL register a Claude Agent SDK in-process MCP server named `project_repo` exposing exactly one tool `lookup_project_repo` with input schema `{project_code: string, project_name?: string}` and a JSON text response containing at minimum `project_code`, `project_name`, `repo_url` (token-masked, for display), `clone_url` (token-injected, for the Agent to actually `git clone`), `default_branch`, `auth_required`. When no enabled entry matches, the tool SHALL return `{"error": "not_found", "project_code": "<normalized>"}`. The log analysis Agent's `allowed_tools` SHALL include `mcp__project_repo__lookup_project_repo`.

#### Scenario: Tool resolves a registered project

- **WHEN** the Agent calls `mcp__project_repo__lookup_project_repo` with `{project_code:"foo"}` and an enabled entry exists
- **THEN** the tool returns a JSON text with `repo_url` masked (no token), `clone_url` containing the global or per-repo token, `default_branch`, and `auth_required: true|false`
- **AND** `tool_trace` records the call but masks `clone_url` before persistence

#### Scenario: Tool returns not_found for unknown project_code

- **WHEN** the Agent calls the tool with `{project_code: "unknown"}` and no entry exists
- **THEN** the tool returns `{"error":"not_found","project_code":"unknown"}` and the run continues so the Agent may retry with `project_name`

#### Scenario: Other agents do not get the tool by default

- **WHEN** an unrelated agent (e.g., a future migrated chat agent) builds options without explicitly requesting the registry MCP server
- **THEN** the resulting `ClaudeAgentOptions.mcp_servers` does not include `project_repo`

### Requirement: Plaintext tokens never reach tool_trace or persistent logs

The system SHALL apply token redaction (`https://[^@]+@` → `https://***@`) to all `tool_trace.output_excerpt` and `tool_trace.input` entries before they are persisted to `LogRecord.ai_analysis_result`, and SHALL apply the same redaction to any structured logs emitted from `LogAnalysisAgent` or `project_repo_service`.

#### Scenario: Clone URL is masked in tool_trace

- **WHEN** the Agent calls `lookup_project_repo` and subsequently `git clone https://oauth2:secret@host/foo.git repo`
- **THEN** `LogRecord.ai_analysis_result.tool_trace[*].input` for the Bash call shows `https://***@host/foo.git`
- **AND** the lookup tool's response in `tool_trace[*].output_excerpt` shows `clone_url: "https://***@host/foo.git"`

### Requirement: Legacy OAM/Stack repo settings remain readable but become deprecated

The system SHALL keep `GET /admin/repo-settings` returning the existing payload shape (so the old frontend page does not break) for one release cycle. The fields `oam_url` and `stack_url` SHALL be additionally annotated as `deprecated: true` in the response. `PUT /admin/repo-settings` SHALL still accept updates to `git_token` and `clone_depth` (which remain global) but SHALL ignore writes to `oam_url`/`stack_url`, returning a `200` with a top-level warning message instructing admins to use `/admin/project-repos`.

#### Scenario: Legacy GET still works

- **WHEN** a frontend client without project-repo support calls `GET /admin/repo-settings`
- **THEN** the response is `200` with the existing fields plus `deprecated: true` markers on `oam_url` and `stack_url`

#### Scenario: Legacy PUT ignores deprecated fields

- **WHEN** a client calls `PUT /admin/repo-settings` with both `git_token: "tok"` and `oam_url: "https://new.example/o.git"`
- **THEN** the global `code_repo_git_token` is updated, no `project_repo` row is mutated, and the response includes `warnings: ["oam_url/stack_url ignored; use /admin/project-repos"]`
