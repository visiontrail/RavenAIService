## ADDED Requirements

### Requirement: Project Expert switches workspaces with the selected project
On a follow-up turn with a different valid `project_repo_id`, Project Expert SHALL create a fresh workspace bound to the newly selected project before starting the Agent. It SHALL keep the same chat session and make the previous text conversation available to the new workspace. Same-project follow-ups SHALL reuse the current workspace. Invalid selections MUST NOT replace the active workspace.

#### Scenario: Switch after a completed turn
- **WHEN** a session bound to project A receives a new message selecting project B
- **THEN** the next Agent run uses a new workspace whose primary project is B
- **AND** no checkout from A is present in that workspace
- **AND** the previous session transcript is available there

#### Scenario: Repeat same project
- **WHEN** a session bound to project A receives another message selecting A
- **THEN** the Agent reuses the existing workspace

#### Scenario: Invalid project switch
- **WHEN** a session bound to project A receives a disabled or unavailable project ID
- **THEN** the service reports an error and keeps the workspace bound to A

#### Scenario: Switch during an active run
- **WHEN** an Agent run is still active and a new message selects a different project
- **THEN** the service reports that the new message must be retried after the active run
- **AND** it does not replace the running workspace
