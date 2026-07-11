## ADDED Requirements

### Requirement: General Agent runs a bounded Claude Agent SDK tool loop

GeneralAgent SHALL drive `claude_agent_sdk.query()` as a message-by-message Agent loop until a terminal result, timeout, cancellation/error, or its GeneralAgent-specific turn bound. It SHALL project SDK tool calls, tool results, partial answer text, usage, and the terminal result into the existing chat trace event vocabulary while preserving the final plain-text response and `suggested_agent_type` contract.

#### Scenario: Project discovery executes inside the loop

- **WHEN** the model calls `mcp__project_repo__discover_projects` while handling a project-bound request
- **THEN** GeneralAgent continues the SDK loop with the tool result and produces a final routing response
- **AND** the run emits correlated tool start/end trace events before `run_complete`

#### Scenario: Loop bound is recoverable

- **WHEN** the SDK reaches the configured GeneralAgent turn bound after producing usable text
- **THEN** GeneralAgent completes with the collected text instead of failing the entire chat run
- **AND** if no usable text exists it returns the existing safe routing fallback

### Requirement: General Agent has least-privilege project discovery

When the configured provider supports in-process MCP tools, GeneralAgent SHALL register the discovery-only project repository MCP server and allow `mcp__project_repo__discover_projects`. It MUST NOT register or allow `mcp__project_repo__lookup_project_repo`, filesystem, shell, web, task, or write tools. When MCP tools are unsupported, it SHALL route to specialist Agents without naming a concrete registered project or claiming that no suitable project exists.

#### Scenario: Discovery-only server is registered

- **WHEN** GeneralAgent builds SDK options for an MCP-capable provider
- **THEN** its allowed tools include `mcp__project_repo__discover_projects`
- **AND** its registered project repository server exposes no credential-bearing lookup capability

#### Scenario: Unsupported provider degrades safely

- **WHEN** GeneralAgent runs with a provider that does not support MCP server tools
- **THEN** no project repository MCP server or MCP allowed tool is configured
- **AND** its prompt forbids concrete project-existence and no-match assertions

### Requirement: General Agent supports Agent-level Skills without project binding

The system SHALL register `general_agent` in the existing Agent Skills administration. Before every GeneralAgent SDK run it SHALL materialize enabled Agent-level Skills into the isolated run workspace, allow the SDK `Skill` tool when Skills are available, and set `setting_sources=["project"]` so the SDK can discover them. It SHALL NOT load project-level Skills, accept a project code, or appear in project-level Skill/prompt configuration surfaces.

#### Scenario: Enabled GeneralAgent Skill is loaded

- **WHEN** an enabled Agent Skill is installed for `general_agent`
- **THEN** the run workspace contains `.claude/skills/<skill-name>/SKILL.md`
- **AND** SDK options allow `Skill` and use `setting_sources=["project"]`
- **AND** `run_start` and `run_complete` report the loaded Skill name

#### Scenario: GeneralAgent remains absent from projects

- **WHEN** project-level Agent configuration keys and project selection choices are enumerated
- **THEN** `general_agent` is absent
- **AND** project-bound questions are still routed to the relevant specialist Agent

### Requirement: General Agent always uses the small fast model profile

GeneralAgent SHALL pass an explicit model resolved from `anthropic_small_fast_model` or the active provider's `default_small_fast_model`. It MUST NOT use the configured primary Anthropic model or the provider's primary default, and SHALL retain GeneralAgent-specific max-token, timeout, and turn bounds.

#### Scenario: Primary and small models differ

- **WHEN** both a primary model and a small/fast model are configured
- **THEN** GeneralAgent SDK options use the small/fast model
- **AND** ProjectExpertAgent and LogAnalysisAgent remain free to use the primary model

#### Scenario: Small model is unavailable

- **WHEN** neither an explicit nor provider-default small/fast model can be resolved
- **THEN** GeneralAgent fails with a clear configuration error
- **AND** it does not silently execute on the primary model
