## MODIFIED Requirements

### Requirement: Agent owns metadata reading, repo lookup, and clone inside an isolated temporary workspace

The system SHALL allocate a per-task temporary directory under `settings.code_repo_clone_base_dir/<task_id>/`. The Python orchestrator SHALL NOT pre-clone the repository and SHALL NOT pre-resolve the repo URL; it SHALL write only a `task.json` with non-sensitive fields (`question`, `hints`, `log_id`, optional `log_type` hint) plus an empty `repo/` placeholder and the extracted `logs/` directory. The system prompt SHALL instruct the Agent to (1) `Read` the archived `metadata.json` to obtain `project_code` (and optionally `project_name`), (2) call the MCP tool `mcp__project_repo__lookup_project_repo` to resolve `clone_url`/`default_branch`, (3) `git clone` and checkout into `repo/` using the returned `clone_url`. The orchestrator MUST clean up the workspace on both success and failure paths.

**Change**: When materializing skills before the agent run, the system SHALL pass the resolved `project_code` (extracted from metadata or task context) to `materialize_relevant_enabled_skills()` via the new `project_code` parameter, so that project-level skills are included in the candidate pool alongside agent-level skills. If no `project_code` is available, the system SHALL pass `None` and only agent skills are loaded (backward-compatible).

#### Scenario: Workspace prepared without pre-resolved repo URL

- **WHEN** `workspace.prepare(log_record)` is called for a record with an archive
- **THEN** a fresh directory `<base>/<task_id>/` exists containing `task.json`, an empty `repo/` placeholder, and a populated `logs/` directory
- **AND** `task.json` does NOT contain `repo_url`, `clone_url`, or any git token
- **AND** the directory path is returned in the `WorkspaceContext`

#### Scenario: Agent reads metadata.json then calls lookup tool

- **WHEN** the agent loop begins for an archive whose `metadata.json` contains `project_info.project_code == "foo"`
- **THEN** the recorded `tool_trace` shows, in order: at least one `Read` (or `Glob`+`Read`) of `metadata.json`, followed by a `mcp__project_repo__lookup_project_repo` call with `{"project_code":"foo"}`
- **AND** a subsequent `Bash` tool use invokes `git clone` targeting `<workspace>/repo`

#### Scenario: Agent retries lookup with project_name on first not_found

- **WHEN** the first `lookup_project_repo` call returns `{"error":"not_found"}` and `metadata.json` contains a `project_name`
- **THEN** the Agent issues a second `lookup_project_repo` call using `project_name` as `project_code`
- **AND** if that also returns `not_found`, the run finishes with `status == "error"` and `error_kind == "project_repo_not_registered"` without attempting `git clone`

#### Scenario: Workspace removed after run

- **WHEN** the agent run completes — whether the result is `ok`, `schema_mismatch`, or `error`
- **THEN** the temporary workspace under `<base>/<task_id>/` no longer exists on disk

#### Scenario: Project skills loaded when project_code available

- **WHEN** `metadata.json` contains `project_info.project_code == "foo"` and project `"foo"` has enabled skills
- **THEN** `materialize_relevant_enabled_skills` is called with `project_code="foo"`
- **AND** the `loaded_skills` in the run result MAY include project-level skills from project `"foo"`

#### Scenario: No project_code falls back to agent-only skills

- **WHEN** `metadata.json` does not contain any project identity field
- **THEN** `materialize_relevant_enabled_skills` is called without `project_code` (or with `project_code=None`)
- **AND** only agent-level skills are considered for materialization
