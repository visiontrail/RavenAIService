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

The system SHALL expose under the existing `/admin` router: `GET /admin/project-repos` (list, paginated), `POST /admin/project-repos` (create), `GET /admin/project-repos/{id}` (read), `PUT /admin/project-repos/{id}` (update), `DELETE /admin/project-repos/{id}` (delete), and `POST /admin/project-repos/{id}/test-connection` (run `git ls-remote`-based check, returning `{success, message, auth_method}`).

Global admins SHALL retain full CRUD and connectivity-test access using the existing admin authorization behavior. Project-member admins SHALL be authorized only for `GET /admin/project-repos`, `GET /admin/project-repos/{id}`, `PUT /admin/project-repos/{id}`, and `POST /admin/project-repos/{id}/test-connection` on enabled projects where they are members. Project-member admin list responses SHALL include only their member projects. Project-member admin update requests SHALL accept only `project_name`, `description`, `repo_url`, and `default_branch`; changes to `enabled`, `git_token`, members, creation, and deletion SHALL require global admin access. Responses SHALL never include the raw `git_token`; instead they SHALL return a boolean `git_token_set` and accept the literal placeholder `••••••••` on global-admin update to mean "do not change".

#### Scenario: Create a project repo entry

- **WHEN** an authenticated global admin POSTs `{project_code:"foo", project_name:"Foo", repo_url:"https://gitlab.example/foo.git"}`
- **THEN** the response is `201` and the row exists with `enabled == true`, `default_branch == "main"`, `git_token == None`

#### Scenario: Update with masked token is no-op for token

- **WHEN** a global admin PUTs `{git_token: "••••••••", project_name: "Foo Renamed"}` on an entry that already has a stored token
- **THEN** the row's `project_name` is updated and `git_token` is unchanged
- **AND** the response includes `git_token_set: true` and no plaintext token

#### Scenario: Delete unused entry

- **WHEN** a global admin DELETEs an entry whose `project_code` has not been used in any in-flight log analysis
- **THEN** the row is removed and the API returns `204`

#### Scenario: Test connection returns structured result

- **WHEN** `POST /admin/project-repos/{id}/test-connection` runs against a reachable repo for an authorized global admin or project-member admin
- **THEN** the response body is `{success: true, message: "...", auth_method: "token_in_url"|"anonymous"|"ssh_key"}`
- **AND** the response does not include a raw git token

#### Scenario: Project-member admin lists only member projects

- **WHEN** a project-member admin belongs to project A but not project B
- **AND** the user calls `GET /admin/project-repos`
- **THEN** the response has status 200
- **AND** the response contains project A
- **AND** the response does not contain project B

#### Scenario: Project-member admin reads member project

- **WHEN** a project-member admin calls `GET /admin/project-repos/{id}` for a project they belong to
- **THEN** the response has status 200 with that project data
- **AND** the response does not include a raw git token

#### Scenario: Project-member admin cannot read non-member project

- **WHEN** a project-member admin calls `GET /admin/project-repos/{id}` for an enabled project they do not belong to
- **THEN** the response has status 404

#### Scenario: Project-member admin updates allowed project fields

- **WHEN** a project-member admin PUTs `{project_name:"New Name", description:"Updated", repo_url:"https://gitlab.example/new.git", default_branch:"develop"}` to a project they belong to
- **THEN** the response has status 200
- **AND** those fields are updated

#### Scenario: Project-member admin cannot update restricted project fields

- **WHEN** a project-member admin PUTs a payload containing `enabled` or `git_token` for a project they belong to
- **THEN** the response has status 403 or 422
- **AND** the restricted fields are not changed

#### Scenario: Project-member admin cannot create or delete projects

- **WHEN** a project-member admin calls `POST /admin/project-repos` or `DELETE /admin/project-repos/{id}`
- **THEN** the response has status 403

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

### Requirement: Project repo admin responses expose a member summary

The existing `/admin/project-repos` list and read responses SHALL include a `member_count` field reporting how many registered users are members of each project repository. This field SHALL be derived from the `project_repo_member` table and SHALL never expose member credentials. The existing fields (including `git_token_set`) and token-masking behavior SHALL remain unchanged.

#### Scenario: List response includes member count

- **WHEN** an authenticated admin calls `GET /admin/project-repos`
- **THEN** each entry includes a `member_count` equal to the number of `project_repo_member` rows for that repo
- **AND** no plaintext git token appears in the response

#### Scenario: Read response includes member count

- **WHEN** an admin calls `GET /admin/project-repos/{id}`
- **THEN** the response includes `member_count` for that repository


### Requirement: Every project has a required project card
`ProjectRepo` SHALL store a trimmed, non-empty `project_card` text value. Admin create requests MUST include a project card, explicit updates MUST reject a blank card, and admin/public project responses SHALL return `project_card` instead of the optional `description` field. The card SHALL describe enough project scope and boundaries for users and Agents to decide whether a question belongs to the project.

#### Scenario: Create rejects a missing project card
- **WHEN** an administrator creates a project without `project_card` or with whitespace only
- **THEN** the API returns a validation error
- **AND** no project row is created

#### Scenario: Project card is normalized and returned
- **WHEN** an administrator creates a project with a non-empty project card surrounded by whitespace
- **THEN** the stored value is trimmed
- **AND** both admin and public project responses return the trimmed `project_card`

#### Scenario: Update cannot clear the card
- **WHEN** an authorized administrator updates an existing project with an empty or whitespace-only `project_card`
- **THEN** the API rejects the update
- **AND** the existing project card remains unchanged

### Requirement: Legacy descriptions migrate without nullable cards
The database migration SHALL preserve each non-blank `description` value as `project_card`, SHALL backfill a clearly marked scope-incomplete card for every blank legacy row, SHALL rename the column to `project_card`, and SHALL enforce non-null/non-blank writes. PostgreSQL SHALL use `NOT NULL`; SQLite SHALL use an in-place rename plus INSERT/UPDATE triggers so referenced project rows are not cascade-deleted during a table rebuild. Downgrade SHALL retain the text while renaming the column back to nullable `description`.

#### Scenario: Existing description is preserved
- **WHEN** the migration runs for a project whose description is `Satellite telemetry ingestion`
- **THEN** its `project_card` equals `Satellite telemetry ingestion`
- **AND** the row has no `description` column after upgrade

#### Scenario: Blank legacy description receives fallback
- **WHEN** the migration runs for a project with a null or whitespace-only description
- **THEN** its `project_card` is non-empty and identifies the project name/code
- **AND** the card explicitly indicates that the project scope still needs completion

#### Scenario: SQLite upgrade preserves project references
- **WHEN** the migration or runtime schema sync upgrades a SQLite project row referenced by Agent/member/log tables with foreign keys enabled
- **THEN** all referencing rows remain present and continue to reference the same project id
- **AND** subsequent null or blank project-card inserts/updates are rejected by database triggers

### Requirement: Project-level system prompt endpoints are project-scoped
The system SHALL expose project-level system prompt read and update endpoints under `/admin/project-repos/{project_code}/system-prompt`. These endpoints SHALL admit global admins for any valid project code and project-member admins only when the normalized project code maps to an enabled project where the current user is a member. Project-member admins SHALL receive 404 for non-member, disabled, or unknown project codes. The prompt content SHALL remain constrained by existing project prompt validation.

#### Scenario: Project-member admin reads own project system prompt
- **WHEN** a project-member admin calls `GET /admin/project-repos/alpha/system-prompt` for a project they belong to
- **THEN** the response has status 200
- **AND** the response includes that project's prompt content metadata

#### Scenario: Project-member admin updates own project system prompt
- **WHEN** a project-member admin calls `PUT /admin/project-repos/alpha/system-prompt` with valid `content` for a project they belong to
- **THEN** the response has status 200
- **AND** subsequent reads return the updated content

#### Scenario: Project-member admin cannot access another project's system prompt
- **WHEN** a project-member admin calls `GET` or `PUT` on `/admin/project-repos/beta/system-prompt` for a project they do not belong to
- **THEN** the response has status 404

#### Scenario: Global admin can manage any valid project system prompt
- **WHEN** a global admin calls `GET` or `PUT` on `/admin/project-repos/beta/system-prompt`
- **THEN** the request is authorized according to the existing project prompt validation rules
