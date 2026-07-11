## Why

Users can select the wrong project or cannot tell which project fits their question because the current optional `description` has no reliable content contract and Agents cannot enumerate the project registry. Project-bound Agents may therefore answer against unrelated context, while GeneralAgent cannot recommend a concrete registered project or state confidently that no suitable project exists.

## What Changes

- Replace the optional project `description` with a required, non-empty `project_card` that explains the project's scope, suitable questions, and boundaries.
- Migrate existing project descriptions into project cards and generate a safe fallback card for legacy rows without a description.
- Add a read-only `discover_projects` Agent tool that returns every enabled project's non-sensitive identity, project card, repository availability, and enabled Agent keys without exposing repository URLs or credentials.
- Give GeneralAgent, ProjectExpertAgent, and LogAnalysisAgent access to project discovery and explicit project-fit decision rules.
- Require Agents to stop using clearly mismatched project context, explain the mismatch, recommend a matching registered project when one exists, and explicitly say that no suitable project is currently registered when none fits.
- Surface project-card summaries in project selection so users can make a better choice before starting a run.

## Capabilities

### New Capabilities
- `agent-project-discovery`: Safe project-catalog discovery and consistent Agent behavior for matching, redirecting, and no-match responses.

### Modified Capabilities
- `project-repo-registry`: Project metadata uses a required project card instead of an optional description.
- `general-agent`: GeneralAgent discovers registered projects before recommending a project-bound workflow.
- `project-expert-agent`: Project Expert validates the selected project against the question and redirects or declines on a clear mismatch.
- `log-analysis-agent`: Log Analysis validates selected or resolved project context and does not analyze against a clearly unrelated project.
- `chat-conversation-ui`: Project selectors expose project-card summaries to help users choose correctly.

## Impact

- Database/model: `project_repo.description` is migrated to a non-null `project_repo.project_card` column.
- APIs: admin and public project-repository schemas replace `description` with required `project_card`.
- Agents: the shared in-process project-repository MCP server gains a safe discovery tool; three Agent tool allowlists and prompts change.
- Frontend: project management validation, localization, types, project table, create/edit dialog, and chat project selector change.
- Tests: migration/model, project service/API contracts, MCP discovery safety, Agent options/prompts, and frontend type/build coverage are updated.
