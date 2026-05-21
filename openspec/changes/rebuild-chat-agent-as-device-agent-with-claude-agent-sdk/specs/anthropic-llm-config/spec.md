## ADDED Requirements

### Requirement: `build_options` accepts `can_use_tool` and `hooks` injection

The system SHALL extend `app/agents/anthropic_client.build_options(...)` with two optional keyword arguments: `can_use_tool` (an async callable matching the Claude Agent SDK signature `(tool_name: str, tool_input: dict, context: Any) -> dict`) and `hooks` (a mapping `{hook_event_name: list[HookMatcher]}` as accepted by `ClaudeAgentOptions`). When provided, these values SHALL be forwarded verbatim to the returned `ClaudeAgentOptions`. When omitted, the resulting options SHALL behave identically to the previous signature.

#### Scenario: can_use_tool passthrough

- **WHEN** a caller invokes `build_options(..., can_use_tool=my_cb)` where `my_cb` is an async callable
- **THEN** the returned `ClaudeAgentOptions.can_use_tool is my_cb`
- **AND** no other field is mutated by passing the callback

#### Scenario: Hooks passthrough

- **WHEN** a caller invokes `build_options(..., hooks={"PostToolUse": [validator_matcher]})`
- **THEN** `ClaudeAgentOptions.hooks["PostToolUse"]` contains `validator_matcher`

#### Scenario: Backwards-compatible default

- **WHEN** a caller invokes `build_options(...)` without passing `can_use_tool` or `hooks`
- **THEN** the returned `ClaudeAgentOptions` has no `can_use_tool` attribute set (or it is `None`) and `hooks` is empty/None

### Requirement: Conversational agents may request the `default` permission mode

The system SHALL permit callers to pass `permission_mode="default"` to `build_options(...)` and SHALL forward that value to `ClaudeAgentOptions.permission_mode`. Together with a registered `can_use_tool` callback, this mode enables interactive human-in-the-loop review for conversational agents (e.g., DeviceAgent) without disabling tool-use entirely.

#### Scenario: default mode + callback forwarded together

- **WHEN** a caller invokes `build_options(..., permission_mode="default", can_use_tool=cb)`
- **THEN** the returned `ClaudeAgentOptions.permission_mode == "default"` and `ClaudeAgentOptions.can_use_tool is cb`

## REMOVED Requirements

### Requirement: OpenAI-compatible configuration remains untouched

**Reason**: The new DeviceAgent replaces the LangGraph ChatAgent, which was the only remaining consumer of the OpenAI-compatible `Settings` fields. The `rebuild-chat-agent-as-device-agent-with-claude-agent-sdk` change deletes `app/agents/chat_agent.py` and the "primary model" runtime overrides; the OpenAI-compatible config fields (`openai_api_key`, `openai_base_url`, `deepseek_api_key`, `deepseek_base_url`, `llm_model_name`, `llm_reasoning_model`, `llm_temperature`, `llm_provider`) are removed when no other code references them.

**Migration**: All Anthropic-backed agents (LogAnalysisAgent, DeviceAgent, and the new chat-title generator) consume `ANTHROPIC_*` settings via `app/agents/anthropic_client.build_options`. Operators who previously set `OPENAI_API_KEY` for chat MUST set `ANTHROPIC_API_KEY` (and optionally `ANTHROPIC_PROVIDER`, `ANTHROPIC_MODEL`, `ANTHROPIC_BASE_URL`) before deploying this change. The admin "Model Settings" page no longer exposes a writable "primary model" form; the Anthropic configuration view is read-only.
