## ADDED Requirements

### Requirement: Explicit-close conversation modal
The admin conversation viewer SHALL appear centered and SHALL close only via its X button during normal interaction.

#### Scenario: Backdrop and Escape do not dismiss
- **WHEN** the admin clicks the backdrop or presses Escape
- **THEN** the conversation and temporary questions remain visible

### Requirement: Mermaid diagram preview
Rendered Mermaid diagrams SHALL open a large, scrollable zoom preview when clicked, including diagrams in temporary answers.

#### Scenario: Inspect a diagram
- **WHEN** the admin clicks a rendered diagram and increases its zoom
- **THEN** a larger preview appears without closing the conversation

### Requirement: Temporary workspace follow-up
An authenticated administrator SHALL ask multiple temporary questions using the selected event's original workspace and conversation context. Temporary turns MUST NOT be persisted in user history, run tables, SDK transcripts or request/response body logs. Workspace access MUST be read-only and scoped to the resolved source workspace.

#### Scenario: Isolated multi-turn review
- **WHEN** an admin asks two follow-up questions
- **THEN** the second request includes the first temporary question and answer
- **AND** original sessions, messages, runs and workspace files remain unchanged

#### Scenario: Close and reopen
- **WHEN** the admin closes the dialog during a request and reopens a conversation
- **THEN** the old request is cancelled and temporary turns are empty

#### Scenario: Source unavailable or wrong owner
- **WHEN** the event has no valid matching run workspace or its workspace was cleaned
- **THEN** the system reports unavailability without creating a substitute workspace or invoking AI

#### Scenario: Admin authentication required
- **WHEN** a caller without admin authentication requests a follow-up
- **THEN** access is denied before workspace access or model invocation
