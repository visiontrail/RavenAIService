## ADDED Requirements

### Requirement: Project repo members authorize Raven package metadata editing
The system SHALL use `project_repo_member` as the source of project-member authorization for editing Raven package descriptions and tags. A membership row SHALL grant edit permission only for packages whose normalized `projectCode` resolves to the same enabled `project_repo` row. Adding or removing a member in backend project management SHALL affect this package metadata edit permission without requiring a package metadata migration.

#### Scenario: Newly added project member gains package metadata edit permission
- **WHEN** a global admin adds user `alice` as a member of enabled project repo `alpha` in backend project management
- **AND** package `pkg-1` has `projectCode == "alpha"`
- **THEN** `alice` is authorized to edit `pkg-1` description and tags

#### Scenario: Removed project member loses package metadata edit permission
- **WHEN** user `alice` is removed from project repo `alpha`
- **AND** package `pkg-1` has `projectCode == "alpha"`
- **THEN** `alice` is no longer authorized to edit `pkg-1` description and tags

#### Scenario: Membership does not cross project boundaries
- **WHEN** user `alice` is a member of project repo `alpha`
- **AND** package `pkg-2` has `projectCode == "beta"`
- **THEN** `alice` is not authorized by the `alpha` membership to edit `pkg-2` description or tags

#### Scenario: Disabled project does not grant member edit permission
- **WHEN** user `alice` is a member of project repo `alpha`
- **AND** project repo `alpha` is disabled
- **AND** package `pkg-1` has `projectCode == "alpha"`
- **THEN** `alice` is not authorized by that membership to edit `pkg-1` description or tags

### Requirement: Project management member copy describes package metadata permission
The backend project management UI SHALL describe project members as users who can access the existing project-scoped capabilities and edit Raven package descriptions and tags for packages associated with that project. The copy SHALL NOT imply that project members can edit package files, versions, project association, or other non-metadata fields.

#### Scenario: Member management hint mentions package metadata editing
- **WHEN** an admin opens project member management for a project
- **THEN** the member permission hint includes Raven package description and tag editing
- **AND** the hint does not state or imply full package administration access
