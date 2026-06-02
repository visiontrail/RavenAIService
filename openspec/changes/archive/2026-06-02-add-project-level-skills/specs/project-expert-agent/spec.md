## MODIFIED Requirements

### Requirement: Project Expert supports Skill loading via the agent registry

The system SHALL register `project_expert` in `app/services/skills_service.SUPPORTED_AGENTS`. Before each `query()` run the agent SHALL materialize enabled skills for `project_expert` into `<workspace>/.claude/skills/<name>/` via `materialize_relevant_enabled_skills("project_expert", workspace_dir, query_text=..., project_code=<project_code>)` and SHALL set `setting_sources=["project"]` so the SDK auto-loads them. The admin Agent Skills page SHALL list `ProjectExpertAgent` in its agent dropdown without additional admin-code changes.

**Change**: The `materialize_relevant_enabled_skills` call SHALL now include the `project_code` parameter derived from the session's `ProjectRepo.project_code`. This causes project-level skills to be included in the candidate pool alongside agent-level skills. The `loaded_skills` field in trace events and the run result SHALL reflect all materialized skills regardless of source (agent or project).

#### Scenario: project_expert registered in SUPPORTED_AGENTS

- **WHEN** `skills_service.SUPPORTED_AGENTS` is inspected
- **THEN** it contains a `project_expert` entry with `framework == "Claude Agent SDK"`
- **AND** the admin agent dropdown (driven by `SUPPORTED_AGENTS`) includes `ProjectExpertAgent`

#### Scenario: Enabled skills materialized before the run

- **WHEN** a Project Expert run starts with one enabled agent skill `foo` and one enabled project skill `bar` for the session's project
- **THEN** `<workspace>/.claude/skills/foo/` and `<workspace>/.claude/skills/bar/` exist before the `query()` loop begins
- **AND** the agent is configured with `setting_sources=["project"]`

#### Scenario: Project skill overrides same-named agent skill

- **WHEN** agent `project_expert` has enabled skill `helper` and the session's project also has enabled skill `helper`
- **THEN** the materialized `<workspace>/.claude/skills/helper/SKILL.md` contains the project skill content

#### Scenario: Run result includes project skill names in loaded_skills

- **WHEN** the run completes having materialized both agent and project skills
- **THEN** `result["loaded_skills"]` lists all materialized skill names
- **AND** the `run_start` trace event's `loaded_skills` field matches

#### Scenario: Session without project falls back to agent-only skills

- **WHEN** the session context has no project_code (defensive edge case)
- **THEN** only agent-level skills are materialized and behavior is identical to the pre-change implementation
