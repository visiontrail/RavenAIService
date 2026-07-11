## Why

GeneralAgent is still implemented as a special lightweight one-shot wrapper with an in-code prompt and no Agent-level Skill materialization, while LogAnalysisAgent and ProjectExpertAgent use the shared Claude Agent SDK loop/configuration conventions. This prevents GeneralAgent from safely using the project-card discovery tool and admin-managed Skills/prompts through the same operational path as the specialist Agents.

## What Changes

- Rework GeneralAgent around a bounded Claude Agent SDK Agent loop that can execute only explicitly registered routing tools, including project-card discovery, while preserving its existing structured specialist recommendation contract.
- Materialize enabled `general_agent` Skills into each run workspace, expose the SDK `Skill` tool, and load project settings with `setting_sources=["project"]` using the same Agent-level Skill workflow as the specialist Agents.
- Move the GeneralAgent system/user prompts from Python constants into localized `prompts_config.yaml` entries so administrators can edit them through the existing background prompt-management page.
- Register GeneralAgent in the existing Agent Skills and prompt metadata surfaces, but keep it absent from project selection and project-level configuration surfaces; project-bound work remains the responsibility of specialist Agents.
- Continue resolving the model exclusively from the configured small/fast model (`ANTHROPIC_SMALL_FAST_MODEL` or the provider's small/fast default), with GeneralAgent-specific token, timeout, and turn bounds.

## Capabilities

### New Capabilities

None.

### Modified Capabilities

- `general-agent`: Require the default router to run a bounded Claude Agent SDK tool loop with project discovery and Agent-level Skills while remaining non-project-bound and using the small/fast model.
- `localized-ai-interaction`: Require GeneralAgent prompts to be localized, cache-invalidated, and editable through the existing admin prompt-management surface.

## Impact

- Backend Agent/runtime: `app/agents/general_agent/`, shared Claude SDK option construction, project discovery MCP registration, usage/trace events.
- Configuration/admin: `app/prompts/prompts_config.yaml`, `app/services/prompts_config_service.py`, `app/services/skills_service.py`, and existing admin Agent Skills/Prompts APIs and UI metadata.
- Tests: GeneralAgent loop/tool/Skill/model behavior, prompt loading and cache invalidation, and admin metadata visibility.
- No new public chat API or model-provider dependency is introduced.
