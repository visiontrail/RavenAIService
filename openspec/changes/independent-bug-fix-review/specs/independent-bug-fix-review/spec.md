## ADDED Requirements

### Requirement: Independent BugFix endpoint
The system SHALL expose independently persisted provider, API key, base URL, model, token budget, turn limit and timeout settings for BugFix in Admin, including a connectivity probe. BugFix SHALL use this endpoint without falling back to analysis configuration.

#### Scenario: Admin changes BugFix configuration
- **WHEN** an administrator saves a BugFix model and endpoint
- **THEN** the next BugFix execution uses those settings and analysis model settings remain unchanged

### Requirement: Evidence context survives dispatch
The system SHALL preserve the analysis question, history hints, full analysis result, all uploaded log attachments, screenshot originals and OCR text for asynchronous BugFix execution and retries. Missing expected evidence SHALL be reported explicitly.

#### Scenario: Multi-attachment analysis dispatches a repair
- **WHEN** a successful analysis with multiple logs and screenshots dispatches BugFix
- **THEN** BugFix receives the same task context and evidence bytes after the analysis workspace is cleaned up

### Requirement: Independent rejection and complete accounting
BugFix SHALL independently review every proposal and MAY reject an incorrect or unsupported proposal with a reason grounded in the available evidence. The system SHALL display rejected outcomes distinctly and require every proposed item to be accounted for before reporting success.

#### Scenario: Analysis proposes an unnecessary repair
- **WHEN** BugFix finds the proposal contradicted by source and logs
- **THEN** it returns a rejected outcome with evidence, creates no MR for that item, and completes the review successfully

#### Scenario: SDK fails or omits an outcome
- **WHEN** execution ends with a terminal SDK error or unaccounted proposed items
- **THEN** the task records actionable failure detail and cannot report complete success
