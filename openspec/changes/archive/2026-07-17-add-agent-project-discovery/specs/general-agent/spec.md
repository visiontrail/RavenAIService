## ADDED Requirements

### Requirement: GeneralAgent uses the project catalog for project recommendations
When a user asks a project-bound question through GeneralAgent, GeneralAgent SHALL call `mcp__project_repo__discover_projects` before naming a registered project or asserting that no project fits. It SHALL still recommend the appropriate specialized Agent, and SHALL include the matching project name/code when catalog evidence is clear.

#### Scenario: GeneralAgent recommends a concrete project and Agent
- **WHEN** a source-code question clearly matches one enabled project card
- **THEN** GeneralAgent tells the user to use ProjectExpertAgent with that project name/code
- **AND** its structured `suggested_agent_type` remains `project_expert`

#### Scenario: GeneralAgent reports no suitable project
- **WHEN** a project-bound question matches no card in the complete discovery response
- **THEN** GeneralAgent says no suitable project is currently registered
- **AND** it does not invent a project or answer the domain question

#### Scenario: Discovery is unavailable
- **WHEN** the configured provider cannot register the discovery tool
- **THEN** GeneralAgent falls back to specialized-Agent routing without naming a concrete project
- **AND** it does not claim that the project catalog has no match
