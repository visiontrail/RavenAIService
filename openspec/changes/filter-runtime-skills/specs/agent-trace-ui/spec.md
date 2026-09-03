## ADDED Requirements

### Requirement: Trace UI distinguishes available and actually loaded Skills

The trace UI SHALL render selected/materialized candidates under “Available Skills” and actual `Skill` tool invocations under “Loaded Skills”. It SHALL derive loaded Skills only from `step_start(tool_name="Skill")`. For historical traces, lifecycle `loaded_skills` and `system_notice(kind="skills_loaded")` SHALL be treated as availability metadata rather than invocation evidence.

#### Scenario: Unused candidates are not labeled loaded

- **WHEN** a trace advertises three available Skills but invokes only one through the `Skill` tool
- **THEN** the available row shows all three candidates
- **AND** the loaded row shows only the invoked Skill

#### Scenario: Historical trace remains understandable

- **WHEN** a persisted historical trace contains lifecycle `loaded_skills` but no `available_skills`
- **THEN** those names appear under “Available Skills”
- **AND** “Loaded Skills” remains absent unless the trace contains a `Skill` step

