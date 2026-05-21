## ADDED Requirements

### Requirement: Device chat runs on Claude Agent SDK and the legacy LangGraph ChatAgent is removed

The system SHALL implement the device-linked chat feature exclusively via the Claude Agent SDK `query()` agent loop, exposed through a new class `app/agents/device_agent/agent.DeviceAgent`. The legacy LangGraph modules (`app/agents/chat_agent.py`, `app/agents/tools/device_prompt_tool.py`, and the `app/agents/tools/__init__.py` re-export) MUST be removed from the codebase. `app/services/ai_chat_service.py` MUST NOT import `langchain_core`, `langchain_openai`, `langgraph`, or `app.agents.chat_agent` after this change.

#### Scenario: No legacy chat-agent imports remain

- **WHEN** the repository is grepped after this change is applied
- **THEN** there are zero Python imports of `app.agents.chat_agent` or `app.agents.tools.device_prompt_tool`
- **AND** there are zero imports of `langchain_core.messages`, `langchain_openai`, `langgraph.graph`, or `langgraph.prebuilt` inside `app/agents/` or `app/services/`

#### Scenario: Chat endpoint dispatches to DeviceAgent

- **WHEN** `POST /chat` is invoked with a valid `target_device_id`
- **THEN** the request is served by `app.agents.device_agent.agent.DeviceAgent` and the response `model` field equals the effective Anthropic model id

### Requirement: Remote device MCP tools are dynamically mapped to in-process SDK tools per request

The system SHALL, on every chat run, query the linked device via `device_link_manager.get_device(target_device_id)` and convert every reported `(server_name, tool_name)` entry in `device.capabilities.mcp.servers[]` into a Claude Agent SDK in-process tool registered through `create_sdk_mcp_server(name="device", ...)`. Each generated tool's name SHALL be `mcp__device__<server_name>__<tool_name>`, its `description` SHALL be the remote tool's `description` (or a generated fallback), and its `input_schema` SHALL be the remote tool's `inputSchema` when present (falling back to `{"type": "object", "additionalProperties": true}`). `ClaudeAgentOptions.allowed_tools` SHALL include only the generated names plus `"Skill"`; it MUST NOT include `Bash`, `Read`, `Write`, `Edit`, `WebFetch`, `WebSearch`, or `TodoWrite`.

#### Scenario: Remote tools become SDK tools

- **WHEN** a device reports two MCP tools `task.list_background_tasks` and `task.start_background_task` and the user sends a chat message targeting that device
- **THEN** `ClaudeAgentOptions.allowed_tools` returned to the SDK includes `mcp__device__task__list_background_tasks` and `mcp__device__task__start_background_task`
- **AND** the `device` MCP server registered with `create_sdk_mcp_server` exposes exactly these two proxy tools
- **AND** the `Skill` tool is also present in `allowed_tools`

#### Scenario: Disallowed built-in tools are never exposed

- **WHEN** any chat request reaches DeviceAgent
- **THEN** none of `Bash`, `Read`, `Write`, `Edit`, `Grep`, `Glob`, `WebFetch`, `WebSearch`, `TodoWrite` appear in `ClaudeAgentOptions.allowed_tools`

#### Scenario: Remote tool count is bounded

- **WHEN** a device reports more than `device_agent_max_remote_tools` (default 64) tools
- **THEN** DeviceAgent registers only the first 64 (deterministic by `(server_name, tool_name)` sort order) and emits a `system_notice` trace event with `kind == "too_many_tools"` listing the dropped names

### Requirement: Tool invocations are forwarded to the device using a versioned structured envelope

Each generated SDK proxy tool SHALL forward its invocation to the linked device by constructing a `PromptEnvelope` whose `prompt` field is a JSON string containing at minimum: `protocol_version`, `action == "mcp_call"`, `server`, `tool`, `args`, `request_id`, `permission_decision`, and `ts`. The envelope SHALL be delivered through the existing `device_link_manager.send_prompt` API and the proxy SHALL return the device's structured reply (after `PostToolUse` validation) as the tool result.

#### Scenario: Envelope contains structured payload

- **WHEN** the model invokes `mcp__device__task__list_background_tasks` with `args == {"limit": 5}`
- **THEN** `device_link_manager.send_prompt` is called with a `PromptEnvelope` whose `prompt` parses as JSON with `protocol_version == 2`, `action == "mcp_call"`, `server == "task"`, `tool == "list_background_tasks"`, `args == {"limit": 5}`, and a `request_id` matching the SDK tool-use id (or a freshly generated UUID if unavailable)

#### Scenario: Legacy device fallback envelope

- **WHEN** the connected device's reported capabilities include `protocol_version < 2` (or no `protocol_version` field)
- **THEN** the proxy MAY fall back to the legacy `【DEVICE_TASK】...【/DEVICE_TASK】` text envelope while keeping the model-facing tool name and input schema unchanged
- **AND** a `system_notice` trace event with `kind == "legacy_envelope"` is emitted on the first such call per run

### Requirement: Human-in-the-loop tool review via `can_use_tool`

DeviceAgent SHALL install a `can_use_tool` callback in `ClaudeAgentOptions` that classifies every tool call into one of three risk levels (`read`, `write`, `destructive`). For `read`-level calls the callback SHALL return `{"behavior": "allow"}` immediately. For `write` and `destructive` calls the callback SHALL emit a `tool_permission_request` trace event carrying `{request_id, tool_name, args, risk, rationale}`, wait for an external decision delivered through `POST /chat/permissions/{request_id}/resolve`, and translate that decision into the SDK return value. The wait SHALL be bounded by `device_agent_permission_timeout_seconds` (default 120 seconds); on timeout the callback SHALL return `{"behavior": "deny", "message": "permission timeout"}` and emit a `tool_permission_resolved` trace event with `decision == "deny"` and `reason == "timeout"`.

#### Scenario: Read-only tool allowed without prompting

- **WHEN** the model invokes a tool classified as `read` (e.g., matched by glob `*list*`/`*status*`/`*get*` or carrying `"risk": "read"` in its capability metadata)
- **THEN** the `can_use_tool` callback returns `{"behavior": "allow"}` synchronously
- **AND** no `tool_permission_request` event is emitted

#### Scenario: Destructive tool blocked until user approves

- **WHEN** the model invokes a tool classified as `destructive` and the user responds via `POST /chat/permissions/{request_id}/resolve` with `{"decision": "allow"}`
- **THEN** the SSE stream emits a `tool_permission_request` event followed by a `tool_permission_resolved` event with `decision == "allow"`
- **AND** the `can_use_tool` callback returns `{"behavior": "allow"}`
- **AND** the underlying SDK tool invocation proceeds

#### Scenario: User edits args before approving

- **WHEN** the user responds with `{"decision": "allow", "updated_args": {"force": false}}` for a request whose original args contained `{"force": true}`
- **THEN** the `can_use_tool` callback returns `{"behavior": "allow", "updatedInput": {"force": false}}`
- **AND** the SDK invokes the proxy with the overridden args

#### Scenario: Timeout denies and unblocks the loop

- **WHEN** the user does not respond within `device_agent_permission_timeout_seconds`
- **THEN** the callback returns `{"behavior": "deny", "message": "permission timeout"}`
- **AND** a `tool_permission_resolved` event with `decision == "deny"` and `reason == "timeout"` is emitted

### Requirement: Client return values are validated by a `PostToolUse` hook

DeviceAgent SHALL register a `PostToolUse` hook matched against `mcp__device__*` that validates every device-returned tool result before it is fed back to the model. The hook SHALL: (a) parse the device reply per the `Decision 10` envelope schema; (b) validate the `result` field against the tool's `outputSchema` when present; (c) truncate any single `evidence` entry exceeding `device_agent_result_excerpt_bytes` (default 16 KiB) and mark it `truncated: true`; (d) replace the full content with `{"error_kind": "result_too_large"}` when the raw payload exceeds `device_agent_result_max_bytes` (default 256 KiB); (e) mask URL/token-shaped substrings using the same masking helpers as the log-analysis agent; (f) emit a `result_validation` trace event with `status` ∈ `{"ok", "schema_mismatch", "truncated", "error"}`. When validation fails, the hook SHALL return `permissionDecision == "allow"` with `modifiedContent` containing a JSON object `{"error_kind": <code>, "raw_excerpt": <truncated>}` instead of the original payload.

#### Scenario: Schema-conformant result passes through

- **WHEN** a proxy tool returns `{"status": "ok", "result": {...}}` matching the tool's `outputSchema`
- **THEN** the hook emits a `result_validation` event with `status == "ok"`
- **AND** the unchanged content reaches the model

#### Scenario: Schema-mismatched result is replaced

- **WHEN** the device returns a payload missing required `outputSchema` fields
- **THEN** the hook emits a `result_validation` event with `status == "schema_mismatch"`
- **AND** the content passed back to the model is `{"error_kind": "schema_mismatch", "raw_excerpt": <≤ excerpt_bytes>}`

#### Scenario: Oversized result is truncated

- **WHEN** a device result's `raw` field exceeds `device_agent_result_max_bytes`
- **THEN** the hook returns `modifiedContent == {"error_kind": "result_too_large"}` and emits `result_validation` with `status == "error"`

#### Scenario: Tokens in result are masked

- **WHEN** a device result includes a substring `https://x:abcdef@host/path`
- **THEN** the content fed back to the model and recorded in trace replaces the credential prefix with `https://***@host/path`

### Requirement: DeviceAgent supports Skill packages via `setting_sources=["project"]`

The system SHALL register `device_agent` in `app/services/skills_service.SUPPORTED_AGENTS` and, on every chat run, materialize all enabled Skill packages for that agent key into a per-run temporary working directory under `<workspace>/.claude/skills/<skill_name>/` before invoking the SDK. `ClaudeAgentOptions.cwd` SHALL be set to the working directory and `ClaudeAgentOptions.setting_sources` SHALL include `"project"` whenever at least one skill is materialized. The `Skill` tool name SHALL remain in `allowed_tools`. The workspace SHALL be removed at the end of every run regardless of success or failure.

#### Scenario: Enabled Skill is materialized

- **WHEN** an admin has uploaded and enabled a Skill named `device-troubleshooter` for the `device_agent` key, and a chat run begins
- **THEN** the path `<workspace>/.claude/skills/device-troubleshooter/SKILL.md` exists before `query()` is invoked
- **AND** `ClaudeAgentOptions.setting_sources` contains `"project"`

#### Scenario: Workspace cleaned up after run

- **WHEN** a chat run finishes (success, schema_mismatch, error, or cancelled)
- **THEN** the temporary workspace directory used for that run no longer exists on disk

#### Scenario: Admin UI lists DeviceAgent

- **WHEN** the admin opens the Agent Skills page
- **THEN** the agent selector lists `DeviceAgent` alongside `LogAnalysisAgent`
- **AND** uploading/enabling a Skill for `device_agent` succeeds through the existing `/admin/agent-skills/*` API

### Requirement: Agent trace events stream to clients over SSE

The system SHALL stream every Claude Agent SDK message as `AgentTraceEvent` items (defined in `app/agents/log_analysis/trace.py`) plus the device-agent-specific events `tool_permission_request`, `tool_permission_resolved`, and `result_validation` to the chat SSE client through `POST /chat/stream`. The SSE event stream SHALL include `run_start`, zero or more `thinking_*`, `step_*`, `tool_permission_*`, `result_validation`, and finally exactly one `run_complete` event (or `cancelled`/`error` in failure paths) per request. The final assistant text SHALL also be emitted as a `chunk`/`done` envelope so existing front-end consumers continue to display the answer.

#### Scenario: Tool call produces ordered events

- **WHEN** the model issues a tool call against a destructive tool, the user approves, and the device returns a schema-conformant result
- **THEN** the SSE stream emits, in order: `run_start`, `step_start`, `tool_permission_request`, `tool_permission_resolved` (decision allow), `step_end`, `result_validation` (status ok), `run_complete`

#### Scenario: Final assistant text reaches the legacy `done` event

- **WHEN** the agent run finishes successfully with a non-empty `final_text`
- **THEN** the SSE stream still emits a final `done` event whose `answer` equals the final assistant text and `model` equals the effective Anthropic model

### Requirement: Permission resolution endpoint accepts user decisions

The system SHALL expose `POST /chat/permissions/{request_id}/resolve` that accepts a JSON body `{decision: "allow"|"deny", updated_args?: object, message?: string}` and resolves the corresponding pending `can_use_tool` request. The endpoint SHALL return HTTP 200 with `{"resolved": true}` on success, HTTP 404 when `request_id` is unknown or already resolved, and HTTP 400 when the request body fails schema validation. The endpoint SHALL require the same authentication as `POST /chat`.

#### Scenario: Allow with updated args is forwarded

- **WHEN** the front-end posts `{"decision": "allow", "updated_args": {"limit": 10}}` for an open permission request
- **THEN** the server returns HTTP 200 and the `can_use_tool` callback completes with `{"behavior": "allow", "updatedInput": {"limit": 10}}`

#### Scenario: Unknown request id rejected

- **WHEN** the front-end posts a decision for a `request_id` that does not exist
- **THEN** the server returns HTTP 404

### Requirement: Unsupported provider produces a typed failure

When `anthropic_provider` resolves to a profile whose `supports_mcp_server_tools` is `False` (e.g., `deepseek` or `custom` with default capability matrix), DeviceAgent SHALL refuse to start the agent loop and SHALL surface an error to the client with `error_kind == "provider_no_mcp_support"`, naming the active provider.

#### Scenario: DeepSeek provider refused

- **WHEN** `settings.anthropic_provider == "deepseek"` and the user sends a chat message with a `target_device_id`
- **THEN** the server returns an SSE `error` event with `error_kind == "provider_no_mcp_support"` and a human-readable message naming `deepseek`
- **AND** no SDK `query()` invocation is made

### Requirement: Primary-model runtime configuration is removed

The system SHALL remove all "primary model" runtime configuration surfaces previously used by the LangGraph ChatAgent: `app/services/runtime_settings_service.get_effective_primary_config` and its writer; `GET/PUT` endpoints under `/admin/model-settings/primary` (or equivalent); the `OPENAI_API_KEY`, `OPENAI_BASE_URL`, `DEEPSEEK_API_KEY`, `DEEPSEEK_BASE_URL`, `LLM_MODEL_NAME`, `LLM_TEMPERATURE` related `Settings` fields when no other module depends on them; and the front-end "主力模型" form block plus its `api/admin.ts` methods. Chat title generation SHALL be re-implemented on top of `app/agents/anthropic_client.build_options` using the existing Anthropic configuration.

#### Scenario: No primary-model setter remains

- **WHEN** the codebase is grepped after this change is applied
- **THEN** there are zero references to `get_effective_primary_config`, `update_primary_config`, or `_PRIMARY_CONFIG_KEYS`
- **AND** the admin "Model Settings" page has no editable form for primary-model `model` / `base_url` / `api_key` / `temperature`

#### Scenario: Chat title still works without OpenAI keys

- **WHEN** the user completes the first turn in a new session with `OPENAI_API_KEY` unset and `ANTHROPIC_API_KEY` set
- **THEN** the session title is generated via an Anthropic-backed `query()` call and persisted exactly as before
