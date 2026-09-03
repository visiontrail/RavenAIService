## ADDED Requirements

### Requirement: Skill availability and invocation have distinct trace semantics

Lifecycle trace events SHALL use `available_skills` for the complete enabled Skill catalog associated with the selected Agent and project. This catalog SHALL be reported independently from the bounded subset materialized into the workspace. A Skill SHALL be considered actually loaded only when a `step_start` event invokes tool `Skill` with that Skill's name. New lifecycle notices SHALL use kind `skills_available`; a legacy `loaded_skills` lifecycle alias MAY be emitted temporarily for old clients but MUST NOT be interpreted as proof of invocation.

#### Scenario: One Skill invoked from a larger enabled catalog

- **WHEN** `run_start.available_skills` contains `ka-phased-array-antenna` and `lx10-telemetry`
- **AND** the trace contains one `step_start{tool_name:"Skill", tool_input:{skill:"ka-phased-array-antenna"}}`
- **THEN** the available set contains both names
- **AND** the actually loaded set contains only `ka-phased-array-antenna`

#### Scenario: Request filtering does not hide configured availability

- **WHEN** a project has seven enabled Skills
- **AND** request filtering materializes only `ka-phased-array-antenna`
- **THEN** `available_skills` contains all seven enabled Skill names
- **AND** only the materialized Skill is eligible to produce a `Skill` invocation

#### Scenario: Materialized Skill is never invoked

- **WHEN** a Skill appears in lifecycle availability metadata but no `Skill` step names it
- **THEN** the run MUST NOT report that Skill as actually loaded
