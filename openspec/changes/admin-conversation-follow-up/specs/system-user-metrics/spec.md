## ADDED Requirements

### Requirement: Raw event feed excludes package downloads
The raw event list SHALL omit source package_download before pagination and total counting. Stored download events and download aggregates MUST remain intact.

#### Scenario: Downloads interspersed with AI and upload events
- **WHEN** an admin lists raw events, including when filtering by package_download
- **THEN** no download rows are returned and totals count only eligible events
- **AND** package uploads and AI events remain visible
