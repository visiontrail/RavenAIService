## ADDED Requirements

### Requirement: Agent materialization merges agent skills and project skills into a single .claude/skills/ directory

The system SHALL, when materializing skills for an agent run that has a project context, first materialize agent-level skills then materialize project-level skills into the same `<workspace>/.claude/skills/` directory. Both sets of skills SHALL be discoverable by the Claude Agent SDK via `setting_sources=["project"]`.

#### Scenario: Both agent and project skills materialized

- **WHEN** agent `project_expert` has enabled skill `general_code_review` AND project `"my_project"` has enabled skill `project_deploy_guide`
- **AND** a run starts for `project_expert` with project_code `"my_project"`
- **THEN** the workspace contains both `<workspace>/.claude/skills/general_code_review/SKILL.md` and `<workspace>/.claude/skills/project_deploy_guide/SKILL.md`

#### Scenario: No project context falls back to agent-only skills

- **WHEN** an agent run has no project_code (e.g. project_code is None or empty)
- **THEN** only agent-level skills are materialized
- **AND** behavior is identical to the current implementation

### Requirement: Project skills override same-named agent skills on conflict

The system SHALL, when a project skill has the same `name` as an agent skill, materialize the project skill, overwriting the previously materialized agent skill symlink/copy. The project skill takes precedence because it is more specific to the current context.

#### Scenario: Same-name skill resolved in favor of project

- **WHEN** agent `log_analysis` has enabled skill `debug_helper` AND project `"my_project"` also has enabled skill `debug_helper`
- **AND** a run starts for `log_analysis` with project_code `"my_project"`
- **THEN** `<workspace>/.claude/skills/debug_helper/SKILL.md` contains the content from the project skill, not the agent skill

### Requirement: Unified relevance scoring across both skill sources

The system SHALL combine enabled agent skills and enabled project skills into a single candidate pool for relevance scoring. The scoring algorithm (term extraction, weighted matching on name/description/body) SHALL be identical for both sources. The unified pool SHALL be ranked and truncated to `max_skills` (default 5).

#### Scenario: Mixed pool scored and ranked together

- **WHEN** agent `project_expert` has 3 enabled skills and project `"my_project"` has 2 enabled skills
- **AND** a query is submitted that matches one agent skill (score 12) and one project skill (score 18)
- **THEN** the project skill ranks higher and is materialized
- **AND** the total materialized count does not exceed `max_skills`

#### Scenario: No project skills does not affect agent skill scoring

- **WHEN** project `"my_project"` has zero enabled skills
- **THEN** the scoring pool contains only agent skills and the result is identical to the current behavior

### Requirement: Default max_skills increased from 3 to 5

The system SHALL increase the default `max_skills` parameter from 3 to 5 to accommodate the larger candidate pool from combined agent and project skills. The parameter SHALL remain overridable by callers.

#### Scenario: Default allows up to 5 skills materialized

- **WHEN** the combined pool has 8 relevant skills and the caller does not override max_skills
- **THEN** at most 5 skills are materialized

### Requirement: Materialization function accepts optional project_code parameter

The system SHALL extend `materialize_relevant_enabled_skills()` to accept an optional `project_code` parameter. When provided, the function SHALL include the project's enabled skills in the candidate pool. When not provided or None, the function SHALL behave identically to the current implementation.

#### Scenario: project_code passed triggers project skill loading

- **WHEN** `materialize_relevant_enabled_skills("log_analysis", target_dir, query_text="...", project_code="my_project")` is called
- **THEN** project skills for `"my_project"` are included in the scoring pool alongside `log_analysis` agent skills

#### Scenario: project_code omitted preserves backward compatibility

- **WHEN** `materialize_relevant_enabled_skills("log_analysis", target_dir, query_text="...")` is called without project_code
- **THEN** behavior is identical to the pre-change implementation (agent skills only)
