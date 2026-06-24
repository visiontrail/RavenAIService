## ADDED Requirements

### Requirement: Project-member admins can manage Skills for member projects
The admin frontend SHALL allow project-member admins to open the Project Skills management view only for projects included in their admin identity scope. For an allowed project, the UI SHALL provide the same project Skill list, upload with overwrite, enable/disable, delete, and file-preview controls available to global admins.

#### Scenario: Project member opens Skill management for own project
- **WHEN** a project-member admin belongs to project `alpha`
- **AND** the user opens `/admin/project-repos/alpha/skills`
- **THEN** the Project Skills view loads successfully
- **AND** the user can list, upload, overwrite, enable, disable, delete, and preview project Skills for `alpha`

#### Scenario: Project member modifies an existing Skill by overwrite upload
- **WHEN** a project-member admin uploads a valid zip with `overwrite=true` for an existing Skill in their project
- **THEN** the UI calls the project Skill upload endpoint with the current project code
- **AND** the refreshed list shows the updated Skill metadata

### Requirement: Project-member admins cannot navigate to non-member Project Skills
The admin frontend SHALL prevent project-member admins from rendering Project Skills management for project codes outside their allowed project scope. A direct route to a non-member project code SHALL show a forbidden or not-found state and SHALL NOT display Skill management controls.

#### Scenario: Direct non-member Skill route is blocked
- **WHEN** a project-member admin for project `alpha` navigates directly to `/admin/project-repos/beta/skills`
- **THEN** the frontend does not render the Project Skills controls for `beta`
- **AND** the backend request for `beta` returns 404

### Requirement: Project-member admin project list exposes Skill actions only for visible projects
The admin project repository page SHALL list only projects available to the current project-member admin. Skill management actions SHALL appear only on those visible rows. Global admins SHALL continue to see Skill actions for all projects allowed by the existing admin project list.

#### Scenario: Project member sees Skill action only on member project row
- **WHEN** a project-member admin belongs to project `alpha` but not project `beta`
- **AND** the user opens `/admin/project-repos`
- **THEN** the table includes project `alpha`
- **AND** the table does not include project `beta`
- **AND** the Skill management action is available only for project `alpha`
