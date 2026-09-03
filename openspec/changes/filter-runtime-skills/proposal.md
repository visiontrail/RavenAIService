## Why

Agent runs currently materialize every enabled Agent/project Skill and publish that availability list as `loaded_skills`. This inflates prompt/catalog context and makes the UI claim that unrelated Skills were loaded even when the SDK invoked only one of them.

## What Changes

- Select a small request-relevant Skill candidate set before workspace materialization, using request text, attachment filenames/types, and Skill metadata/content.
- Fail closed to no optional Skill when no candidate has positive evidence instead of falling back to every enabled Skill.
- Preserve Agent/project precedence and an explicit maximum candidate count.
- Split trace semantics into available/materialized Skills and Skills actually invoked through the `Skill` tool.
- Update the trace UI to label and render the two sets accurately, including backward-compatible replay of historical traces.

## Capabilities

### New Capabilities

None.

### Modified Capabilities

- `project-skill-materialization`: Materialize only a bounded, request-relevant subset of enabled Agent/project Skills.
- `agent-trace-stream`: Report candidate availability independently from actual Skill invocations.
- `agent-trace-ui`: Display available and actually loaded Skills with accurate labels and historical compatibility.
- `log-analysis-agent`: Build relevance evidence from the real log-analysis question, hints, and attachment filenames before materialization.

## Impact

- Backend: `app/services/skills_service.py`, Skill-enabled agents, shared trace schema, agent results and regression tests.
- Frontend: trace types, Skill aggregation/rendering, translations and unit tests.
- Runtime: smaller `.claude/skills` candidate sets and prompt menus; no database migration or new dependency.
