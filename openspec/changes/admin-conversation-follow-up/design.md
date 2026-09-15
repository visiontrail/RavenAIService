## Context
AdminMetrics currently renders the transcript in a right-hand drawer. ChatAgentRun records the workspace path; normal chat services also persist runs and messages, so they cannot implement temporary audit questions safely.

## Goals / Non-Goals
**Goals:** Centered X-only modal, Mermaid zoom, transient multi-turn admin follow-up using the event's workspace, and filtered download events.
**Non-Goals:** Changing original user messages, resuming original SDK sessions, device mutations, deployment or removal of stored download events.

## Decisions
- Resolve the source run by event.run_id and matching session/owner; use a session-scoped latest run only for legacy events without run_id. Never accept a workspace path from the client. Missing/cleaned workspace returns a clear conflict.
- A separate admin-authenticated SSE endpoint reads the source transcript and accepts bounded prior temporary turns from browser memory. It never calls chat history or chat run persistence services. Close aborts the request; no server conversation registry is created.
- Launch a fresh SDK invocation with persistence disabled and isolated temporary CLI configuration. Use the source workspace as cwd but disable built-in tools, project hooks/settings, and extra MCP servers. Expose only scoped read/list/search MCP tools with traversal and symlink checks; never modify or clean the source workspace. This preserves workspace context while preventing audit follow-ups from changing original work.
- Source selection and transcript context are rechecked for each request. Exclude the endpoint from request/response body logging; errors sent to clients are generic.
- Keep the existing Markdown renderer. Add a reusable delegated Mermaid preview component to the admin dialog; process newly added temporary answers after DOM updates.
- Hide package_download in the raw-event query before counting/pagination. Retain existing log_upload exclusion and all stored metrics.

## Risks / Trade-offs
- Deleted/remote-only workspace → explain unavailability and refuse substitution.
- Provider without in-process MCP → require MCP-capable endpoint and fail explicitly if unavailable.
- Temporary history length → enforce bounded input and report limit rather than silently dropping turns.
- Disconnect/timeout → cancel SDK iterator and clean only temporary CLI state.

## Migration Plan
No migration. Ship backend and frontend together; rollback by reverting the commit.
