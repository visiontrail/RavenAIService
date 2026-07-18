## Context

`project_repo.description` is currently optional and is treated as an informal admin note. The same value is returned by project-list APIs, but project selectors show only name/code, GeneralAgent has no tools, and the existing project-repository MCP server only resolves one already-known project code into clone credentials. ProjectExpertAgent and LogAnalysisAgent therefore have no safe way to compare the selected project with the complete registry before answering.

The change crosses the database model, Alembic migration, public/admin APIs, shared MCP server, three Agent configurations/prompts, workspace metadata, and Vue project-management/chat UI. Repository credentials must remain isolated to the existing lookup tool.

## Goals / Non-Goals

**Goals:**

- Make useful project scope metadata mandatory at every create/update boundary and non-null in storage.
- Let the relevant user-facing Agents enumerate every enabled project through one safe tool.
- Give Agents enough metadata to identify a clear project mismatch, recommend a better registered project, or state that no suitable project is registered.
- Help users choose before sending by showing card summaries in the selector.
- Preserve existing repository lookup, membership, Agent binding, and session binding semantics.

**Non-Goals:**

- Automatically switch a running session to another project.
- Expose disabled projects, Git URLs, tokens, membership, or other admin-only data through Agent discovery.
- Implement an embedding/vector search service for project matching.
- Guarantee a semantic match through backend keyword rules; the Agent reasons over the complete card catalog.
- Extend project discovery to internal Agents that never accept a user-selected project in this change.

## Decisions

### 1. Use a first-class `project_card` field and migrate the old column

The database column is renamed from `description` to `project_card`, made non-null, and represented as a required string in admin create/update and public response schemas. Reusing `description` while only changing its UI label was rejected because it would preserve optional semantics and leave API/tool consumers unable to rely on the field.

Create and explicit update values are trimmed and rejected when blank. A bounded length prevents prompt/tool payload abuse. Existing non-blank descriptions are preserved verbatim; blank legacy rows receive a clearly marked fallback card stating that their scope still needs administrator completion. This avoids a blocking migration while preventing Agents from treating the fallback as a confident match.

### 2. Add a non-sensitive discovery tool beside repository lookup

The existing in-process `project_repo` MCP server gains `discover_projects`. It returns all enabled rows with only `id`, `project_code`, `project_name`, `project_card`, `has_repo`, and `enabled_agent_keys`. It never returns `repo_url`, `clone_url`, `git_token`, or auth state.

Keeping discovery in the shared MCP module avoids a second database/tool integration and lets ProjectExpertAgent and LogAnalysisAgent reuse their existing full server registration. Because SDK `allowed_tools` is not a hard visibility boundary in every permission mode, GeneralAgent registers a discovery-only server view containing no credential-bearing `lookup_project_repo` tool at all.

The tool returns the full enabled catalog rather than applying backend keyword filtering. Semantic filtering would create false negatives for natural-language questions and would make “no suitable project” unreliable. The existing project count is small and the public API already supports up to 500 options; the tool applies a bounded catalog limit as a payload guard.

### 3. Share one project-fit response contract across Agents

Each relevant Agent receives the same policy:

1. Read the full project catalog before making a project recommendation or asserting that no project fits.
2. Compare the question/log identity with the current project's card when a current project exists.
3. On a clear mismatch, do not continue reasoning from the unrelated repository or project-specific prompt.
4. Name the current and recommended project (name and code) when a clear alternative exists, and tell the user to start/select the appropriate project because sessions remain bound.
5. If no card fits, explicitly state that the current project registry has no suitable project; do not choose the “closest” unrelated project.
6. If evidence is ambiguous, explain the uncertainty rather than fabricating a confident redirect.

Prompt-only implicit behavior was rejected as insufficient unless backed by a real catalog tool and selected-project card in `task.json`. Project Expert and explicitly selected Log Analysis workspaces therefore persist the non-sensitive card alongside project identity.

### 4. Degrade safely when the configured provider has no MCP support

The existing provider capability check continues to remove MCP tools for unsupported providers. Project-bound Agents still receive the selected project's card in `task.json`, so they can reject a clear mismatch with the current project, but they MUST NOT claim that another project exists or that no suitable project exists without catalog evidence. GeneralAgent falls back to generic Agent routing when discovery is unavailable.

This preserves current DeepSeek compatibility without pretending discovery occurred.

The `custom` Anthropic-compatible profile is MCP-capable by default because SDK in-process MCP tools use the same standard `tool_use` loop as built-in tools such as `Read`; they are not remote MCP settings passed through to the upstream provider. This keeps project discovery available on the deployed Yinhe custom endpoint. The unsupported-provider fallback remains defensive for an explicitly incapable or unknown profile.

### 5. Surface cards in the existing selector without redesigning chat navigation

The existing native selector remains, but each option label includes a bounded single-line card summary and exposes the full card as its title. The admin list and create/edit dialog use “Project Card” terminology and required validation. A full custom project-picker redesign was rejected as unnecessary for this change and would expand accessibility and interaction risk.

## Risks / Trade-offs

- [Large catalogs increase prompt/tool payload] → Return enabled projects only, cap the tool result, keep cards length-bounded, and omit all repository/security fields.
- [Legacy fallback cards are weak matching evidence] → Make the fallback explicitly say scope is incomplete and instruct Agents not to infer a confident match from it.
- [LLM semantic judgment can still be imperfect] → Require explicit evidence from cards, distinguish clear/ambiguous/no-match outcomes, and test that prompts/tools carry the complete contract.
- [API field rename can break stale clients] → Update backend and bundled frontend atomically; the migration preserves values. This is an intentional contract change because retaining optional `description` would defeat the requirement.
- [MCP-disabled providers cannot inspect the complete catalog] → Degrade to current-project-only mismatch detection and prohibit unsupported global conclusions.
- [A mismatch discovered mid-session cannot auto-switch] → Keep session binding unchanged and return a precise instruction to start a new session with the recommended project.

## Migration Plan

1. Upgrade: trim/preserve non-empty `description` values and backfill blank values with an explicit legacy-card message. PostgreSQL renames the column and sets `NOT NULL`; SQLite uses an in-place rename plus INSERT/UPDATE required-value triggers so existing foreign-key references are preserved without cascade loss.
2. Deploy backend model, APIs, tool server, Agent allowlists/prompts, and workspace metadata together.
3. Deploy the frontend with the new required payload and card-aware selectors.
4. Administrators review legacy fallback cards and replace them with accurate scope/boundary content.
5. Rollback renames `project_card` back to nullable `description`; card text is retained as description data.

## Open Questions

None for implementation. Rich structured card sections and semantic indexing can be evaluated later if project count or matching quality warrants it.
