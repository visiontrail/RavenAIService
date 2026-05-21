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

## MODIFIED Requirements

### Requirement: Agent loop 消息处理

`LogAnalysisAgent.run()` SHALL 在异步处理 Claude Agent SDK `query()` 返回的每条消息时，除了将事件写入本地结构化日志（`_log_workflow`）并累积 `tool_trace` 之外，**额外**通过可选注入的 `trace_emitter: Callable[[AgentTraceEvent], None] | None` 把每条 SDK 消息转换为一条或多条 `AgentTraceEvent` 并外发。

`trace_emitter` MUST 满足：

- 类型为同步函数（非协程），返回值忽略；调用方在不同 event loop / 不同线程间共享同一 agent 实例时无需额外适配；
- 不传 emitter（`None`）时，Agent 行为 MUST 与现状一致（向后兼容），即仅写日志与累积 `tool_trace`；
- emitter 内部抛出异常 MUST NOT 中断 agent 主流程，仅 logger.warning 记录。

每条 SDK 消息按以下映射转化为事件：

- 进入 loop 前发 `run_start`（携带 `model`、`provider`）；
- 退出 loop 后发 `run_complete`（携带 `trace_summary`、`final_text`）或 `cancelled`（取消时）或 `error`（异常时）；
- assistant 文本块：拆分为 `thinking_start` / `thinking_delta`*（按 ≤ 4 KB 切片）/ `thinking_end`；
- tool_use 块：发 `step_start{tool_name, tool_input}`；
- tool_result 块：先发若干 `step_delta{output_chunk}`（按 ≤ 4 KB 切片），再发 `step_end{status, output_excerpt, duration_seconds}`；
- system / 其他 subtype 消息：发 `system_notice{subtype, detail}`。

#### Scenario: 不传 emitter 行为不变

- **WHEN** 调用方以 `LogAnalysisAgent().run(ctx)` 调用（不传 `trace_emitter`）
- **THEN** Agent MUST 完成分析并返回与现状结构一致的 result dict，且 NOT 因为缺失 emitter 报错

#### Scenario: emitter 收到完整事件序列

- **WHEN** 调用方传入收集型 emitter `collected = []; trace_emitter=collected.append`
- **THEN** `collected` MUST 以 `run_start` 起、以 `run_complete` / `cancelled` / `error` 之一止，期间包含本次分析全部 tool / thinking / system 事件，按 `seq` 严格递增

#### Scenario: emitter 抛错不影响主流程

- **WHEN** 调用方传入会随机抛错的 emitter
- **THEN** Agent loop MUST 继续运行至自然结束，最终 result dict MUST 与传入正常 emitter 时具有相同 `status` 和 `summary`

### Requirement: result dict 扩展字段

`LogAnalysisAgent.run()` 返回的 result dict SHALL 在现有字段基础上**新增**：

- `trace_events: List[AgentTraceEvent]` — 本次 agent loop 产生的完整事件流（含 `run_start`、`run_complete` 等终态）；
- `trace_summary: Dict` — 至少包含 `thought_duration_seconds: float`、`tool_call_count: int`、`thinking_chars: int`。

现有字段 `tool_trace` SHALL 继续被填充，且 MUST 由 `trace_events` 派生（仅保留 tool_use 类条目，结构 `{name, input, output_excerpt}`），以保证旧消费者不感知本次变更。

#### Scenario: 新字段被填充

- **WHEN** Agent 正常完成
- **THEN** 返回 dict MUST 同时包含非空的 `trace_events` 列表、`trace_summary` 字典以及由其派生的 `tool_trace` 列表

#### Scenario: tool_trace 派生一致性

- **WHEN** result 同时包含 `trace_events` 与 `tool_trace`
- **THEN** `tool_trace` 中的条目 MUST 与 `trace_events` 中所有 `step_end` 事件一一对应（按 step_id 关联），`name == tool_name`、`input == tool_input`、`output_excerpt == output_excerpt`

### Requirement: 取消时的事件语义

当 `cancel_event` 被外部设置后，Agent SHALL 在下一次 SDK 消息到达前的检查点：

1. 立即通过 emitter 发出 `system_notice{kind: "cancel_requested"}`（如果之前未发过同 kind 事件）；
2. 抛出内部 `AgentCancelled`，触发外层捕获；
3. 在退出 loop 前发 `cancelled` 终态事件，并在返回的 result dict 中携带 `trace_events` 与 `trace_summary`。

#### Scenario: 取消两阶段反馈

- **WHEN** 外部在第 5 次 tool_use 进行中 set 了 cancel_event
- **THEN** 收集型 emitter 收到的事件序列 MUST 满足：先一条 `system_notice{kind: "cancel_requested"}`，再一条 `cancelled`，且 `cancelled` 后无任何额外事件

#### Scenario: 取消结果仍带 summary

- **WHEN** Agent 因 cancel_event 退出
- **THEN** 返回 dict MUST 包含 `trace_summary`，其 `tool_call_count` 不少于已发出 `step_end` 的次数
