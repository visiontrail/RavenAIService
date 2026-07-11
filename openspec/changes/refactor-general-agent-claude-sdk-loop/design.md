## Context

GeneralAgent is the default, non-project-bound chat route. It already calls `claude_agent_sdk.query()`, but it treats the SDK stream as a one-shot text collector: SDK tool messages are not projected into the shared Agent trace loop, enabled Skills are not materialized, and its system prompt is a Python constant outside the editable prompt configuration. The recently added project-card discovery MCP server is discovery-only for GeneralAgent and deliberately omits the credential-bearing repository lookup tool.

LogAnalysisAgent and ProjectExpertAgent establish the repository conventions to follow: per-run workspaces, `build_options()`, SDK message-by-message loop processing, Agent Skill materialization under `.claude/skills`, `setting_sources=["project"]`, localized YAML prompts, and cache invalidation after admin edits. GeneralAgent must adopt those conventions without becoming a project-bound execution Agent and without inheriting their large model.

## Goals / Non-Goals

**Goals:**

- Give GeneralAgent a real bounded Claude Agent SDK loop whose tool-use messages can be observed and whose final result preserves the existing chat event contract.
- Allow only project-card discovery and explicitly materialized Agent Skills; keep credential, filesystem, shell, web, task, and write tools unavailable.
- Make `general_agent` available in Agent Skills administration and load enabled Skills in an isolated run workspace.
- Load localized GeneralAgent prompts from `prompts_config.yaml` and expose them through the existing admin prompt editor.
- Keep GeneralAgent on the configured small/fast model with its existing small token and timeout budgets.
- Keep GeneralAgent absent from project-level prompt/Skill configuration and project selection flows.

**Non-Goals:**

- GeneralAgent will not clone repositories, read project source, inspect logs, search packages, operate devices, or answer project-bound questions itself.
- GeneralAgent will not receive project-level Skills or project-level system-prompt addenda.
- This change will not add a GeneralAgent choice to the project UI or change specialist Agent routing APIs.
- This change will not move GeneralAgent to the primary/large Anthropic model.

## Decisions

### 1. Retain `query()` but process it as the shared SDK Agent loop

GeneralAgent will continue to use the public `claude_agent_sdk.query()` API, iterating every SDK message until the SDK returns its terminal result or the bounded loop fails. SDK messages will be passed through the shared trace state/translation used by the specialist Agents so tool calls, tool results, usage, and the terminal result are preserved. The existing `run_start`, `run_complete`, `answer_delta`, step, and error event vocabulary remains compatible with `chat_run_service`.

Using the specialist trace translator is preferred over a second GeneralAgent-only tool parser because SDK message shapes and masking behavior then remain aligned. The GeneralAgent result remains plain text plus `suggested_agent_type`; it does not adopt the specialist Agents' fenced-JSON result schema.

### 2. Use an isolated temporary workspace and Agent-only Skill materialization

For each run, GeneralAgent creates a temporary workspace, calls `skills_service.materialize_enabled_skills("general_agent", workspace)`, and sets `setting_sources=["project"]` only when one or more Skills were materialized. `general_agent` is added to `skills_service.SUPPORTED_AGENTS`, so the existing admin Agent Skills APIs/UI discover it automatically.

No `project_code` is passed. GeneralAgent is intentionally omitted from `project_prompt_service.PROJECT_AGENT_KEYS` and all project-scoped admin configuration. The word `project` in `setting_sources` refers to the Claude SDK's workspace settings source, not a Raven project binding.

### 3. Construct a least-privilege tool set per run

The base allowed list is empty. When the active provider supports in-process MCP tools, register only the discovery-only `project_repo` MCP view and allow `mcp__project_repo__discover_projects`. When Agent Skills were materialized, additionally allow the SDK `Skill` tool. The existing built-in disallow list remains in force, and repository lookup is never registered for GeneralAgent.

The loop bound will be high enough for one Skill invocation and/or one project discovery followed by a final answer, but will remain a GeneralAgent-specific small bound rather than inheriting the specialist default. Timeout and output-token limits continue to use `anthropic_small_fast_*` settings.

### 4. Move prompt bodies to localized YAML with a GeneralAgent loader

Add `claude_agent_general.generic.system_prompt` and `user_prompt_template` entries with `zh` and `en` bodies. A small `app/agents/general_agent/prompts.py` loader mirrors the log-analysis/project-expert loaders and renders the conversation history and latest input. `PROMPT_FUNCTION_META` and `PROMPT_AGENT_META` will label these entries for the existing admin editor, and prompt cache invalidation will clear the GeneralAgent cache.

The optional per-request `system_prompt_override` remains an additive runtime suffix for compatibility. The active response-language directive is appended last.

### 5. Preserve small/fast model resolution as an invariant

GeneralAgent passes an explicit model from `settings.anthropic_small_fast_model`, falling back only to the provider profile's `default_small_fast_model`. It never falls back to `settings.anthropic_model` or the provider's primary model. If neither small model is defined, configuration fails clearly instead of silently using the specialist model.

## Risks / Trade-offs

- [Agent Skills can broaden routing behavior] → The system prompt states that Skills may improve system guidance/routing only and cannot authorize project work; tool permissions still enforce the boundary.
- [Skill plus discovery may require more turns than the current fixed value] → Use a small explicit loop bound covered by tests, and retain recoverable max-turn handling/fallback behavior.
- [Shared trace helpers are currently defined in the log-analysis module] → Reuse them in this focused change to preserve behavior; extracting a neutral trace module is a separate refactor.
- [Prompt migration can change wording] → Copy the current Chinese contract verbatim into YAML, add an equivalent English variant, and retain marker parsing/fallback tests.
- [Providers without MCP support cannot discover projects] → Remove MCP tools and append the existing catalog-unavailable guidance; Agent routing still works without naming a project.

## Migration Plan

1. Add YAML prompt entries and loader/admin metadata while retaining behavioral equivalence.
2. Register `general_agent` for Agent Skills and materialize Agent-only Skills per run.
3. Switch the current message collector to shared SDK loop event processing and least-privilege tool assembly.
4. Run GeneralAgent, prompt-service, skills-service, and chat lifecycle tests.

Rollback consists of reverting these code/config changes. There is no database migration and existing Agent Skill registries remain harmless if the agent key is temporarily unsupported.

## Open Questions

None. The user requirement explicitly fixes the role boundary and small/fast model choice.
