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

### Requirement: `build_options` accepts caller-side `model`, `max_tokens`, and `request_timeout_seconds` overrides

The system SHALL extend `app/agents/anthropic_client.build_options(...)` with three optional keyword-only arguments: `model: Optional[str] = None`, `max_tokens: Optional[int] = None`, and `request_timeout_seconds: Optional[int] = None`. When `model` is provided, the effective model id used in the returned `ClaudeAgentOptions` SHALL be the caller-provided value, taking precedence over `settings.anthropic_model` and the active provider profile's `default_model`. When `model` is omitted, the existing resolution order (`settings.anthropic_model` → `profile.default_model`) SHALL apply unchanged. When `max_tokens` or `request_timeout_seconds` are provided, they SHALL be forwarded to `ClaudeAgentOptions` verbatim.

The implementation SHALL emit an INFO-level log entry whenever the caller-provided `model` differs from `settings.anthropic_model`, naming both values so operators can audit lightweight-task model routing.

#### Scenario: caller-provided model wins

- **WHEN** `settings.anthropic_provider == "deepseek"`, `settings.anthropic_model == None`, and the caller invokes `build_options(..., model="deepseek-v4-flash")`
- **THEN** the returned `ClaudeAgentOptions.model == "deepseek-v4-flash"`
- **AND** `options.env["ANTHROPIC_BASE_URL"] == "https://api.deepseek.com/anthropic"` (base_url is unchanged — only the model id is routed)

#### Scenario: max_tokens and request_timeout_seconds passthrough

- **WHEN** the caller invokes `build_options(..., max_tokens=1024, request_timeout_seconds=30)`
- **THEN** the returned `ClaudeAgentOptions` carries `max_tokens=1024` and the SDK env / option set carries `request_timeout_seconds=30`

#### Scenario: omitted model falls back to Settings then profile

- **WHEN** `settings.anthropic_provider == "deepseek"` and `settings.anthropic_model == "deepseek-v4-pro"` and the caller invokes `build_options(...)` without `model`
- **THEN** the returned `ClaudeAgentOptions.model == "deepseek-v4-pro"` (Settings beats profile default; no INFO log about caller override)

### Requirement: Lightweight tasks share the active Anthropic provider and route to `small_fast_model`

The system SHALL execute all lightweight LLM tasks (session-title generation, user-input summarization, and any other short low-latency single-turn invocation that previously ran on `light_llm_service`) through the same Anthropic provider as the primary agents (LogAnalysisAgent, DeviceAgent), reusing the same `ANTHROPIC_API_KEY` / `ANTHROPIC_BASE_URL`. Lightweight task callers SHALL invoke `build_options(..., model=<lightweight_model>)` where `<lightweight_model>` is resolved as `settings.anthropic_small_fast_model or PROVIDER_PROFILES[settings.anthropic_provider].default_small_fast_model`. The system SHALL NOT provide a separate base_url / api_key configuration for lightweight tasks; the only configuration knob is the model id.

#### Scenario: Title generator routes to deepseek-v4-flash on DeepSeek

- **WHEN** `settings.anthropic_provider == "deepseek"`, `settings.anthropic_small_fast_model == None`, and `title_generator_service.summarize_user_message(...)` is invoked
- **THEN** the underlying `build_options(...)` call passes `model="deepseek-v4-flash"` (from `PROVIDER_PROFILES["deepseek"].default_small_fast_model`)
- **AND** `options.env["ANTHROPIC_API_KEY"]` equals the same key used by DeviceAgent and LogAnalysisAgent
- **AND** `options.env["ANTHROPIC_BASE_URL"] == "https://api.deepseek.com/anthropic"`

#### Scenario: ANTHROPIC_SMALL_FAST_MODEL env override wins

- **WHEN** `ANTHROPIC_PROVIDER=deepseek` and `ANTHROPIC_SMALL_FAST_MODEL=deepseek-v4-flash-preview` are set
- **THEN** `title_generator_service` invocations resolve `model="deepseek-v4-flash-preview"` (Settings beats profile default)

#### Scenario: No separate lightweight base_url / api_key configuration exists

- **WHEN** an operator inspects `app/config.py.Settings`
- **THEN** no `llm_light_*` field exists (specifically: `llm_light_model_name`, `llm_light_base_url`, `llm_light_api_key`, `llm_light_temperature` are absent)
- **AND** no `app/services/light_llm_service.py` module exists
- **AND** the only lightweight-task configuration surface is `anthropic_small_fast_model` (and the supporting `anthropic_small_fast_max_tokens` / `anthropic_small_fast_request_timeout_seconds`)

### Requirement: Conversational agents may request the `default` permission mode

The system SHALL permit callers to pass `permission_mode="default"` to `build_options(...)` and SHALL forward that value to `ClaudeAgentOptions.permission_mode`. Together with a registered `can_use_tool` callback, this mode enables interactive human-in-the-loop review for conversational agents (e.g., DeviceAgent) without disabling tool-use entirely.

#### Scenario: default mode + callback forwarded together

- **WHEN** a caller invokes `build_options(..., permission_mode="default", can_use_tool=cb)`
- **THEN** the returned `ClaudeAgentOptions.permission_mode == "default"` and `ClaudeAgentOptions.can_use_tool is cb`

## REMOVED Requirements

### Requirement: OpenAI-compatible configuration remains untouched

**Reason**: The new DeviceAgent replaces the LangGraph ChatAgent, which was the only remaining consumer of the OpenAI-compatible `Settings` fields. The `rebuild-chat-agent-as-device-agent-with-claude-agent-sdk` change deletes `app/agents/chat_agent.py` and the "primary model" runtime overrides; the OpenAI-compatible config fields (`openai_api_key`, `openai_base_url`, `deepseek_api_key`, `deepseek_base_url`, `llm_model_name`, `llm_reasoning_model`, `llm_temperature`, `llm_provider`) are removed when no other code references them.

**Migration**: All Anthropic-backed agents (LogAnalysisAgent, DeviceAgent, and the new chat-title generator) consume `ANTHROPIC_*` settings via `app/agents/anthropic_client.build_options`. Operators who previously set `OPENAI_API_KEY` for chat MUST set `ANTHROPIC_API_KEY` (and optionally `ANTHROPIC_PROVIDER`, `ANTHROPIC_MODEL`, `ANTHROPIC_BASE_URL`) before deploying this change. The admin "Model Settings" page no longer exposes a writable "primary model" form; the Anthropic configuration view is read-only.
