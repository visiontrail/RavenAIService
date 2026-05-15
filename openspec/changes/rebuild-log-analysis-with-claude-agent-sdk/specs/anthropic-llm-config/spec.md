## ADDED Requirements

### Requirement: Anthropic configuration fields exist with safe defaults and provider selector

The system SHALL expose an Anthropic-standard LLM configuration group in `app/config.Settings` containing at minimum: `anthropic_provider`, `anthropic_api_key`, `anthropic_base_url`, `anthropic_model`, `anthropic_small_fast_model`, `anthropic_max_tokens`, `anthropic_max_turns`, `anthropic_permission_mode`, and `anthropic_request_timeout_seconds`. Defaults SHALL NOT include any secret values; `anthropic_api_key` MUST default to `None`. `anthropic_base_url` and `anthropic_model` MUST default to `None` and be resolved from the provider profile at use time. `anthropic_provider` SHALL accept the values `"anthropic"`, `"deepseek"`, and `"custom"`.

#### Scenario: Settings load without ANTHROPIC_API_KEY

- **WHEN** the process starts with no `ANTHROPIC_API_KEY` env var set
- **THEN** `Settings()` instantiates without error and `settings.anthropic_api_key` equals `None`
- **AND** non-Anthropic features (existing OpenAI-compatible flows) continue to operate

#### Scenario: Settings honor ANTHROPIC_* env vars

- **WHEN** env vars `ANTHROPIC_PROVIDER=deepseek`, `ANTHROPIC_API_KEY=sk-test`, and `ANTHROPIC_MAX_TURNS=42` are set
- **THEN** `settings.anthropic_provider == "deepseek"`, `settings.anthropic_api_key == "sk-test"`, and `settings.anthropic_max_turns == 42`

#### Scenario: Invalid provider value rejected at load time

- **WHEN** env var `ANTHROPIC_PROVIDER=foo` is set
- **THEN** `Settings()` raises a validation error naming the allowed values

### Requirement: Provider profiles supply defaults and a capability matrix

The system SHALL define a registry of provider profiles in `app/agents/anthropic_client.py` keyed by `anthropic_provider`. Each profile SHALL declare at minimum: `default_base_url`, `default_model`, `default_small_fast_model`, `supports_image_input`, `supports_document_input`, `supports_mcp_server_tools`, `thinking_budget_tokens_effective`, and `disable_parallel_tool_use_effective`. The registry SHALL contain entries for `anthropic` and `deepseek`. The `deepseek` profile SHALL set `default_base_url = "https://api.deepseek.com/anthropic"`, `default_model = "deepseek-v4-pro"`, and SHALL mark `supports_image_input`, `supports_document_input`, `supports_mcp_server_tools`, `thinking_budget_tokens_effective`, and `disable_parallel_tool_use_effective` as `False`.

#### Scenario: DeepSeek profile exposes correct defaults

- **WHEN** application code reads `PROVIDER_PROFILES["deepseek"]`
- **THEN** `default_base_url == "https://api.deepseek.com/anthropic"` and `default_model == "deepseek-v4-pro"`
- **AND** `supports_image_input == False` and `thinking_budget_tokens_effective == False`

#### Scenario: Anthropic profile exposes correct defaults

- **WHEN** application code reads `PROVIDER_PROFILES["anthropic"]`
- **THEN** `default_base_url == "https://api.anthropic.com"` and `supports_image_input == True`

#### Scenario: Custom provider requires explicit base_url and model

- **WHEN** `anthropic_provider == "custom"` and `anthropic_base_url` or `anthropic_model` is missing
- **THEN** `assert_anthropic_configured()` raises `AnthropicConfigurationError` naming the missing field

### Requirement: Anthropic client factory builds ClaudeAgentOptions, resolves provider, and validates configuration

The system SHALL provide a module `app/agents/anthropic_client.py` exposing (a) `assert_anthropic_configured()` which raises a typed configuration error when `anthropic_api_key` is missing or when `anthropic_provider == "custom"` lacks `base_url`/`model`, and (b) `build_options(*, system_prompt, allowed_tools, cwd, max_turns=None, permission_mode=None, add_dirs=None, requires_image_input=False, requires_document_input=False, thinking_budget_tokens=None) -> ClaudeAgentOptions` which produces a `ClaudeAgentOptions` instance populated by merging caller overrides, `Settings` values, and the active provider profile in that precedence order. The returned options SHALL include `model` set to the effective model id and `env` containing `ANTHROPIC_API_KEY` and `ANTHROPIC_BASE_URL` derived from configuration.

#### Scenario: build_options requires API key

- **WHEN** `anthropic_api_key` is `None` and a caller invokes `build_options(...)`
- **THEN** the call raises an `AnthropicConfigurationError` referencing the missing setting
- **AND** no network call is made

#### Scenario: build_options applies precedence

- **WHEN** `settings.anthropic_provider == "deepseek"`, `settings.anthropic_max_turns == 30`, `settings.anthropic_model == None`, and caller invokes `build_options(system_prompt="s", allowed_tools=["Bash"], cwd="/tmp/x", max_turns=10)`
- **THEN** the returned `ClaudeAgentOptions` has `max_turns == 10`, `system_prompt == "s"`, `cwd == "/tmp/x"`, `allowed_tools == ["Bash"]`, and `model == "deepseek-v4-pro"` (from the DeepSeek profile)
- **AND** `options.env["ANTHROPIC_BASE_URL"] == "https://api.deepseek.com/anthropic"`

#### Scenario: build_options honors caller override over Settings over profile

- **WHEN** `settings.anthropic_provider == "deepseek"` and `settings.anthropic_model == "deepseek-v4-flash"` and the caller passes no `model` override
- **THEN** the returned `model == "deepseek-v4-flash"` (Settings beats profile default)

### Requirement: Provider capability checks fail fast for unsupported features

The system SHALL refuse to build options when the caller requests a feature the active provider profile marks as unsupported. Image and document input requests against profiles with `supports_image_input == False` or `supports_document_input == False` MUST raise `ProviderCapabilityError`. MCP server tools MUST NOT be registered with profiles whose `supports_mcp_server_tools == False`. Requests setting `thinking_budget_tokens` against a profile where `thinking_budget_tokens_effective == False` SHALL log a WARNING and omit the parameter from `ClaudeAgentOptions`.

#### Scenario: Image input rejected on DeepSeek

- **WHEN** `anthropic_provider == "deepseek"` and a caller invokes `build_options(..., requires_image_input=True)`
- **THEN** the call raises `ProviderCapabilityError` naming `supports_image_input`
- **AND** no `ClaudeAgentOptions` is returned

#### Scenario: thinking budget silently dropped on DeepSeek with WARNING

- **WHEN** `anthropic_provider == "deepseek"` and a caller invokes `build_options(..., thinking_budget_tokens=4096)`
- **THEN** the returned `ClaudeAgentOptions` does not include any `thinking.budget_tokens` parameter
- **AND** a WARNING log entry is emitted naming the active provider and the dropped parameter

### Requirement: Effective model and base_url are recorded on every agent run

The system SHALL record the effective `model` and `base_url` actually used for each agent invocation (after profile/Settings/override resolution) so that operators can detect silent fallbacks (e.g., DeepSeek's automatic fallback to `deepseek-v4-flash` for unknown model ids). The value SHALL be persisted into the log analysis result and emitted in INFO-level logs at the start of every run.

#### Scenario: Result includes effective model

- **WHEN** an agent run completes via the DeepSeek profile with `settings.anthropic_model == None`
- **THEN** `LogRecord.ai_analysis_result.model == "deepseek-v4-pro"`
- **AND** logs include a startup line containing `provider=deepseek model=deepseek-v4-pro base_url=https://api.deepseek.com/anthropic`

### Requirement: OpenAI-compatible configuration remains untouched

The system SHALL retain the existing OpenAI-compatible configuration fields (`deepseek_api_key`, `deepseek_base_url`, `llm_model_name`, `llm_reasoning_model`, `llm_temperature`, `llm_provider`) and their behavior so that `app/agents/chat_agent.py` and `app/services/ai_chat_service.py` continue to function without changes in this change.

#### Scenario: Existing chat agent still resolves its model

- **WHEN** `ai_chat_service.ChatAgent` is instantiated after this change is deployed
- **THEN** it reads the OpenAI-compatible settings unchanged and operates as before
- **AND** Anthropic settings are not consulted by it
