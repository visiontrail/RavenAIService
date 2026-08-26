## ADDED Requirements

### Requirement: Log API exposes normalized analysis attribution
The system SHALL return an `ai_analysis_triggered_by` object for a log when the latest or currently active AI analysis has durable trigger evidence, and SHALL return `null` when no trigger can be established.

#### Scenario: Completed analysis contains a user snapshot
- **WHEN** a log's latest AI-analysis result contains trigger user information
- **THEN** the log list response exposes that trigger through `ai_analysis_triggered_by`

#### Scenario: New analysis is active after an older result
- **WHEN** a queued or running standalone analysis has trigger information and the log also has an older completed result
- **THEN** the log response exposes the active analysis trigger rather than the older result trigger

#### Scenario: Historical AI Chat analysis lacks embedded attribution
- **WHEN** an AI Chat log has no embedded trigger snapshot but a matching persisted chat-agent run exists
- **THEN** the system best-effort reconstructs `ai_analysis_triggered_by` from that run and its user

#### Scenario: Attribution cannot be recovered
- **WHEN** a log has no embedded trigger and no matching durable run evidence
- **THEN** the API returns `ai_analysis_triggered_by` as `null`

### Requirement: Standalone analysis captures the initiating user
The system SHALL capture a bounded user snapshot when `POST /api/v1/logs/{log_id}/analyze` is invoked and SHALL preserve it through the terminal analysis result.

#### Scenario: Authenticated user starts analysis
- **WHEN** an authenticated user starts standalone log analysis
- **THEN** the task metadata records the user's ID, username, display name, and email values that are available at enqueue time

#### Scenario: Anonymous caller starts analysis
- **WHEN** a caller without an authenticated user starts standalone log analysis
- **THEN** the task records trigger evidence without fabricating a user identity

#### Scenario: Worker stores the final result
- **WHEN** the standalone analysis worker persists a result that does not contain `triggered_by`
- **THEN** the worker copies the task trigger snapshot into that result before saving it

### Requirement: Log list displays the triggering user responsively
The log list SHALL display the AI-analysis triggering user on desktop and mobile using localized labels and deterministic identity fallbacks.

#### Scenario: Named user is available
- **WHEN** attribution contains user fields
- **THEN** the UI displays the first non-empty value from display name, username, email, and user ID

#### Scenario: Trigger is anonymous
- **WHEN** trigger evidence exists but contains no user identity
- **THEN** the UI displays the localized anonymous-user label

#### Scenario: No trigger evidence exists
- **WHEN** `ai_analysis_triggered_by` is null or absent
- **THEN** the UI displays `-`

#### Scenario: Responsive presentation
- **WHEN** the log list is viewed on desktop or mobile
- **THEN** desktop shows a dedicated column and mobile shows a labelled metadata item
