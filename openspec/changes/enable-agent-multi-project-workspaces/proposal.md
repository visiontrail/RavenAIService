## Why

Project Expert and Log Analysis can discover that the user selected the wrong project, or that one question spans multiple projects, but today they can only stop and ask the user to start another session. This prevents a single Agent run from correlating OAM evidence with protocol-stack implementation even when both projects are already registered and cloneable.

## What Changes

- Add a workspace-bound Agent tool that resolves and clones an enabled project into a deterministic related-repository directory without exposing clone credentials to the model or trace.
- Let Project Expert and Log Analysis call project discovery, inspect complete project cards, and clone one or more relevant registered repositories in the current isolated workspace.
- Make related-repository cloning idempotent, path-contained, shallow by default, SSH-agent compatible, and safe on partial failures.
- Change project-fit behavior so a clear mismatch can be recovered inside the current run, while joint questions can use the selected repository and additional repositories together.
- Keep GeneralAgent discovery-only and preserve the current single selected project/session ownership, prompts, skills, and membership semantics.
- Persist non-sensitive related-repository provenance in the workspace task manifest and expose the tool activity through the existing Agent trace with credential masking.

## Capabilities

### New Capabilities

- `agent-multi-project-workspace`: Safe workspace-bound cloning, reuse, provenance, and containment for additional registered project repositories.

### Modified Capabilities

- `agent-project-discovery`: Project-bound Agents gain the related-project clone tool while GeneralAgent remains discovery-only.
- `project-expert-agent`: Project Expert can recover from a wrong selection and perform joint source analysis within one session.
- `log-analysis-agent`: Log Analysis can correlate logs and source across the selected project plus additional registered projects.

## Impact

The change affects the shared project-repository MCP server, Project Expert and Log Analysis option construction and prompts, workspace manifests/layout, focused backend tests, Agent documentation, and the existing SSH-enabled Docker production path. It does not change public HTTP request schemas, project membership rules, repository credentials, or the selected-project UI contract.
