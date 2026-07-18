# project-repo-membership Specification

## Purpose

Map registered users to the project repositories they belong to, providing membership lookup that scopes bug-fix visibility and access.

## Requirements

### Requirement: Project repo membership maps registered users to projects

The system SHALL provide a `project_repo_member` table (managed via alembic migration) with at minimum: `id` (PK), `project_repo_id` (FK → `project_repo.id`, not null), `user_id` (FK → `users.id`, not null), `created_at`, and a unique constraint over `(project_repo_id, user_id)`. The system SHALL provide a service to list members of a project, list a user's projects, and test whether a given user is a member of a given project.

#### Scenario: Migration creates the membership table

- **WHEN** the alembic migration runs against a fresh database
- **THEN** the `project_repo_member` table exists with a unique constraint over `(project_repo_id, user_id)`

#### Scenario: Membership check resolves visibility

- **WHEN** the service is asked whether user U is a member of project P and a row `(P, U)` exists
- **THEN** the service returns true; otherwise it returns false

### Requirement: Admin endpoints manage project members

The system SHALL expose under the existing `/admin` router: `GET /admin/project-repos/{id}/members` (list members), `POST /admin/project-repos/{id}/members` (add a member by `user_id`), and `DELETE /admin/project-repos/{id}/members/{user_id}` (remove a member). These endpoints SHALL require admin auth using the existing `require_admin` mechanism. Adding an already-existing member SHALL be idempotent (no duplicate row, success response). Member responses SHALL include the user's `id`, `username`, `display_name`, and `email`, and SHALL NOT include password hashes.

#### Scenario: Admin lists members

- **WHEN** an authenticated admin calls `GET /admin/project-repos/{id}/members`
- **THEN** the response lists each member's `id`, `username`, `display_name`, and `email`

#### Scenario: Add member is idempotent

- **WHEN** an admin POSTs a `user_id` that is already a member of the project
- **THEN** no duplicate row is created and the response indicates success

#### Scenario: Remove member

- **WHEN** an admin DELETEs an existing `(project, user)` membership
- **THEN** the membership row is removed and that user loses visibility of the project's bug fixes

#### Scenario: Non-admin is rejected

- **WHEN** a non-admin caller invokes any project member endpoint
- **THEN** the request is rejected by the admin auth guard
