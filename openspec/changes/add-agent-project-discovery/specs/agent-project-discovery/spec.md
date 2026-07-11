## ADDED Requirements

### Requirement: Agents can safely discover the enabled project catalog
The system SHALL provide an in-process MCP tool named `mcp__project_repo__discover_projects` that returns every enabled project up to the configured catalog bound. Each entry SHALL contain only `id`, `project_code`, `project_name`, `project_card`, `has_repo`, and `enabled_agent_keys`. The tool MUST NOT return repository URLs, clone URLs, tokens, authentication state, members, disabled projects, or any other admin-only field.

#### Scenario: Discovery returns safe project cards
- **WHEN** an Agent calls `discover_projects` and two enabled projects plus one disabled project exist
- **THEN** the response contains the two enabled projects with their complete project cards and Agent bindings
- **AND** the disabled project and all repository credential fields are absent

#### Scenario: Empty registry is explicit
- **WHEN** an Agent calls `discover_projects` and no enabled project exists
- **THEN** the response contains an empty `projects` list and a zero count
- **AND** the response does not synthesize a default project

### Requirement: Relevant user-facing Agents share project discovery
GeneralAgent, ProjectExpertAgent, and LogAnalysisAgent SHALL allow `mcp__project_repo__discover_projects` when the configured provider supports in-process MCP tools. GeneralAgent MUST NOT allow the credential-bearing `mcp__project_repo__lookup_project_repo`; ProjectExpertAgent and LogAnalysisAgent SHALL retain their existing lookup permission.

#### Scenario: GeneralAgent receives discovery only
- **WHEN** GeneralAgent builds options for an MCP-capable provider
- **THEN** its allowed tools contain `mcp__project_repo__discover_projects`
- **AND** its allowed tools do not contain `mcp__project_repo__lookup_project_repo` or any filesystem/shell tool

#### Scenario: Project-bound Agents retain both tools
- **WHEN** ProjectExpertAgent or LogAnalysisAgent builds options for an MCP-capable provider
- **THEN** its allowed tools contain both `mcp__project_repo__discover_projects` and `mcp__project_repo__lookup_project_repo`

### Requirement: Project-fit decisions distinguish redirect, no-match, and uncertainty
An Agent that has project-catalog evidence SHALL compare the request with project cards. On a clear current-project mismatch it MUST stop using unrelated project context and accurately identify the mismatch. If exactly one or more cards clearly fit, it SHALL recommend the best matching registered project by name and code. If no card fits, it SHALL explicitly state that no suitable project is currently registered. If the evidence is ambiguous, it SHALL explain the ambiguity and MUST NOT invent a confident project match.

#### Scenario: A different registered project clearly matches
- **WHEN** the current project card covers antenna firmware and the request clearly concerns a billing service covered by another enabled project's card
- **THEN** the Agent does not answer from the antenna project context
- **AND** it names the billing project and tells the user how to select or start a session with it

#### Scenario: No registered card fits
- **WHEN** the Agent has read the complete enabled catalog and no project card covers the request
- **THEN** it explicitly tells the user that the system currently has no suitable project for the question
- **AND** it does not select the closest unrelated project or fabricate an answer

#### Scenario: Catalog evidence is unavailable
- **WHEN** the provider does not support MCP and the Agent cannot read the complete project catalog
- **THEN** the Agent may identify a clear mismatch with the selected project's persisted card
- **AND** it MUST NOT claim that a specific alternative exists or that no suitable project exists in the whole system
