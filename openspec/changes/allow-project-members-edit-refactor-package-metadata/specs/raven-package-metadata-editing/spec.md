## ADDED Requirements

### Requirement: Package metadata patch API updates description and tags
The system SHALL expose `PATCH /raven/api/packages/{package_id}/metadata` for updating only the Raven package `metadata.description` and `metadata.tags` fields. The endpoint SHALL require an authenticated user, accept a JSON object containing at least one of `description` or `tags`, and return the saved package in the existing success envelope. The endpoint SHALL NOT modify package file path, file size, checksum, name, version, project association, patch flag, components, or created timestamp.

#### Scenario: Authorized user updates description and tags
- **WHEN** an authorized user calls `PATCH /raven/api/packages/pkg-1/metadata` with `{"description":"Release notes", "tags":["ka", "stable"]}`
- **THEN** the package metadata stores `description == "Release notes"` and `tags == ["ka", "stable"]`
- **AND** the response contains the saved package under the existing success response shape
- **AND** non-editable fields such as `path`, `size`, `metadata.sha256`, `version`, `projectCode`, `metadata.isPatch`, `metadata.components`, and `createdAt` are unchanged

#### Scenario: Authorized user clears editable metadata
- **WHEN** an authorized user calls `PATCH /raven/api/packages/pkg-1/metadata` with `{"description": null, "tags": []}`
- **THEN** the package metadata stores an empty description
- **AND** the package metadata stores an empty tag list

#### Scenario: Package does not exist
- **WHEN** an authenticated user calls `PATCH /raven/api/packages/missing/metadata`
- **THEN** the API returns HTTP 404
- **AND** no package metadata file is modified

### Requirement: Package metadata patch API validates and normalizes input
The metadata patch endpoint SHALL normalize editable fields before persistence. `description` SHALL be accepted as a string or null, trimmed, clearable to an empty string, and rejected when it exceeds the configured or implementation-defined maximum length. `tags` SHALL be accepted as an array of strings, trimmed, filtered for non-empty values, deduplicated while preserving first-seen order, and rejected when tag count or individual tag length exceeds the configured or implementation-defined limits.

#### Scenario: Tags are trimmed and deduplicated
- **WHEN** an authorized user calls the metadata patch endpoint with `{"tags":[" stable ", "ka", "stable", ""]}`
- **THEN** the saved package metadata contains `tags == ["stable", "ka"]`

#### Scenario: Invalid tags payload is rejected
- **WHEN** an authorized user calls the metadata patch endpoint with `{"tags":"stable,ka"}`
- **THEN** the API returns HTTP 400
- **AND** the package metadata remains unchanged

#### Scenario: Empty patch body is rejected
- **WHEN** an authorized user calls the metadata patch endpoint with `{}`
- **THEN** the API returns HTTP 400
- **AND** the package metadata remains unchanged

### Requirement: Package metadata edits are authorized by project membership
The metadata patch endpoint SHALL allow edits only when the current user has `role == "admin"` or is a member of the enabled `project_repo` whose normalized `project_code` matches the target package's `projectCode`. Anonymous callers SHALL receive HTTP 401. Authenticated non-members SHALL receive HTTP 403. For non-admin users, packages without a project code, with an unknown project code, or with a disabled project SHALL be treated as not editable and SHALL return HTTP 403.

#### Scenario: Project member edits package metadata for own project
- **WHEN** user `alice` is a member of enabled project repo `alpha`
- **AND** package `pkg-1` has `projectCode == "alpha"`
- **AND** `alice` calls the metadata patch endpoint for `pkg-1`
- **THEN** the API updates the editable metadata fields and returns HTTP 200

#### Scenario: Project member cannot edit another project's package
- **WHEN** user `alice` is a member of project repo `alpha` but not project repo `beta`
- **AND** package `pkg-2` has `projectCode == "beta"`
- **AND** `alice` calls the metadata patch endpoint for `pkg-2`
- **THEN** the API returns HTTP 403
- **AND** package `pkg-2` metadata remains unchanged

#### Scenario: Anonymous caller cannot edit package metadata
- **WHEN** a request without a valid user token calls the metadata patch endpoint
- **THEN** the API returns HTTP 401
- **AND** no package metadata is modified

#### Scenario: Global admin can edit any package metadata
- **WHEN** a user with `role == "admin"` calls the metadata patch endpoint for an existing package
- **THEN** the API updates the editable metadata fields even if the package has no resolvable enabled project

### Requirement: Package detail page supports authorized inline metadata editing
The Raven package detail page SHALL present description and tag editing controls only when the current user is authorized to edit the target package metadata. Authorized users SHALL be able to enter edit mode, change the description and tags, save changes through the metadata patch API, cancel local edits without persisting, and see loading and error states. Unauthorized, anonymous, and read-only viewers SHALL continue to see the existing rendered description and tag pills without edit controls.

#### Scenario: Authorized project member edits description from detail page
- **WHEN** an authorized project member opens a package detail page for their project
- **THEN** the description section exposes an edit action
- **WHEN** the member changes the description and saves
- **THEN** the frontend calls the metadata patch API
- **AND** the page renders the saved description returned by the API

#### Scenario: Authorized project member edits tags from detail page
- **WHEN** an authorized project member opens a package detail page for their project
- **THEN** the tags section exposes tag add and remove controls
- **WHEN** the member adds and removes tags and saves
- **THEN** the frontend calls the metadata patch API with the normalized tag list
- **AND** the page renders the saved tags returned by the API

#### Scenario: Unauthorized viewer sees read-only metadata
- **WHEN** an anonymous user or non-member opens a package detail page
- **THEN** the description and tags sections render in read-only mode
- **AND** no edit, save, cancel, add-tag, or remove-tag controls are shown

#### Scenario: Save failure keeps local edit state
- **WHEN** an authorized user edits metadata on the detail page
- **AND** the metadata patch API returns an error
- **THEN** the page shows an error notification
- **AND** the unsaved draft remains available for correction or cancel

### Requirement: Updated metadata participates in existing package discovery
After a successful metadata edit, updated descriptions and tags SHALL be visible through package detail, package list, tag filtering, text search, and package-search agent tools that read from `RavenPackageService`. The update SHALL use the same persisted metadata fields consumed by upload-created metadata.

#### Scenario: Updated tags are used by package list filtering
- **WHEN** an authorized user changes package `pkg-1` tags to include `stable`
- **THEN** a subsequent `GET /raven/api/packages?tags=stable` includes `pkg-1`

#### Scenario: Updated description is used by text search
- **WHEN** an authorized user changes package `pkg-1` description to include `baseband hotfix`
- **THEN** a subsequent package list search for `baseband hotfix` can match `pkg-1`
