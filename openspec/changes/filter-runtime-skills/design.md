## Context

All enabled Agent and project Skills are currently merged and materialized before every run. Their names/descriptions are appended to both system and user prompts, and the materialized list is emitted as `loaded_skills`. The SDK still reads a Skill body only after a `Skill` tool call, but the current behavior wastes catalog context and the UI conflates availability with invocation.

## Goals / Non-Goals

**Goals:**

- Materialize at most three optional Skills with positive request-specific evidence.
- Use one selection implementation across Skill-enabled agents while preserving Agent/project precedence.
- Treat attachment filename/type as strong evidence for format-specific Skills such as `xlsx` and `docx`.
- Report candidate availability separately from actual `Skill` tool invocation.
- Replay historical traces without continuing the misleading “loaded” interpretation.

**Non-Goals:**

- Adding embeddings, a second model call, or a database schema migration.
- Changing Skill installation, enable/disable controls, or same-name project override behavior.
- Treating Skill content as authoritative over source code or logs.

## Decisions

1. **Use deterministic relevance scoring before materialization.** The service builds a de-duplicated candidate pool, tokenizes the request and each Skill's name/description/bounded `SKILL.md` body, weights name and description matches above body matches, and ranks only positive scores. This restores bounded preselection without an extra model request or dependency.

2. **Use conservative no-match behavior.** A request with no positive evidence receives no optional Skill. The agent can still complete its core workflow from prompts, source code, logs and MCP tools. Falling back to all enabled Skills would recreate the reported issue.

3. **Use attachment evidence explicitly.** Callers include original filenames in the relevance query. Exact suffix/name cues strongly select format-specific Skills; unrelated archive input does not select `xlsx` or `docx` merely because those Skills are globally enabled.

4. **Bound selection to three Skills.** Three preserves room for cross-domain questions while preventing a seven-Skill project from appearing almost entirely selected. Callers may override the bound for a narrowly justified workflow.

5. **Separate trace concepts.** `available_skills` means the full enabled catalog for the selected Agent/project, regardless of request filtering. Selection still controls which Skills are materialized, so listing the catalog does not inflate model context. The UI keeps the full catalog collapsed by default. A Skill is actually loaded only when a `step_start` event invokes tool `Skill`. New traces use `skills_available`; the frontend interprets legacy `run_start.loaded_skills` and `skills_loaded` notices as historical availability metadata.

6. **Keep wire compatibility during rollout.** New backend lifecycle events include `available_skills` and retain the legacy `loaded_skills` candidate alias temporarily. The new frontend never counts that alias as actual invocation.

## Risks / Trade-offs

- [A relevant Skill has no lexical overlap with the request] → Search bounded Skill body text, include attachment evidence, retain up to three positive candidates, and cover multilingual/identifier tokenization with tests.
- [Very generic terms match several Skills] → Down-weight terms common across the candidate pool and require a positive ranked score.
- [Old persisted traces have only `loaded_skills`] → Render them as “available” while deriving “loaded” only from historical `Skill` tool steps.
- [Backend/frontend deploy order differs] → Retain the legacy lifecycle alias until both sides are deployed.

## Migration Plan

1. Deploy backend and frontend from one commit/image set.
2. Verify a Ka log-analysis run exposes the full enabled Agent/project catalog and invokes the Ka Skill.
3. Confirm the available catalog is collapsed by default; after expansion, unrelated `payload-management-unit`, `tcpt027-db-modify`, `xlsx`, and `docx` may be visible there but remain absent from materialization and actual `Skill` calls.
4. Roll back to the previous image if candidate selection prevents a required workflow; no data migration is involved.

## Open Questions

None for this change. Future Skill metadata may add explicit tags or an `always_available` policy, but the current registries do not define those fields.
