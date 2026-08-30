## MODIFIED Requirements

### Requirement: Relevant user-facing Agents share project discovery
GeneralAgent, ProjectExpertAgent, and LogAnalysisAgent SHALL allow `mcp__project_repo__discover_projects` when the configured provider supports in-process MCP tools. GeneralAgent MUST NOT register or allow the credential-bearing `mcp__project_repo__lookup_project_repo`, the workspace-mutating `mcp__project_repo__clone_project_repo`, or any filesystem/shell tool. ProjectExpertAgent and LogAnalysisAgent SHALL retain lookup permission and SHALL additionally receive the workspace-bound clone tool.

#### Scenario: GeneralAgent receives discovery only
- **WHEN** GeneralAgent builds options for an MCP-capable provider
- **THEN** its allowed tools contain `mcp__project_repo__discover_projects`
- **AND** its allowed tools do not contain `mcp__project_repo__lookup_project_repo`, `mcp__project_repo__clone_project_repo`, or any filesystem/shell tool

#### Scenario: Project-bound Agents receive discovery, lookup, and clone
- **WHEN** ProjectExpertAgent or LogAnalysisAgent builds options for an MCP-capable provider
- **THEN** its allowed tools contain `mcp__project_repo__discover_projects`, `mcp__project_repo__lookup_project_repo`, and `mcp__project_repo__clone_project_repo`
- **AND** the clone tool is bound to that run's workspace and Agent key

### Requirement: Project-fit decisions distinguish redirect, no-match, and uncertainty
An Agent that has project-catalog evidence SHALL compare the request with project cards. ProjectExpertAgent and LogAnalysisAgent SHALL recover from a clear current-project mismatch by cloning and inspecting the best matching registered project inside the current workspace, and SHALL clone multiple materially required projects for a joint investigation. If no card fits, the Agent SHALL explicitly state that no suitable project is currently registered. If the evidence is ambiguous, it SHALL explain the ambiguity and MUST NOT invent a confident project match or clone unrelated repositories.

#### Scenario: A different registered project clearly matches
- **WHEN** the current project card is unrelated and one other enabled card clearly matches the request
- **THEN** the project-bound Agent calls `clone_project_repo` for the matching project and inspects the returned checkout
- **AND** it answers from that project's code without treating the unrelated selected project as evidence

#### Scenario: Multiple registered projects are jointly required
- **WHEN** the request crosses responsibilities covered by two or more enabled project cards
- **THEN** the project-bound Agent clones only the additional materially required repositories
- **AND** its answer distinguishes and cites evidence from each repository path

#### Scenario: No registered card fits
- **WHEN** the Agent has read the complete enabled catalog and no project card covers the request
- **THEN** it explicitly tells the user that the system currently has no suitable project for the question
- **AND** it does not select the closest unrelated project, clone it, or fabricate an answer

#### Scenario: Catalog evidence is unavailable
- **WHEN** the provider does not support MCP and the Agent cannot read the complete project catalog
- **THEN** the Agent may identify a clear mismatch with the selected project's persisted card
- **AND** it MUST NOT claim multi-project analysis, a specific alternative, or absence of a suitable project in the whole system
