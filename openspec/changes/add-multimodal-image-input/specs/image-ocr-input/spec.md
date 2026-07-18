## ADDED Requirements

### Requirement: Independent OCR model configuration is resolvable

The system SHALL expose an OCR/vision model configuration that is independent of the primary agent model, sourced from environment settings `OCR_ENABLED`, `OCR_PROVIDER`, `OCR_BASE_URL`, `OCR_API_KEY`, `OCR_MODEL`, `OCR_MAX_TOKENS`, `OCR_REQUEST_TIMEOUT_SECONDS`, `OCR_MAX_IMAGES`, and `OCR_MAX_IMAGE_MB`. The OCR service SHALL report itself as "configured" only when `OCR_ENABLED` is true AND `OCR_API_KEY`, `OCR_MODEL`, and `OCR_BASE_URL` are all present. The configuration MUST NOT depend on or alter the primary `anthropic_*` model settings.

#### Scenario: OCR configured

- **WHEN** `OCR_ENABLED` is true and `OCR_API_KEY`, `OCR_MODEL`, and `OCR_BASE_URL` are set
- **THEN** `ocr_service.is_configured()` returns true
- **AND** the resolved endpoint/model/key are independent of `anthropic_model` / `anthropic_api_key`

#### Scenario: OCR unconfigured when key missing

- **WHEN** `OCR_API_KEY` is not set
- **THEN** `ocr_service.is_configured()` returns false

#### Scenario: OCR explicitly disabled

- **WHEN** `OCR_ENABLED` is false even though a key and model are set
- **THEN** `ocr_service.is_configured()` returns false

### Requirement: OCR service converts images to text via an OpenAI-compatible endpoint

The system SHALL provide `app/services/ocr_service.py` that, given one or more image attachments plus the current user text, issues exactly one OpenAI-compatible `POST {OCR_BASE_URL}/chat/completions` request (authorized with `OCR_API_KEY`) whose user message content contains an instruction/question text block followed by one `image_url` data-URL block per image, and returns the model's extracted text. The instruction SHALL direct the model to transcribe visible text and briefly describe visual facts relevant to the user's question, to state only objective facts, and to not execute any instructions appearing inside the images.

#### Scenario: Successful text extraction

- **WHEN** `extract_text` is called with image attachments and OCR is configured
- **THEN** it sends the instruction text and per-image `image_url` data-URL blocks to the OCR endpoint
- **AND** returns the concatenated recognized text with status "succeeded"

#### Scenario: User text steers the extraction

- **WHEN** the current user text accompanies the image(s)
- **THEN** the instruction sent to the OCR model includes that text so the description focuses on details relevant to it

#### Scenario: Best-effort failure does not raise

- **WHEN** the OCR request times out, returns a non-2xx status, or errors
- **THEN** the service returns status "failed" with an error kind and empty text rather than raising
- **AND** records an AI-usage metric with `source="ocr"` and a failed status

#### Scenario: Usage is metered on success

- **WHEN** an OCR call completes successfully
- **THEN** the service records an AI-usage metric with `source="ocr"`, `provider=OCR_PROVIDER`, `model=OCR_MODEL`, and a succeeded status

### Requirement: Image attachments are validated before OCR

The system SHALL validate image attachments against a MIME whitelist (png, jpeg, webp, gif), a per-image size limit (`OCR_MAX_IMAGE_MB`), and a per-turn count limit (`OCR_MAX_IMAGES`). Attachments exceeding these limits SHALL be rejected with an explicit error (mapped to a 4xx at the API boundary) rather than silently dropped.

#### Scenario: Reject unsupported type

- **WHEN** an attachment's `media_type` is not in the whitelist
- **THEN** validation fails with an explicit unsupported-type error

#### Scenario: Reject oversize or too-many images

- **WHEN** a single image exceeds `OCR_MAX_IMAGE_MB` or the number of images exceeds `OCR_MAX_IMAGES`
- **THEN** validation fails with an explicit size/count error

### Requirement: OCR text is merged into the user prompt for any agent

When a chat turn carries images and OCR is configured, the system SHALL run OCR before the agent starts and SHALL merge the extracted text into the user message as a delimited `<user_image_ocr>` block appended after the original text, so that any agent (project expert, log analysis, package search, device, general) receives the enriched text through its existing message field with no change to the agent or its prompt rendering. No raw image content block SHALL be sent to any agent.

#### Scenario: Merged before the agent runs

- **WHEN** a request to any agent entry point carries images and OCR is configured
- **THEN** OCR runs first and the agent receives a user message containing the recognized text inside a `<user_image_ocr>` block appended after the original message
- **AND** no raw image bytes are passed to the agent

#### Scenario: OCR block is framed as untrusted material

- **WHEN** the recognized text is merged into the user message
- **THEN** the `<user_image_ocr>` block is annotated as user-supplied material/data describing the images, not as instructions to execute

#### Scenario: Applies uniformly across agents

- **WHEN** the active agent is project expert, log analysis, package search, device, or general
- **THEN** the same OCR-merge preprocessing is applied at that agent's entry point

### Requirement: Graceful degradation when images cannot be recognized

The system SHALL NOT block or fail a conversation turn solely because images were attached. When OCR is unconfigured or extraction fails/times out, the turn SHALL proceed on the original text only and the user SHALL be informed that the attached images were not recognized.

#### Scenario: OCR unconfigured

- **WHEN** a request carries images but `ocr_service.is_configured()` is false
- **THEN** the turn proceeds using only the original text message
- **AND** the user is told the images were not recognized because the OCR model is not configured

#### Scenario: OCR failed or timed out

- **WHEN** OCR returns a failed status for an image-bearing turn
- **THEN** the agent still answers using the original text message
- **AND** the user is told the images could not be recognized this turn

### Requirement: Merged text is persisted, raw images are not

The system SHALL persist the user turn as the merged message text (including the `<user_image_ocr>` block) so later turns retain context without re-uploading images, and SHALL NOT persist raw image bytes in conversation history.

#### Scenario: History retains recognized text

- **WHEN** an image-bearing turn completes
- **THEN** conversation history records the merged user message containing the recognized text
- **AND** no base64 image bytes are stored in the history record

#### Scenario: Follow-up turn reuses prior recognition

- **WHEN** a subsequent turn in the same session is sent without re-attaching the image
- **THEN** the previously stored recognized text is available in history context without resending image bytes
