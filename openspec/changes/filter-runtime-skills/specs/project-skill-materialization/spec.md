## MODIFIED Requirements

### Requirement: Agent materialization merges selected agent skills and project skills into a single .claude/skills/ directory

The system SHALL build one enabled candidate pool from Agent-level and project-level Skills, select only request-relevant candidates, then materialize the selected Agent Skills followed by selected project Skills into `<workspace>/.claude/skills/`. Only selected Skills SHALL be discoverable by the Claude Agent SDK via `setting_sources=["project"]`.

#### Scenario: Relevant skills from both levels are materialized

- **WHEN** an Agent-level Skill and a project-level Skill both have positive evidence in the request
- **AND** the selection bound allows both candidates
- **THEN** both Skills are materialized into the workspace
- **AND** unrelated enabled Skills are absent

#### Scenario: No project context falls back to agent-only candidates

- **WHEN** an agent run has no `project_code`
- **THEN** only enabled Agent-level Skills are considered
- **AND** only positively matched candidates are materialized

### Requirement: Unified relevance scoring across both skill sources

The system SHALL combine enabled Agent Skills and enabled project Skills into a single de-duplicated candidate pool for relevance scoring. It SHALL score request evidence against Skill name, description and a bounded portion of `SKILL.md`, weight name/description evidence above body-only evidence, and rank candidates deterministically. Terms common to many candidates SHALL contribute less evidence than candidate-specific terms.

#### Scenario: Mixed pool is ranked together

- **WHEN** one project Skill has stronger request-specific evidence than an Agent Skill
- **THEN** the project Skill ranks higher
- **AND** both may be selected only if each has positive evidence and the selection bound allows it

#### Scenario: No positive evidence selects no optional skill

- **WHEN** the request and attachment evidence has no positive match with any enabled candidate
- **THEN** no Skill is materialized
- **AND** the system MUST NOT fall back to all enabled Skills

#### Scenario: Attachment suffix selects format skill

- **WHEN** the request includes an attachment filename ending in `.xlsx`
- **THEN** an enabled `xlsx` Skill receives strong positive evidence
- **AND** an unrelated enabled `docx` Skill receives no evidence from that suffix

### Requirement: Default max_skills is three

The system SHALL limit relevance selection to at most three Skills by default. The parameter SHALL remain overridable by callers.

#### Scenario: Default truncates a broad relevant pool

- **WHEN** five enabled Skills have positive evidence and the caller does not override `max_skills`
- **THEN** at most the three highest-ranked Skills are materialized

### Requirement: Materialization function accepts request evidence and optional project_code

The system SHALL provide `materialize_relevant_enabled_skills()` with `query_text`, optional `project_code`, and overridable `max_skills` parameters. When `project_code` is provided, the function SHALL include that project's enabled Skills; otherwise it SHALL consider only Agent-level Skills.

#### Scenario: Project context includes project candidates

- **WHEN** `materialize_relevant_enabled_skills("log_analysis", target_dir, query_text="Ka接收天线波束异常", project_code="my_project")` is called
- **THEN** matching project Skills are considered alongside matching Agent Skills

#### Scenario: Omitted project context remains agent-only

- **WHEN** the same function is called without `project_code`
- **THEN** project Skill registries are not considered

