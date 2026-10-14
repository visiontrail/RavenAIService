## ADDED Requirements

### Requirement: Compact list summaries
The API SHALL support opt-in compact list results without full analysis, trace, conversation, or manual-analysis bodies, while preserving group summaries, status, attribution and explicit analysis-presence flags. Default list and detail results SHALL remain compatible.

#### Scenario: Large analysis result
- **WHEN** a log contains a multi-megabyte analysis history and compact listing is requested
- **THEN** the list returns its summary and presence flags without the bodies and detail still returns the complete history

### Requirement: Efficient grouping with stable semantics
The SQLite list path SHALL group lightweight headers before pagination and hydrate only selected groups. Group identity, primary record, aggregate status/sort/filter behavior and legacy attribution SHALL be preserved.

#### Scenario: Legacy and modern attachments
- **WHEN** filtering or paging grouped logs including legacy AI-chat attachments
- **THEN** complete groups are returned and totals count groups, with no full metadata hydration for off-page groups

### Requirement: Bounded browser page reuse
The browser SHALL reuse matching cached pages immediately, revalidate stale pages in the background, cap retention and count, and refresh on mount, focus and explicit refresh. Mutation SHALL invalidate cached and pending pre-mutation results.

#### Scenario: Return from detail
- **WHEN** the user returns to a recently viewed list
- **THEN** cached rows render immediately while a new request obtains current data

### Requirement: Concurrent requests remain coherent
The browser SHALL deduplicate identical concurrent list requests and SHALL prevent old query responses from overwriting the latest requested query.

#### Scenario: Rapid filter changes
- **WHEN** an earlier request completes after a newer filter request
- **THEN** only the newer filter result remains visible

#### Scenario: Refresh fails
- **WHEN** a background refresh fails
- **THEN** the last available rows remain visible and loading indicators stop
