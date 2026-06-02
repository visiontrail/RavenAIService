### Requirement: Project Expert runs on Claude Agent SDK and reuses Log Analysis trace and repo-lookup tooling

The system SHALL implement a Project Expert agent exclusively via the Claude Agent SDK `query()` agent loop, in a new package `app/agents/project_expert/`. The agent SHALL reuse the existing trace layer `app/agents/log_analysis/trace.py` (the `AgentTraceEvent` model and event constants) and the existing in-process MCP tool `mcp__project_repo__lookup_project_repo` from `app/agents/log_analysis/mcp_tools.py`. The agent's allowed tools SHALL be exactly `Bash`, `Read`, `Grep`, `Glob`, `Skill`, and `mcp__project_repo__lookup_project_repo`. The agent key SHALL be `project_expert`.

#### Scenario: Agent loop uses Claude Agent SDK

- **WHEN** `ProjectExpertAgent().run_stream(ctx)` is invoked for a valid context
- **THEN** it drives a Claude Agent SDK `query()` loop
- **AND** it emits `AgentTraceEvent` values using the constants imported from `app/agents/log_analysis/trace.py`
- **AND** the run result records `engine == "claude-agent-sdk"`

#### Scenario: Repo lookup tool is reused, not reimplemented

- **WHEN** the Project Expert agent resolves a repository
- **THEN** it calls the MCP tool `mcp__project_repo__lookup_project_repo` provided by `app/agents/log_analysis/mcp_tools.get_mcp_server()`
- **AND** no duplicate `lookup_project_repo` implementation is added under `app/agents/project_expert/`

### Requirement: Project Expert does NOT perform attached-log analysis

The system SHALL NOT accept or process any log archive in the Project Expert workflow. The workspace preparation SHALL NOT create a `logs/` directory, SHALL NOT extract any archive, and SHALL NOT require or look up a `metadata.json`. The `/project-expert/stream` endpoint SHALL NOT accept a file upload field.

#### Scenario: Workspace contains no logs directory

- **WHEN** the Project Expert workspace is prepared for a session
- **THEN** the workspace directory contains a `task.json` and an empty `repo/` placeholder
- **AND** the workspace directory does NOT contain a `logs/` directory
- **AND** no archive extraction is performed

#### Scenario: Missing metadata.json never fails the run

- **WHEN** a Project Expert run executes
- **THEN** the run never fails with a missing-`metadata.json` error
- **AND** the system prompt contains no instruction to read `logs/` or to locate `metadata.json`

#### Scenario: Stream endpoint rejects file uploads

- **WHEN** the `/project-expert/stream` endpoint is defined
- **THEN** it exposes no `file`/`UploadFile` parameter
- **AND** the request schema carries `message`, `session_id`, `history`, `remember`, and `project_repo_id`

### Requirement: Project identity comes from a user-selected project repository

The system SHALL require `project_repo_id` for a new Project Expert session. The service layer SHALL resolve the selected project from the project repository registry and write its non-sensitive identity into `task.json` under `repo_info` with `source == "user_selected_project_repo"`. The `task.json` SHALL NOT contain any git token. The system prompt SHALL instruct the agent to read `repo_info` from `task.json`, call `mcp__project_repo__lookup_project_repo` with the `project_code` to obtain a token-injected `clone_url` and `default_branch`, and clone into `repo/`.

#### Scenario: New session without project_repo_id is rejected

- **WHEN** a new Project Expert session is started without `project_repo_id`
- **THEN** the request fails with a 4xx error whose reason is `project_repo_required`
- **AND** no workspace is prepared

#### Scenario: Selected project written as authoritative repo_info

- **WHEN** a new session is started with `project_repo_id` pointing to a registered repo with `project_code == "foo"`
- **THEN** `task.json` contains `repo_info.project_code == "foo"`, `repo_info.repo_url`, `repo_info.default_branch`, and `repo_info.source == "user_selected_project_repo"`
- **AND** `task.json` contains no git token

#### Scenario: Token only injected in tool response, never persisted

- **WHEN** the agent resolves the repository for a private project via `lookup_project_repo`
- **THEN** the token-injected `clone_url` appears only in the MCP tool response
- **AND** neither `task.json` on disk nor any emitted `AgentTraceEvent` contains a plaintext git token

### Requirement: Agent clones and analyzes source code to answer the user's question

The system SHALL allocate a per-session temporary workspace under `settings.code_repo_clone_base_dir/<task_id>/`. On the first turn the agent SHALL `git clone` the resolved repository into `repo/`; on subsequent turns, if `repo/.git` already exists, the agent SHALL reuse the existing clone rather than cloning again. The agent SHALL use `Read`, `Grep`, `Glob`, and `Bash` against `repo/` to analyze the source code and answer the user's question, citing file paths (and line numbers where applicable).

#### Scenario: First turn clones into repo/

- **WHEN** the first turn of a session runs and `repo/.git` does not exist
- **THEN** the recorded tool trace shows a `Bash` `git clone` targeting `<workspace>/repo`
- **AND** subsequent analysis tool calls operate under `repo/`

#### Scenario: Follow-up turn reuses the existing clone

- **WHEN** a follow-up turn runs in a session whose workspace already contains `repo/.git`
- **THEN** the agent does NOT issue another `git clone`
- **AND** it operates on the existing repository (e.g. `git -C repo`, `rg ... repo`, file reads)

#### Scenario: Answer is grounded in the source

- **WHEN** the agent answers a question about the project
- **THEN** the answer references concrete locations in `repo/` (file paths, and line numbers where applicable)

### Requirement: Session-scoped persistent workspace supports follow-up questions

The system SHALL keep a persistent filesystem workspace per chat session via `ProjectExpertChatService`, so a user can ask follow-up questions against the same cloned repository without re-cloning. New work SHALL run as a long-lived background task; SSE streams SHALL be views subscribing to the job's buffered events; client disconnects SHALL NOT cancel the underlying job. The workspace SHALL be cleaned up idempotently when the session is reclaimed.

#### Scenario: Follow-up reuses the same workspace

- **WHEN** a second question is sent with the same `session_id`
- **THEN** the service reuses the existing workspace directory bound to that session
- **AND** the cloned `repo/` from the first turn is still present

#### Scenario: Client disconnect does not cancel the job

- **WHEN** an SSE client disconnects while a Project Expert turn is running
- **THEN** the underlying background job continues to completion
- **AND** its result remains retrievable via `GET /project-expert/result`

#### Scenario: Switching project mid-session is not silently honored

- **WHEN** a follow-up turn passes a `project_repo_id` different from the session's first-turn project
- **THEN** the run stays bound to the first-turn project's `repo/`
- **AND** a `system_notice` event informs the user to start a new session to switch projects

### Requirement: Project Expert exposes stream, cancel, and result endpoints

The system SHALL expose `POST /project-expert/stream` (SSE), `POST /project-expert/cancel`, and `GET /project-expert/result`. The SSE stream SHALL emit the same event protocol as Log Analysis (`run_start`, `step_start`/`step_delta`/`step_end`, `thinking_start`/`thinking_delta`/`thinking_end`, `answer_delta`, `run_complete`, plus `system_notice`/`error`). Cancellation SHALL be best-effort and signaled to the running job; `result` SHALL serve as a polling fallback for status and final answer.

#### Scenario: Stream emits the shared trace protocol

- **WHEN** a client subscribes to `POST /project-expert/stream` for a running turn
- **THEN** it receives `run_start` first and `run_complete` last
- **AND** intermediate events use the same event types as the Log Analysis stream

#### Scenario: Cancel signals the running job

- **WHEN** `POST /project-expert/cancel` is called with an in-flight `session_id`
- **THEN** the job's cancel signal is set
- **AND** the run terminates and reports a cancelled status

#### Scenario: Result polling returns final answer

- **WHEN** `GET /project-expert/result?session_id=...` is called after a turn finished
- **THEN** it returns the run status and the final answer for that session

### Requirement: Project Expert supports Skill loading via the agent registry

The system SHALL register `project_expert` in `app/services/skills_service.SUPPORTED_AGENTS`. Before each `query()` run the agent SHALL materialize enabled skills for `project_expert` into `<workspace>/.claude/skills/<name>/` via `materialize_relevant_enabled_skills("project_expert", workspace_dir, query_text=..., project_code=<project_code>)` and SHALL set `setting_sources=["project"]` so the SDK auto-loads them. The admin Agent Skills page SHALL list `ProjectExpertAgent` in its agent dropdown without additional admin-code changes.

**Change**: The `materialize_relevant_enabled_skills` call SHALL now include the `project_code` parameter derived from the session's `ProjectRepo.project_code`. This causes project-level skills to be included in the candidate pool alongside agent-level skills. The `loaded_skills` field in trace events and the run result SHALL reflect all materialized skills regardless of source (agent or project).

#### Scenario: project_expert registered in SUPPORTED_AGENTS

- **WHEN** `skills_service.SUPPORTED_AGENTS` is inspected
- **THEN** it contains a `project_expert` entry with `framework == "Claude Agent SDK"`
- **AND** the admin agent dropdown (driven by `SUPPORTED_AGENTS`) includes `ProjectExpertAgent`

#### Scenario: Enabled skills materialized before the run

- **WHEN** a Project Expert run starts with one enabled agent skill `foo` and one enabled project skill `bar` for the session's project
- **THEN** `<workspace>/.claude/skills/foo/` and `<workspace>/.claude/skills/bar/` exist before the `query()` loop begins
- **AND** the agent is configured with `setting_sources=["project"]`

#### Scenario: Project skill overrides same-named agent skill

- **WHEN** agent `project_expert` has enabled skill `helper` and the session's project also has enabled skill `helper`
- **THEN** the materialized `<workspace>/.claude/skills/helper/SKILL.md` contains the project skill content

#### Scenario: Run result includes project skill names in loaded_skills

- **WHEN** the run completes having materialized both agent and project skills
- **THEN** `result["loaded_skills"]` lists all materialized skill names
- **AND** the `run_start` trace event's `loaded_skills` field matches

#### Scenario: Session without project falls back to agent-only skills

- **WHEN** the session context has no project_code (defensive edge case)
- **THEN** only agent-level skills are materialized and behavior is identical to the pre-change implementation

### Requirement: Front-end exposes a Project Expert agent option with required project selection and no file upload

The system SHALL add a "项目专家" agent option to the chat composer (`AIChat.vue`), alongside "日志分析" and "重构包配置管理员". When the Project Expert option is selected, the composer SHALL require the user to select a related project before sending, SHALL disable log-file selection and drag-and-drop, and SHALL route the turn to `POST /project-expert/stream`, rendering the response with the existing agent-trace stream UI.

#### Scenario: Project selection required before send

- **WHEN** the Project Expert option is selected and no related project is chosen
- **THEN** sending is disabled and the user is prompted to select a project

#### Scenario: File upload disabled under Project Expert

- **WHEN** the Project Expert option is active
- **THEN** the log-file picker and drag-and-drop upload are disabled
- **AND** a sent turn calls `POST /project-expert/stream` with the selected `project_repo_id`
