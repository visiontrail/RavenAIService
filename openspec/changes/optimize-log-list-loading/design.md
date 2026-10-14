## Context

The list groups modern and legacy multi-attachment uploads before filtering/paging. Full metadata includes multi-megabyte analysis traces and conversation history. Compatibility requires preserving group identity, representative selection, aggregate sort/filter behavior, and trigger-user fallback.

## Goals / Non-Goals

**Goals:** Reduce first-load work and payload size; make returning to a page immediate; preserve correct status, grouping, and attribution.

**Non-Goals:** Change analysis execution, persist sensitive list contents in localStorage, change legacy client contracts, or introduce a new caching service.

## Decisions

- `compact=true` opts into list summaries with explicit `has_ai_analysis` and `has_manual_analysis` flags. Full detail and default list responses retain their current fields. Compact responses clear analysis/history/manual bodies and unneeded metadata; the UI falls back to old fields when talking to an older server.
- SQLite uses a lightweight projection of grouping fields and guarded JSON scalar extraction. Other configured databases retain a compatible grouping fallback. Only records on the chosen page are hydrated with full metadata. Compute representatives once per group, retaining legacy grouping and attachment matching.
- Trigger fallback queries load only run identity/request/timestamps and user display columns, never stored trace/output bodies.
- Keep at most ten pages in Pinia memory, fresh for 30 seconds and reusable for five minutes with background refresh. Keys include all query parameters. Mount, focus, polling, and manual refresh revalidate; mutation clears entries and invalidates pending responses. Avoid disk persistence and cross-tab staleness complexity.
- Deduplicate identical pending reads and use a request sequence to prevent older filters overwriting the active page. Separate initial loading from refreshing so existing rows remain usable.

## Risks / Trade-offs

- Grouping still examines lightweight headers for all records → preserve legacy semantics now; test the removal of large metadata and bound full-record hydration by page membership. Database-native grouped pagination can be added if header volume becomes the bottleneck.
- Cached values can be briefly stale → revalidate on return/focus, poll active analysis, bypass freshness for explicit refresh, and invalidate after mutations.
- SQLite JSON may be malformed in legacy rows → guard with `json_valid` and retain malformed-metadata recovery tests.

## Migration Plan

Deploy backend and frontend normally; no schema migration. Older frontend/backend combinations remain compatible. Roll back the commit to restore prior behavior.
