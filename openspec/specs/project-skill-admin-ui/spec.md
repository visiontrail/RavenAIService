## ADDED Requirements

### Requirement: Project detail page includes a Skills management tab

The system SHALL add a "Skills" tab to the project detail/edit page in the admin frontend. The tab SHALL display a list of installed project skills with their name, description, enabled status, file size, and install date.

#### Scenario: Skills tab visible on project detail

- **WHEN** an admin navigates to a project's detail page
- **THEN** a "Skills" tab is available alongside existing project information
- **AND** clicking the tab shows the project's installed skills

#### Scenario: Empty state displayed when no skills

- **WHEN** the Skills tab is active and the project has no installed skills
- **THEN** an empty state message is displayed with a prompt to upload a skill

### Requirement: Upload skill from project detail page

The system SHALL provide a file upload control on the project Skills tab that accepts `.zip` files. The upload SHALL call `POST /admin/project-repos/{project_code}/skills` and refresh the skill list on success. An overwrite checkbox SHALL be available for replacing existing skills.

#### Scenario: Successful upload refreshes list

- **WHEN** admin uploads a valid skill zip via the project Skills tab
- **THEN** the API is called with the project's `project_code`
- **AND** the skill list refreshes to show the newly installed skill

#### Scenario: Upload error displayed

- **WHEN** the upload fails (invalid zip, conflict without overwrite)
- **THEN** an error message is displayed to the admin

### Requirement: Toggle skill enabled state from project detail page

The system SHALL provide an enable/disable toggle for each project skill in the list. Toggling SHALL call `PATCH /admin/project-repos/{project_code}/skills/{skill_id}` and update the UI optimistically.

#### Scenario: Disable then re-enable a skill

- **WHEN** admin toggles a skill from enabled to disabled
- **THEN** the API is called with `{"enabled": false}`
- **AND** the skill's visual state updates to show disabled

### Requirement: Delete skill from project detail page

The system SHALL provide a delete action for each project skill. Deletion SHALL require confirmation and call `DELETE /admin/project-repos/{project_code}/skills/{skill_id}`.

#### Scenario: Confirmed deletion removes skill

- **WHEN** admin clicks delete on a skill and confirms
- **THEN** the API is called and the skill disappears from the list

#### Scenario: Cancelled deletion preserves skill

- **WHEN** admin clicks delete but cancels the confirmation
- **THEN** no API call is made and the skill remains in the list

### Requirement: Skill file preview from project detail page

The system SHALL allow admins to browse a project skill's file tree and preview file contents, reusing the same UI pattern as the agent skill file browser. Clicking a skill SHALL expand to show its file tree; clicking a file SHALL display its content.

#### Scenario: View SKILL.md content

- **WHEN** admin clicks on a project skill and selects `SKILL.md`
- **THEN** the file content is displayed in a code/markdown viewer
