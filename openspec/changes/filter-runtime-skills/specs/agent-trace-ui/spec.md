## ADDED Requirements

### Requirement: Trace UI distinguishes available and actually loaded Skills

The trace UI SHALL make the full configured/enabled Agent/project catalog available under “Available Skills” and render actual `Skill` tool invocations under “Loaded Skills”. The available catalog SHALL be collapsed by default and expandable on demand. The UI SHALL derive loaded Skills only from `step_start(tool_name="Skill")`. Request filtering and materialization SHALL NOT reduce the available catalog. For historical traces, lifecycle `loaded_skills` and `system_notice(kind="skills_loaded")` SHALL be treated as availability metadata rather than invocation evidence.

#### Scenario: Unused configured Skills are not labeled loaded

- **WHEN** a trace advertises all configured Skills but invokes only one through the `Skill` tool
- **THEN** the available row is collapsed by default and indicates its item count
- **AND** expanding it shows all three configured Skills
- **AND** the loaded row shows only the invoked Skill

#### Scenario: Historical trace remains understandable

- **WHEN** a persisted historical trace contains lifecycle `loaded_skills` but no `available_skills`
- **THEN** those names appear under “Available Skills”
- **AND** “Loaded Skills” remains absent unless the trace contains a `Skill` step
