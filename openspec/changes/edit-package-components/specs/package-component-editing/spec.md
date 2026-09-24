## ADDED Requirements

### Requirement: Authorized component metadata patch
The metadata PATCH endpoint SHALL accept components as an array of objects with a required non-empty string name and optional string version. It SHALL trim both fields, allow at most 100 entries and 256 characters per field, and reject invalid input with HTTP 400 before any fields are persisted. Existing project-member/admin authorization SHALL apply. Omitting components SHALL preserve them; an empty array SHALL clear them. Other package fields and archive bytes SHALL remain unchanged.

#### Scenario: Save and reload components
- **WHEN** an enabled project member saves component names and versions
- **THEN** PATCH and subsequent detail reads return the persisted components
- **AND** component search reads the updated metadata

#### Scenario: Invalid input or unauthorized caller
- **WHEN** a caller submits invalid component input or lacks edit permission
- **THEN** the request fails with HTTP 400 or the existing 401/403 authorization response
- **AND** no metadata is changed

#### Scenario: Clear components
- **WHEN** an authorized user submits components as an empty array
- **THEN** detail reads return an empty component list

### Requirement: Inline component editor
Authorized detail viewers SHALL be able to add, edit and remove component rows, save, or cancel. Name SHALL be required and version optional. Unauthorized viewers SHALL see read-only pills. Saving SHALL disable component controls; failure SHALL retain the draft. Changing the viewed package SHALL discard component drafts and prevent stale saves from replacing the newly viewed package.

#### Scenario: Edit an empty component list
- **WHEN** an authorized user opens a package without components
- **THEN** the component section offers Edit and allows adding rows and saving

#### Scenario: Cancel or retry
- **WHEN** editing is canceled
- **THEN** displayed data remains unchanged
- **WHEN** saving fails
- **THEN** the draft remains available with an error notification
