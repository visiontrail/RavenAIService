## Context

WorkbenchLayout has an inactive search toggle. ChatSession and ChatMessage already persist searchable text and enforce owner access through authenticated user routes. Local Docker services are stopped and must be rebuilt for acceptance.

## Goals / Non-Goals

**Goals:** Match the reference icon placement and familiar centered search interaction; find titles and message text across persisted conversations; support keyboard, IME, locales, themes, and account isolation.

**Non-Goals:** Semantic/vector retrieval, searching files or agent traces, changing chat execution, or production deployment.

## Decisions

- Add GET /api/v1/users/chat-sessions/search with q (trimmed, max 200), limit (1..50), offset, results and has_more. Empty q lists recent conversations. Stable recency ordering includes session ID as a tie-breaker.
- Use parameterized escaped SQL LIKE via icontains and correlated message subqueries; fetch one matching message per result. This supports existing SQLite and PostgreSQL deployments without a new index service or loading entire history into the browser. Literal percent/underscore queries must not become wildcards. Only user/ai/assistant message roles are searchable.
- Return bounded plain-text snippets centered on the match, with safe Vue text-node highlighting. The client never interprets retrieved content as HTML.
- Use a separate search component and composable. Debounce 250 ms and cancel/invalidate previous requests immediately on edits, close, IME composition, or unmount. Pagination appends deduplicated results.
- Use native modal dialog for focus containment, inert background and focus restoration. Add combobox/listbox keyboard semantics, recent time groups, new-chat action, Escape and backdrop dismissal, and Cmd/Ctrl+K. Reuse session selection to reopen the complete conversation.
- Guest search opens the existing login dialog. Unmount search on logout/account change so no cached results cross users.

## Risks / Trade-offs

- Substring search scans text → Scope to owner, cap query/result sizes and debounce; add dedicated text indexing if real data volume warrants it.
- Concurrent history updates can shift offset pagination → Use deterministic sorting and client deduplication; searches refresh on each opening.
- Provider sessions persist messages at different lifecycle points → Search indexes persisted messages only, with no agent/API invocation.

## Migration Plan

No schema changes. Run API and frontend regressions, build Docker images, start Compose, and verify HTTP, source parity, and browser interaction. Rollback uses previous Docker image tags.
