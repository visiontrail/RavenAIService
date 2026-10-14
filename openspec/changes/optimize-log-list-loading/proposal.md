## Why

The deployed log list transfers 14.7 MB for ten rows and took 8.79 seconds in a baseline request. It loads and repeatedly parses every record's analysis metadata before pagination and sends full analysis histories that the table does not display.

## What Changes

- Add an opt-in compact list response retaining grouping, status, attribution, and attachment summaries; keep full detail and legacy list responses compatible.
- Use lightweight grouping data and only hydrate the requested page; avoid loading trace bodies for trigger-user lookup.
- Cache recent pages in browser memory with bounded lifetime, background revalidation, request deduplication, and race protection.
- Refresh on return and mutation, without obscuring already available rows during background updates.

## Capabilities

### New Capabilities
- `log-list-loading`: Efficient, compatible paginated list loading and bounded client caching.

### Modified Capabilities
None.

## Impact

Log list API/service, Vue list/store/types, and regression tests. No new runtime dependency or destructive data migration.
