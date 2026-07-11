## ADDED Requirements

### Requirement: Every project has a required project card
`ProjectRepo` SHALL store a trimmed, non-empty `project_card` text value. Admin create requests MUST include a project card, explicit updates MUST reject a blank card, and admin/public project responses SHALL return `project_card` instead of the optional `description` field. The card SHALL describe enough project scope and boundaries for users and Agents to decide whether a question belongs to the project.

#### Scenario: Create rejects a missing project card
- **WHEN** an administrator creates a project without `project_card` or with whitespace only
- **THEN** the API returns a validation error
- **AND** no project row is created

#### Scenario: Project card is normalized and returned
- **WHEN** an administrator creates a project with a non-empty project card surrounded by whitespace
- **THEN** the stored value is trimmed
- **AND** both admin and public project responses return the trimmed `project_card`

#### Scenario: Update cannot clear the card
- **WHEN** an authorized administrator updates an existing project with an empty or whitespace-only `project_card`
- **THEN** the API rejects the update
- **AND** the existing project card remains unchanged

### Requirement: Legacy descriptions migrate without nullable cards
The database migration SHALL preserve each non-blank `description` value as `project_card`, SHALL backfill a clearly marked scope-incomplete card for every blank legacy row, SHALL rename the column to `project_card`, and SHALL enforce non-null/non-blank writes. PostgreSQL SHALL use `NOT NULL`; SQLite SHALL use an in-place rename plus INSERT/UPDATE triggers so referenced project rows are not cascade-deleted during a table rebuild. Downgrade SHALL retain the text while renaming the column back to nullable `description`.

#### Scenario: Existing description is preserved
- **WHEN** the migration runs for a project whose description is `Satellite telemetry ingestion`
- **THEN** its `project_card` equals `Satellite telemetry ingestion`
- **AND** the row has no `description` column after upgrade

#### Scenario: Blank legacy description receives fallback
- **WHEN** the migration runs for a project with a null or whitespace-only description
- **THEN** its `project_card` is non-empty and identifies the project name/code
- **AND** the card explicitly indicates that the project scope still needs completion

#### Scenario: SQLite upgrade preserves project references
- **WHEN** the migration or runtime schema sync upgrades a SQLite project row referenced by Agent/member/log tables with foreign keys enabled
- **THEN** all referencing rows remain present and continue to reference the same project id
- **AND** subsequent null or blank project-card inserts/updates are rejected by database triggers
