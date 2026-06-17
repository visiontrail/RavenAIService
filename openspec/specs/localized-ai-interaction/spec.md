## ADDED Requirements

### Requirement: Per-language prompt templates

Prompt definitions in `prompts_config.yaml` SHALL provide a body for each supported language (`zh`, `en`) for every prompt that produces or shapes user-facing AI output (the log-analysis, device, project-expert, package-search, and general agents, and the chat session-title prompt). When a language variant is missing for a prompt, the loader SHALL fall back to the default `zh` body.

#### Scenario: Loader selects the requested language body

- **WHEN** an agent loads its system/user prompt with locale `en`
- **THEN** the loader SHALL return the English prompt body for that agent

#### Scenario: Missing variant falls back

- **WHEN** an agent loads a prompt with locale `en` but only a `zh` body is defined for that prompt
- **THEN** the loader SHALL return the `zh` body rather than failing

### Requirement: Active locale passed into every agent run

The resolved request locale SHALL be threaded from the API/task entry point through to each agent run and the chat-title generation, so prompt selection and the response-language directive use the caller's language. Background tasks that act on a user's behalf SHALL use that user's stored language.

#### Scenario: Chat request carries locale to the agent

- **WHEN** a user in English locale sends a message that triggers an agent run
- **THEN** the agent run SHALL be invoked with locale `en` and SHALL select English prompts

#### Scenario: Async analysis uses owner language

- **WHEN** a log-analysis task runs in the background for a log owned by an English-preference user
- **THEN** the agent SHALL run with locale `en`

### Requirement: Model responds in the active language

Every prompt that yields user-facing AI output SHALL instruct the model to respond in the active language. The AI's returned content — analysis reports, chat answers, and generated session titles — SHALL be in the selected language regardless of the language of the input data (logs, source code, device output) it analyzes.

#### Scenario: English answer over Chinese input data

- **WHEN** a user in English locale asks a question about logs that contain Chinese text
- **THEN** the model's answer SHALL be written in English

#### Scenario: Localized session title

- **WHEN** a session title is generated for a conversation while the user's locale is `en`
- **THEN** the generated title SHALL be in English

#### Scenario: Chinese remains correct

- **WHEN** a user in `zh` locale runs any agent
- **THEN** prompts and the model's answer SHALL be in Chinese, matching today's behavior

### Requirement: Admin prompt editing is per-language

The admin prompt management API and UI SHALL allow viewing and editing each prompt's `zh` and `en` bodies independently, and SHALL persist them back into the per-language structure of `prompts_config.yaml`.

#### Scenario: Editing one language preserves the other

- **WHEN** an admin edits the English body of a prompt and saves
- **THEN** the system SHALL persist the updated English body and leave the `zh` body unchanged

#### Scenario: Cache invalidation after edit

- **WHEN** an admin saves a prompt change
- **THEN** subsequent agent runs SHALL load the updated per-language body (the in-memory prompt cache SHALL be invalidated)
