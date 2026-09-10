## ADDED Requirements

### Requirement: Source-controlled mandatory writing skill
The service SHALL bundle the full pinned Humanizer-zh source, license and integration prompt for log_analysis and project_expert, available with empty runtime data directories and without network downloads.

#### Scenario: Fresh deployment
- **WHEN** either Agent starts with no uploaded skills
- **THEN** humanizer-zh is materialized and its complete rules are included in the final system prompt

### Requirement: Every-run loading independent of relevance
The service MUST load the required skill on every invocation, including follow-up turns, outside optional relevance selection and its limits. Uploaded same-name skills MUST NOT replace the required source. A missing or invalid required package MUST prevent a model invocation.

#### Scenario: Unrelated short follow-up
- **WHEN** the user asks a short question without writing-related keywords in a reused workspace
- **THEN** the required skill is freshly loaded and does not consume optional skill capacity

#### Scenario: Required package unavailable
- **WHEN** the required skill cannot be read or materialized
- **THEN** the Agent fails before querying the model and does not silently continue

### Requirement: Truthful loading evidence and response contracts
The service SHALL emit an actual server-side loading event with the skill name, digest and load method. The integration prompt MUST retain facts, evidence, code, numbers, references, uncertainty, locale and structured output. A required style skill alone MUST NOT activate plain-text result fallback.

#### Scenario: Model request and trace
- **WHEN** an Agent sends its first model request
- **THEN** the full writing rules and technical constraints are present and a server_prompt load event identifies their digest without claiming a model tool call

#### Scenario: Invalid structured response
- **WHEN** a model returns plain text with only the required writing skill loaded
- **THEN** the existing structured response validation remains enforced
