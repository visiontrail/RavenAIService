## Why

Project Expert currently ignores a new project selection within an existing chat session and continues using the previous project's checkout. Its broad cross-project guidance can also cause code from a different product series to be presented as evidence of the selected project's implementation.

## What Changes

- Switch Project Expert to a fresh workspace when the selected project changes, while retaining the same chat session and its conversation history.
- Keep follow-up turns on the same project in the current workspace.
- Require clear source provenance and distinguish same-series implementation evidence from other-series reference code in Project Expert guidance.
- Verify the behavior with focused tests and local Docker deployment.

## Capabilities

### New Capabilities

None.

### Modified Capabilities

- `project-expert-agent`: project switching and conversation context across workspaces.
- `agent-project-discovery`: source selection and provenance for cross-project Project Expert analysis.

## Impact

Project Expert chat service, its prompts, focused tests, and the Project Expert runbook. The stream API keeps the existing `project_repo_id` parameter and session ID.
