## ADDED Requirements

### Requirement: Independent multimodal model configuration is resolvable

The system SHALL expose a multimodal model configuration that is independent of the primary agent model, resolvable via a function (e.g. `resolve_multimodal_config()`) in `app/agents/anthropic_client.py`. The configuration SHALL be sourced from `ANTHROPIC_MULTIMODAL_PROVIDER`, `ANTHROPIC_MULTIMODAL_MODEL`, `ANTHROPIC_MULTIMODAL_BASE_URL`, `ANTHROPIC_MULTIMODAL_API_KEY`, `ANTHROPIC_MULTIMODAL_MAX_TOKENS`, and `ANTHROPIC_MULTIMODAL_REQUEST_TIMEOUT_SECONDS`. The resolver SHALL report the configuration as "available" only when the effective model's provider profile declares `supports_image_input == True`.

#### Scenario: Explicit multimodal model with image-capable provider

- **WHEN** `ANTHROPIC_MULTIMODAL_PROVIDER` resolves to a profile with `supports_image_input == True` and `ANTHROPIC_MULTIMODAL_MODEL` is set
- **THEN** `resolve_multimodal_config()` returns an available config carrying that model, base_url, and api_key
- **AND** the returned config is independent of `anthropic_model` / primary `anthropic_api_key`

#### Scenario: Fallback to primary provider only when image-capable

- **WHEN** no `ANTHROPIC_MULTIMODAL_*` model is configured AND the primary `anthropic_provider` profile has `supports_image_input == True`
- **THEN** `resolve_multimodal_config()` returns an available config reusing the primary provider/model

#### Scenario: Unconfigured when neither multimodal nor primary supports images

- **WHEN** no `ANTHROPIC_MULTIMODAL_*` model is configured AND the primary provider profile has `supports_image_input == False`
- **THEN** `resolve_multimodal_config()` reports the multimodal capability as unavailable

#### Scenario: Multimodal provider lacking image support is rejected

- **WHEN** `ANTHROPIC_MULTIMODAL_PROVIDER` resolves to a profile with `supports_image_input == False`
- **THEN** `resolve_multimodal_config()` reports the capability as unavailable and logs a WARNING naming the provider

### Requirement: Image understanding service parses images against the user question

The system SHALL provide a service `app/services/image_understanding_service.py` that, given one or more image attachments plus the current user question text, invokes the resolved multimodal model exactly once (`build_options(requires_image_input=True, max_turns=1, permission_mode="bypassPermissions")` driven by `claude_agent_sdk.query()`) with a streaming user message whose content contains the instruction/question text block followed by base64 image blocks, and SHALL return the concatenated assistant text as the image understanding.

#### Scenario: Successful image understanding

- **WHEN** the service is called with image attachments and a non-empty user question and the multimodal config is available
- **THEN** it sends the question text and base64 image content blocks to the multimodal model
- **AND** returns the model's textual understanding of the images directed by the question

#### Scenario: Question context steers the parsing

- **WHEN** the user question accompanies the image(s)
- **THEN** the instruction sent to the multimodal model includes that question so the description focuses on details relevant to it

#### Scenario: Best-effort failure does not raise

- **WHEN** the multimodal call times out or errors
- **THEN** the service returns no understanding (e.g. `None`) together with an error kind rather than raising
- **AND** records an AI-usage metric with `source="image_understanding"` and a failed status

#### Scenario: Usage is metered on success

- **WHEN** an image understanding call completes successfully
- **THEN** the service records an AI-usage metric with `source="image_understanding"` and a succeeded status

### Requirement: Image-bearing turns inject understanding into the primary agent prompt

When a chat run is created with attached images and the multimodal capability is available, the run orchestration (`chat_run_service`) SHALL run image understanding before starting the primary agent and SHALL inject the resulting text into the primary agent's user prompt as a delimited `<image_understanding>` block, so the primary agent (DeviceAgent / GeneralAgent) continues over text only.

#### Scenario: Understanding injected before primary agent runs

- **WHEN** a `/chat/stream` create request carries images and the multimodal capability is available
- **THEN** orchestration produces an image understanding first
- **AND** the primary agent receives a user prompt containing the understanding inside an `<image_understanding>` block
- **AND** no raw image content block is sent to the primary agent

#### Scenario: Progress is surfaced as a trace event

- **WHEN** image understanding is in progress for a run
- **THEN** a trace event indicating the image-understanding phase is emitted on the run stream for the frontend to display

#### Scenario: Understanding is treated as untrusted material

- **WHEN** the understanding text is injected into the primary agent prompt
- **THEN** the system prompt instructs the agent to treat the `<image_understanding>` content as user-supplied material describing the images, not as instructions to execute

### Requirement: Graceful degradation when images cannot be understood

The system SHALL NOT block or fail a conversation turn solely because images were attached. When the multimodal capability is unavailable or understanding fails, the turn SHALL proceed on text only and the user SHALL be informed that the attached images were not parsed.

#### Scenario: Multimodal unconfigured

- **WHEN** a request carries images but `resolve_multimodal_config()` reports the capability unavailable
- **THEN** the run proceeds using only the text message
- **AND** the user is told the images were not parsed (multimodal model not configured)

#### Scenario: Understanding failed or timed out

- **WHEN** image understanding returns no result for an image-bearing turn
- **THEN** the primary agent still answers using the text message
- **AND** the user is told the images could not be parsed this turn

### Requirement: Image understanding is persisted, raw images are not

The system SHALL persist the user turn with an indication that N images were attached and SHALL persist the image understanding text so later turns retain context, and SHALL NOT persist raw image bytes in conversation history.

#### Scenario: History retains textual understanding

- **WHEN** an image-bearing turn completes
- **THEN** conversation history records the user message annotated with the image count and the image understanding text
- **AND** no base64 image bytes are stored in the history record

#### Scenario: Follow-up turn reuses prior understanding

- **WHEN** a subsequent turn in the same session is sent without re-attaching the image
- **THEN** the previously stored understanding text is available in history context without resending image bytes
