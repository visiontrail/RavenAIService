## 1. Backend Auth Principal

- [ ] 1.1 Add a structured admin principal model that represents legacy global admin, admin-role user, and project-member admin identities.
- [ ] 1.2 Add authorization dependencies for global-admin-only routes, project-member-or-global admin routes, project lookup by repo id, and project lookup by project code.
- [ ] 1.3 Update `/admin/auth/me` response schemas to return access level, allowed navigation keys, and allowed project identifiers.
- [ ] 1.4 Keep `/admin/auth/login` legacy admin credential behavior unchanged.

## 2. Project Repo And Project Settings APIs

- [ ] 2.1 Update `GET /admin/project-repos` so global admins see the existing result set and project-member admins see only enabled member projects.
- [ ] 2.2 Update `GET /admin/project-repos/{id}` so project-member admins can read member projects and receive 404 for non-member projects.
- [ ] 2.3 Update `PUT /admin/project-repos/{id}` so project-member admins can change only `project_name`, `description`, `repo_url`, and `default_branch`.
- [ ] 2.4 Ensure project-member admins cannot create projects, delete projects, update `enabled` or `git_token`, or manage project members.
- [ ] 2.5 Allow `POST /admin/project-repos/{id}/test-connection` for member projects without exposing raw tokens.
- [ ] 2.6 Update project-level system prompt endpoints to allow global admins for valid project codes and project-member admins only for their own enabled projects.

## 3. Project Skill APIs

- [ ] 3.1 Update project Skill list/upload/toggle/delete/file endpoints to authorize global admins or project-member admins for the matching normalized project code.
- [ ] 3.2 Preserve global-admin project Skill pre-provisioning for unknown project codes.
- [ ] 3.3 Return 404 for project-member admins when the project code is unknown, disabled, or not in their memberships.
- [ ] 3.4 Ensure rejected project-member Skill writes do not create, modify, or delete files under non-member project Skill directories.

## 4. Frontend Admin Scope

- [ ] 4.1 Extend admin API types and client handling for `/admin/auth/me` access level, allowed navigation keys, and allowed project identifiers.
- [ ] 4.2 Update admin route entry behavior so project-member admins are sent from `/admin` to `/admin/project-repos`.
- [ ] 4.3 Filter admin navigation so project-member admins see only project repository and project-specific Skill/settings surfaces.
- [ ] 4.4 Update project repo UI controls so project-member admins do not see global-only actions such as create, delete, member management, token editing, or global settings links.
- [ ] 4.5 Guard the Project Skills view so project-member admins can render controls only for allowed project codes.
- [ ] 4.6 Add or update localization strings for project-member admin access and forbidden/not-found states.

## 5. Tests

- [ ] 5.1 Add backend tests for `/admin/auth/me` covering global admin, project-member admin, user without memberships, and unauthenticated callers.
- [ ] 5.2 Add backend tests for project repo scoped list/read/update/test-connection and forbidden global-only actions.
- [ ] 5.3 Add backend tests for project-level system prompt read/update on member and non-member projects.
- [ ] 5.4 Add backend tests for project Skill API access by global admin, project-member admin, non-member, unknown project, and unauthenticated caller.
- [ ] 5.5 Add frontend tests for admin nav filtering, `/admin` redirect behavior, project repo action visibility, and Project Skills route guarding.

## 6. Validation

- [ ] 6.1 Run the targeted backend test suite for admin project members, project repos, project prompts, and project Skills.
- [ ] 6.2 Run the targeted frontend tests for admin routing/navigation and Project Skills UI.
- [ ] 6.3 Run OpenSpec status/validation for `project-member-admin-access` and address any artifact errors.
