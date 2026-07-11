## 1. Prompt configuration

- [x] 1.1 Add localized `claude_agent_general.generic` system and user prompts to `prompts_config.yaml`
- [x] 1.2 Add a GeneralAgent prompt loader/renderer and wire admin prompt metadata plus cache invalidation

## 2. Agent Skills configuration

- [x] 2.1 Register `general_agent` in the shared Agent Skills catalog while keeping project-level Agent keys unchanged
- [x] 2.2 Materialize enabled GeneralAgent Skills in each isolated run workspace and configure `Skill`/`setting_sources` only when available

## 3. Claude Agent SDK loop

- [x] 3.1 Refactor GeneralAgent SDK message processing to preserve tool calls/results, answer deltas, usage, and terminal text through the shared trace event machinery
- [x] 3.2 Keep project discovery discovery-only, enforce the built-in tool denylist, and preserve provider fallback guidance
- [x] 3.3 Enforce explicit small/fast model resolution and GeneralAgent-specific turn/token/timeout limits
- [x] 3.4 Preserve structured specialist suggestion parsing, safe fallback answers, and chat lifecycle compatibility

## 4. Verification

- [x] 4.1 Add/update GeneralAgent tests for SDK loop traces, project discovery permissions, Skill loading, and small-model invariants
- [x] 4.2 Add/update prompt and skills administration tests for GeneralAgent visibility, localization, editing, and cache invalidation
- [x] 4.3 Run targeted backend tests and OpenSpec validation
