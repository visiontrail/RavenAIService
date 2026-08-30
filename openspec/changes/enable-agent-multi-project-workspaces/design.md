## Context

RavenAI already exposes `discover_projects` (safe project cards) and `lookup_project_repo` (clone-ready repository details) to Project Expert and Log Analysis. Both Agents run with `Bash` in an isolated persistent workspace, but the workspace has one fixed `repo/` slot and the project-fit prompt requires a mismatched run to stop and ask the user to create another session. The production deployment also supports SSH-only repositories through a sidecar `ssh-agent`; any new clone path must inherit that runtime without mounting the private key into the Agent container.

The change crosses the shared in-process MCP server, two Agent option/prompt builders, workspace layout, task provenance, tests, and production validation. Clone credentials must not enter `task.json`, the discovery catalog, normal tool output, persisted traces, logs, or the final answer.

## Goals / Non-Goals

**Goals:**

- Let Project Expert and Log Analysis discover and inspect project cards, then clone the selected or additional relevant project repositories without leaving the current session.
- Support both wrong-project recovery and true multi-project investigation with deterministic, reusable repository paths.
- Keep repository resolution and credentials inside a workspace-bound tool, including SSH-agent support.
- Bound disk use, prevent path traversal, clean partial clones, and persist sanitized provenance.
- Preserve the current primary `repo/` layout and all existing HTTP/UI contracts.

**Non-Goals:**

- Automatically change the session's selected project, membership, project prompt, or materialized project Skills.
- Expose repository URLs or credentials through project discovery or the new clone tool response.
- Permit GeneralAgent to clone repositories or access filesystem/shell tools.
- Merge repositories, modify cloned source, push commits, or create merge requests.
- Implement backend semantic matching; the model continues to reason over project cards.

## Decisions

### 1. Add a workspace-bound `clone_project_repo` MCP tool

The full project-repository server will be constructed per Agent run with the canonical workspace path, primary project code, and Agent key. The new tool accepts only `project_code`; it resolves the enabled registry row and Agent binding server-side, derives any HTTPS token internally, and performs `git clone` without a shell. Its response contains sanitized project identity/card, branch, commit, reuse status, and workspace paths, but no repository URL, token, or authentication state.

This is preferred over asking the model to call `lookup_project_repo` followed by `Bash git clone` for additional repositories because clone credentials would otherwise pass through model context and trace masking would remain a last line of defence rather than a hard boundary. `lookup_project_repo` remains available for compatibility and provider fallback behavior.

### 2. Preserve `repo/` for the primary project and add `related_repos/<project_code>/`

When the requested code matches the session's selected/resolved project, the tool uses the existing `<workspace>/repo` slot. Other projects use `<workspace>/related_repos/<sanitized-project-code>`. The server computes and resolves every path beneath the bound workspace; the model never chooses a destination path. A fixed per-workspace repository limit (configured with a safe default) bounds disk amplification.

This preserves existing prompts, evidence paths, follow-up reuse, and cleanup behavior while making multi-project evidence visually distinct.

### 3. Make cloning idempotent and failure-safe

An existing Git checkout at the deterministic target is reused after reading its current branch and commit. A new clone is shallow and performed into a unique sibling partial directory, then atomically renamed into place. Empty system-created placeholders may be replaced; any other non-Git target is treated as a conflict. Timeouts, Git errors, and unexpected exceptions remove only the validated partial directory and return a sanitized typed error.

A per-server asynchronous lock serializes clone/manifest updates inside one run. This avoids two parallel tool calls racing on the same repository path.

### 4. Persist only non-sensitive related-repository provenance

After clone or reuse, the tool atomically upserts `task.json.related_repos` with project code/name/card, relative path, branch, commit SHA, and reuse state. The primary `repo_info` contract remains unchanged. No clone URL, Git token, SSH identity, or raw Git stderr is written.

This gives follow-up turns and production verification a durable record of which additional code actually participated, without adding a database migration or changing public APIs.

### 5. Replace redirect-only project-fit instructions with in-workspace recovery

Both project-bound Agents must read the complete project catalog before project-grounded conclusions. If the selected project is wrong and another card clearly matches, the Agent calls `clone_project_repo`, inspects that returned path, and answers from the matching code while explicitly excluding unrelated selected-project evidence. If multiple cards are jointly required, it clones each needed repository and cites evidence by repository path. No match and ambiguous-match behavior remain evidence-bounded.

The selected project's project prompt and Skills remain loaded because changing them mid-run would alter session ownership and permission semantics. Prompts therefore prohibit treating selected-project instructions or Skills as evidence for an unrelated additional project.

### 6. Retain discovery-only isolation for GeneralAgent

The discovery-only MCP server remains a distinct server object containing only `discover_projects`. The new clone tool exists only on the workspace-bound full server used by Project Expert and Log Analysis. Provider profiles without in-process MCP support retain current single-project fallback and receive an explicit runtime limitation instead of a false multi-project claim.

## Risks / Trade-offs

- **[Model clones too many plausible projects]** → enforce a configured per-workspace limit and prompt the Agent to clone only cards materially required by the question.
- **[Additional project prompt/Skills are not loaded]** → return the full project card, analyze only cloned source for that project, and state this scope; do not silently switch session ownership.
- **[Clone credentials leak through Git errors]** → keep clone URLs out of tool responses, use argv rather than shell, and redact the exact clone URL/token-bearing variants from all error text and logs.
- **[Partial clone consumes space or blocks retry]** → clone into validated unique partial paths and clean only those paths on every failure.
- **[SSH succeeds on host but fails in containers]** → reuse the existing SSH-agent overlay and verify the new tool from the actual backend container and production UI.
- **[Persistent workspace grows]** → shallow clone, fixed repository count, existing session cleanup, and explicit related-repository provenance.

## Migration Plan

1. Deploy the backend image and recreate only Agent-capable services that need the new Python code, keeping the existing SSH-agent overlay and volumes.
2. Verify the SSH-agent health and a container-side clone of the registered LX07A protocol-stack project through the new tool path.
3. Run a real Project Expert session selected on `灵犀07A操作维护`; confirm discovery, additional clone, persisted `related_repos`, trace, answer evidence, and browser-visible completion.
4. Roll back by redeploying the pre-change commit/image. Existing workspaces remain compatible because `related_repos` is additive and ignored by older code.

## Open Questions

None. The default related-repository limit and clone timeout remain internal safe defaults and can be promoted to admin settings later if operational evidence requires it.
