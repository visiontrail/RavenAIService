## ADDED Requirements

### Requirement: Log analysis runs on Claude Agent SDK and the legacy LangGraph implementation is removed

The system SHALL implement the log analysis feature exclusively via the Claude Agent SDK `query()` agent loop. The legacy LangGraph modules (`app/agents/log_agent.py`, `app/agents/code_analysis_graph.py`, `app/agents/xml_utils.py`) and their entry points MUST be removed from the codebase, and `app/tasks/ai_analysis.py::run_ai_analysis_task` MUST NOT import or reference them.

#### Scenario: No legacy imports remain

- **WHEN** the repository is searched after this change is applied
- **THEN** there are zero Python imports of `app.agents.log_agent`, `app.agents.code_analysis_graph`, or `app.agents.xml_utils`
- **AND** `requirements.txt` no longer pins `langgraph`, `langchain`, `langchain-community`, or `langchain-openai`

#### Scenario: Celery task dispatches to the new agent

- **WHEN** `run_ai_analysis_task(log_id)` executes for a log record with valid repo metadata and archive
- **THEN** it invokes the new Claude Agent SDK-based agent and writes `engine == "claude-agent-sdk"` into `LogRecord.ai_analysis_result`

### Requirement: Agent owns metadata reading, repo lookup, and clone inside an isolated temporary workspace

The system SHALL allocate a per-task temporary directory under `settings.code_repo_clone_base_dir/<task_id>/`. The Python orchestrator SHALL NOT pre-clone the repository and SHALL NOT pre-resolve the repo URL; it SHALL write only a `task.json` with non-sensitive fields (`question`, `hints`, `log_id`, optional `log_type` hint) plus an empty `repo/` placeholder and the extracted `logs/` directory. The system prompt SHALL instruct the Agent to (1) `Read` the archived `metadata.json` to obtain `project_code` (and optionally `project_name`), (2) call the MCP tool `mcp__project_repo__lookup_project_repo` to resolve `clone_url`/`default_branch`, (3) `git clone` and checkout into `repo/` using the returned `clone_url`. The orchestrator MUST clean up the workspace on both success and failure paths.

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

### Requirement: metadata.json field resolution follows a documented fallback order

The system prompt SHALL instruct the Agent to read project identity from `metadata.json` using the priority order: `project_info.project_code` → `project_code` (top-level) → `issue_info.service_name`; and `project_info.project_name` → `project_name`. The orchestrator SHALL document this order in `prompts_config.yaml` so it can be tuned without code changes.

#### Scenario: project_info preferred over service_name

- **WHEN** `metadata.json` contains both `project_info.project_code == "foo"` and `issue_info.service_name == "bar"`
- **THEN** the Agent issues `lookup_project_repo` with `project_code == "foo"`

### Requirement: Log archives extracted by Python with bounded size

The system SHALL extract the log archive referenced by the `LogRecord` into `<workspace>/logs/` using a Python extractor (not the Agent). Total uncompressed size SHALL be bounded by `settings.ai_analysis_max_extract_bytes` (default 2 GiB), and the task SHALL fail with a typed error if the bound is exceeded before exhausting the archive.

#### Scenario: Archive within size bound

- **WHEN** a `.tar.gz` archive of total uncompressed size 500 MiB is processed with default settings
- **THEN** extraction completes and `logs/` contains the archive members

#### Scenario: Archive exceeds size bound

- **WHEN** an archive whose cumulative entry sizes exceed `ai_analysis_max_extract_bytes` is processed
- **THEN** extraction aborts, partially extracted files are removed, and the Celery task fails with `WorkspaceExtractTooLarge`
- **AND** no agent loop is started

### Requirement: Agent tool surface is restricted to read-only investigation tools plus Bash plus the project-repo lookup MCP tool

The system SHALL configure `ClaudeAgentOptions.allowed_tools` to exactly `["Bash", "Read", "Grep", "Glob", "mcp__project_repo__lookup_project_repo"]`. The system MUST NOT enable `Edit`, `Write`, `WebFetch`, `WebSearch`, or `TodoWrite` for this agent. `permission_mode` SHALL be `"acceptEdits"`, and a `PreToolUse` hook SHALL block `Bash` commands that begin with destructive or network-egress prefixes outside the allowlist (`git`, `grep`, `rg`, `tar`, `zcat`, `gunzip`, `find`, `cat`, `head`, `tail`, `wc`, `jq`, `ls`, `awk`, `sed`).

#### Scenario: Disallowed tool is rejected at configuration time

- **WHEN** `build_options` is called for the log analysis agent
- **THEN** `ClaudeAgentOptions.allowed_tools` returned to the caller equals `["Bash","Read","Grep","Glob","mcp__project_repo__lookup_project_repo"]`
- **AND** none of `Edit`, `Write`, `WebFetch`, `WebSearch`, `TodoWrite` appear

#### Scenario: Bash hook blocks a curl command

- **WHEN** the agent attempts a `Bash` tool use with input `curl https://evil.example`
- **THEN** the `PreToolUse` hook denies the call before execution
- **AND** the denial is recorded in `tool_trace` with an explanatory message

### Requirement: Agent output is a structured JSON written to LogRecord.ai_analysis_result

The system SHALL persist the agent's final structured analysis to `LogRecord.ai_analysis_result` using `schema_version = 2` and the following top-level keys: `engine`, `model`, `schema_version`, `status`, `summary`, `severity`, `root_cause_hypotheses`, `recommended_actions`, `related_keywords`, `tool_trace`, `raw`, `duration_seconds`, `token_usage`. When the final assistant message does not contain a valid JSON block matching the documented schema, `status` SHALL be `"schema_mismatch"` and `raw` SHALL contain the full final assistant text.

#### Scenario: Well-formed JSON output is parsed and stored

- **WHEN** the agent's `ResultMessage` text contains a single fenced JSON block matching the schema
- **THEN** `ai_analysis_result.status == "ok"` and `summary`, `severity`, `root_cause_hypotheses`, `recommended_actions`, `related_keywords` reflect the JSON fields

#### Scenario: Malformed JSON falls back to raw

- **WHEN** the agent's final text is prose without a fenced JSON block
- **THEN** `ai_analysis_result.status == "schema_mismatch"`, `raw` equals the full final text, and other domain fields default to empty values

#### Scenario: Tool trace is recorded and excerpted

- **WHEN** the agent performs N tool calls during the run
- **THEN** `ai_analysis_result.tool_trace` contains N entries
- **AND** each entry's `output_excerpt` is at most 1 KiB and `input` is repo-URL-masked

### Requirement: Missing archive or unrecoverable project metadata fails with typed error_kind

The system SHALL refuse to run the log analysis when (a) `LogRecord.archive_path` is absent or unreadable, (b) the extracted archive contains no `metadata.json`, (c) `metadata.json` contains none of the keys in the documented fallback order, or (d) `lookup_project_repo` returns `not_found` for both `project_code` and `project_name`. Each failure MUST persist a distinct `error_kind` in `LogRecord.ai_analysis_result`: `"missing_archive"`, `"missing_metadata_json"`, `"missing_project_identity"`, `"project_repo_not_registered"`. There SHALL be no fallback to a non-repo analysis path.

#### Scenario: Log record without archive

- **WHEN** `run_ai_analysis_task` executes for a record with `archive_path == None`
- **THEN** the task fails immediately and `LogRecord.ai_analysis_result.status == "error"` with `error_kind == "missing_archive"`
- **AND** no workspace is created and no Anthropic API call is made

#### Scenario: Archive without metadata.json

- **WHEN** the workspace extraction completes but no file named `metadata.json` exists under `logs/`
- **THEN** the task fails with `error_kind == "missing_metadata_json"` and the workspace is cleaned up

#### Scenario: metadata.json without any project identity field

- **WHEN** `metadata.json` exists but contains none of `project_info.project_code`, `project_code`, or `issue_info.service_name`
- **THEN** the agent run completes with `status == "error"` and `error_kind == "missing_project_identity"`

#### Scenario: project_code resolves to unregistered project

- **WHEN** `lookup_project_repo` returns `not_found` for both `project_code` and `project_name`
- **THEN** the agent stops without `git clone` and the result has `error_kind == "project_repo_not_registered"`

### Requirement: Agent run has bounded duration and turn count

The system SHALL bound each agent run by both `settings.anthropic_max_turns` (SDK-level) and `settings.anthropic_request_timeout_seconds` (orchestrator-level). The Celery task SHALL apply a soft timeout equal to the request timeout plus 60 seconds and a hard timeout 60 seconds beyond the soft timeout.

#### Scenario: Agent exceeds max turns

- **WHEN** the agent loop runs for `anthropic_max_turns + 1` iterations
- **THEN** the SDK stops the loop and the orchestrator records `status == "error"`, `error_kind == "max_turns_exceeded"`

#### Scenario: Agent exceeds wall-clock budget

- **WHEN** the agent run exceeds `anthropic_request_timeout_seconds`
- **THEN** the orchestrator cancels the run, cleans up the workspace, and records `status == "error"`, `error_kind == "timeout"`

### Requirement: Prompts for the new agent live under a new prompts key

The system SHALL define the new agent's system and user prompt templates under a fresh top-level key (e.g., `claude_agent_log_analysis`) in `app/prompts/prompts_config.yaml`, with per-log-type variants. The legacy LangGraph prompt keys SHALL be removed in the same change.

#### Scenario: Legacy prompt keys absent

- **WHEN** `prompts_config.yaml` is loaded after the change
- **THEN** keys used by the deleted LangGraph agents (e.g., the old `log_agent.*` keys) are not present
- **AND** the new `claude_agent_log_analysis` key is present with at least one log-type variant
