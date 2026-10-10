## ADDED Requirements

### Requirement: Fork shared analysis into an owned conversation
The system SHALL allow an authenticated reader of log details to Fork saved analysis turns into a fresh conversation owned by that reader.

#### Scenario: Another user forks multiple turns
- **WHEN** a different logged-in user forks a log with saved analysis
- **THEN** a new session and new message IDs contain the saved questions and answers in order and belong only to that user

#### Scenario: Legacy analysis
- **WHEN** a log has only a legacy analysis result
- **THEN** that question and result are copied as the initial exchange

#### Scenario: Unavailable analysis
- **WHEN** the request is anonymous, the log is deleted or missing, or no analysis exists
- **THEN** the system returns 401, 404, or 422 respectively without creating a session or workspace

### Requirement: Fork workspaces and writes are isolated
The system SHALL create independent log and repository directories for each Fork and SHALL preserve the source analysis during follow-up.

#### Scenario: Independent follow-up
- **WHEN** the fork owner asks another question
- **THEN** the AI receives copied history and independent log files and persists the exchange only in the owner's session without source-log updates or automatic source-log BugFix dispatch

#### Scenario: Multiple attachments and repeated forks
- **WHEN** two users fork a multi-attachment log
- **THEN** all attachments are materialized into different directories and edits in either directory cannot affect the other or the source

#### Scenario: Preparation fails
- **WHEN** an attachment is unavailable or extraction fails
- **THEN** no partial session, registry entry, or newly prepared directory is retained

### Requirement: Fork is discoverable and recoverable in the UI
The system SHALL offer a localized Fork action in log details and restore the log analysis Agent and project when the new conversation is opened or reloaded.

#### Scenario: Open and reload
- **WHEN** the user activates Fork and later reloads their conversation
- **THEN** their saved messages, log workspace context, Agent selection and related project remain available for follow-up
