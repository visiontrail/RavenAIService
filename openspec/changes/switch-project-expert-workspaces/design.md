## Context

The Project Expert session registry points to one workspace. A follow-up request with a different `project_repo_id` currently emits a notice and still runs against the original checkout. Chat history is stored separately from that workspace, but only a recent excerpt reaches the Agent.

## Goals / Non-Goals

**Goals:** Switch the selected project for the next turn, isolate its checkout and project Skills, and make the full prior conversation available without treating old answers as source evidence. Keep same-project reuse and existing stream/session identifiers.

**Non-Goals:** Automatically infer a project switch from conversation text or clone unregistered repositories.

## Decisions

- Resolve and authorize a newly selected project before replacing the session context. Prepare a fresh workspace, update the registry, and clean the old workspace after successful replacement. An active run remains attached to its original workspace; a new project request during that run receives an explicit retry error.
- Persist the full prior text transcript in the active workspace as `conversation_history.json`. Keep the recent excerpt in the prompt to control prompt size and direct the Agent to read the transcript for older context. The selected project's `task.json.repo_info` remains authoritative for the current turn.
- Tighten Project Expert's project-fit guidance: use same-series repositories as implementation evidence for the selected project, and describe different-series code only as an explicitly labeled reference. Explicit comparisons may inspect both projects, but answers must not transfer implementation claims between them.

## Risks / Trade-offs

- [A long chat can exceed the model context] → Keep the full transcript in a file and only a recent excerpt in the prompt.
- [A project switch can happen while a run is active] → Reject the new request with a clear retry message; never replace an in-use workspace.
- [Product series cannot be derived reliably from repository naming alone] → Require the Agent to use project cards and disclose uncertain identity instead of hard-coding a prefix matcher.

## Migration Plan

Existing sessions continue to load their current context. The next request with a different selected ID creates a new workspace. Local Docker rebuild and API-level verification precede the commit; no database migration is needed.
