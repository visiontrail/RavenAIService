## ADDED Requirements

### Requirement: Global administrator announcement management
The system SHALL provide a dedicated Admin navigation tab where a global administrator can inspect, publish or replace, and deactivate the single current system announcement. Project-member administrators MUST NOT be permitted to manage global announcements.

#### Scenario: Publish an announcement
- **WHEN** a global administrator submits a valid title and message
- **THEN** the system stores an active current announcement with a new unique ID, publisher identity, and publication timestamp

#### Scenario: Preview Markdown before publication
- **WHEN** a global administrator enters Markdown in the announcement message and selects preview
- **THEN** the Admin UI renders a faithful preview using the same safe Markdown rules used by the user announcement dialog

#### Scenario: Replace an announcement
- **WHEN** a global administrator publishes while another announcement exists
- **THEN** the system replaces the current announcement and assigns a new ID so all users are eligible to see it

#### Scenario: Deactivate the current announcement
- **WHEN** a global administrator deactivates the current announcement
- **THEN** the system retains it for Admin inspection but no longer delivers it to users

#### Scenario: Reject project-member management
- **WHEN** a project-member administrator calls an announcement management endpoint
- **THEN** the system rejects the request and the Admin UI does not expose the announcement tab to that principal

### Requirement: Pending announcement delivery
The system SHALL return the current active announcement to an authenticated user only when that user has not acknowledged its ID. The workbench SHALL check this state on authenticated entry or refresh, after authentication completes, and when the user starts a new conversation.

#### Scenario: First visit after publication
- **WHEN** an authenticated user visits or refreshes the workbench after a new announcement is published and has not acknowledged its ID
- **THEN** the announcement is displayed in a modal dialog with its Markdown formatting rendered

#### Scenario: Render announcement content safely
- **WHEN** announcement content contains Markdown and raw HTML
- **THEN** supported Markdown is rendered while raw HTML remains escaped and cannot execute in the user interface

#### Scenario: Follow the user's color preference
- **WHEN** the announcement dialog is displayed in a light or dark presentation context
- **THEN** the dialog uses the corresponding accessible palette without changing its content or acknowledgement behavior

#### Scenario: New conversation after publication
- **WHEN** an authenticated user starts a new conversation after publication and has not acknowledged the current announcement
- **THEN** the workbench checks pending state and displays the announcement

#### Scenario: No active announcement
- **WHEN** no active current announcement exists
- **THEN** the pending-announcement response contains no announcement and the workbench remains uninterrupted

#### Scenario: Unauthenticated request
- **WHEN** a caller without a valid user token requests a pending announcement
- **THEN** the system rejects the request using the existing user authentication behavior

### Requirement: Once-per-user acknowledgement
The system SHALL persist a successful announcement dismissal against the authenticated user so the same announcement is not displayed to that user again on any browser or device.

#### Scenario: Dismiss an announcement
- **WHEN** a user closes the displayed current announcement and persistence succeeds
- **THEN** the system records its ID for that user and subsequent pending checks do not return the same announcement

#### Scenario: A different user visits
- **WHEN** another user who has not acknowledged the current ID visits the workbench
- **THEN** the system returns and displays the announcement to that user independently

#### Scenario: Announcement changes before dismissal
- **WHEN** a user attempts to acknowledge an ID that is no longer the current active announcement
- **THEN** the system does not acknowledge the newer announcement and instructs the client to refresh pending state

#### Scenario: Acknowledgement fails
- **WHEN** the server cannot persist a user's dismissal
- **THEN** the client keeps the announcement open, reports the failure, and does not mark it as dismissed locally

### Requirement: Upgrade-safe minimal persistence
The system SHALL persist the current announcement without an announcement table and SHALL use one nullable user acknowledgement column, with both formal migration and startup schema synchronization compatibility.

#### Scenario: Upgrade an existing database
- **WHEN** an existing installation upgrades to this version
- **THEN** the nullable acknowledgement column is added without a backfill and all existing user and conversation data remains valid

#### Scenario: Start without a runtime announcement
- **WHEN** the upgraded application starts with no announcement key in runtime settings
- **THEN** it behaves as though no announcement is active

#### Scenario: Roll back application code
- **WHEN** application code is rolled back after the additive migration
- **THEN** the older application ignores the extra nullable column and continues operating
