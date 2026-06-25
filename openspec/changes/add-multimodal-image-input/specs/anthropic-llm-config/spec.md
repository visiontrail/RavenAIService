## ADDED Requirements

### Requirement: Multimodal model configuration fields exist with safe defaults

The system SHALL define multimodal model settings on `app.config.Settings` — `anthropic_multimodal_provider`, `anthropic_multimodal_model`, `anthropic_multimodal_base_url`, `anthropic_multimodal_api_key`, `anthropic_multimodal_max_tokens`, and `anthropic_multimodal_request_timeout_seconds` — bound to the corresponding `ANTHROPIC_MULTIMODAL_*` environment variables. All fields SHALL be optional with safe defaults so that, when unset, application startup is unaffected and the multimodal capability is simply treated as unconfigured.

#### Scenario: Settings load without multimodal env vars

- **WHEN** no `ANTHROPIC_MULTIMODAL_*` environment variables are set
- **THEN** `Settings` loads without error and the multimodal model fields are `None` (or their numeric defaults)

#### Scenario: Settings honor ANTHROPIC_MULTIMODAL_* env vars

- **WHEN** `ANTHROPIC_MULTIMODAL_PROVIDER`, `ANTHROPIC_MULTIMODAL_MODEL`, `ANTHROPIC_MULTIMODAL_BASE_URL`, and `ANTHROPIC_MULTIMODAL_API_KEY` are set
- **THEN** the corresponding `anthropic_multimodal_*` settings reflect those values

### Requirement: build_options supports per-call api_key and base_url overrides

The `build_options` factory in `app/agents/anthropic_client.py` SHALL accept optional `api_key` and `base_url` parameters that override the primary `Settings`-derived values when building `ClaudeAgentOptions.env`, so a bypass caller (such as image understanding) can target a different upstream than the primary agent without mutating primary configuration. When the override parameters are omitted, behavior SHALL be unchanged.

#### Scenario: Override targets a different upstream

- **WHEN** `build_options(..., api_key="mm-key", base_url="https://mm.example/anthropic")` is called
- **THEN** the returned options `env` carries `ANTHROPIC_API_KEY == "mm-key"` and `ANTHROPIC_BASE_URL == "https://mm.example/anthropic"`
- **AND** the primary `settings.anthropic_api_key` / `anthropic_base_url` are not modified

#### Scenario: Omitting overrides preserves existing behavior

- **WHEN** `build_options(...)` is called without `api_key` or `base_url`
- **THEN** the returned options `env` is derived from primary `Settings` and provider profile exactly as before
