## ADDED Requirements

### Requirement: General Agent prompts are editable through the shared prompt configuration

The system SHALL store GeneralAgent's localized system prompt and user prompt template under a dedicated `claude_agent_general` entry in `prompts_config.yaml`. GeneralAgent SHALL load the active locale at run time, and the existing admin prompt-management API/UI SHALL list and edit its system prompt without adding GeneralAgent to any project-level configuration surface.

#### Scenario: Admin edits GeneralAgent system prompt

- **WHEN** an administrator saves a changed `claude_agent_general.generic.system_prompt` language body
- **THEN** the prompt configuration is persisted and the GeneralAgent prompt cache is invalidated
- **AND** the next GeneralAgent run uses the updated body

#### Scenario: Locale selects the GeneralAgent prompt body

- **WHEN** a GeneralAgent run has locale `en`
- **THEN** the English system and user prompt bodies are selected with the standard default-language fallback
- **AND** the response-language directive is appended after configured and runtime prompt layers

#### Scenario: Prompt editor is not project configuration

- **WHEN** an administrator opens project-level Agent prompt configuration
- **THEN** GeneralAgent is not offered as a project-scoped prompt target
