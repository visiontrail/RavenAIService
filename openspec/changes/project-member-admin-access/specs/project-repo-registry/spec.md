## MODIFIED Requirements

### Requirement: Admin endpoints provide CRUD and connectivity testing
The system SHALL expose under the existing `/admin` router: `GET /admin/project-repos` (list, paginated), `POST /admin/project-repos` (create), `GET /admin/project-repos/{id}` (read), `PUT /admin/project-repos/{id}` (update), `DELETE /admin/project-repos/{id}` (delete), and `POST /admin/project-repos/{id}/test-connection` (run `git ls-remote`-based check, returning `{success, message, auth_method}`).

Global admins SHALL retain full CRUD and connectivity-test access using the existing admin authorization behavior. Project-member admins SHALL be authorized only for `GET /admin/project-repos`, `GET /admin/project-repos/{id}`, `PUT /admin/project-repos/{id}`, and `POST /admin/project-repos/{id}/test-connection` on enabled projects where they are members. Project-member admin list responses SHALL include only their member projects. Project-member admin update requests SHALL accept only `project_name`, `description`, `repo_url`, and `default_branch`; changes to `enabled`, `git_token`, members, creation, and deletion SHALL require global admin access. Responses SHALL never include the raw `git_token`; instead they SHALL return a boolean `git_token_set` and accept the literal placeholder `••••••••` on global-admin update to mean "do not change".

#### Scenario: Create a project repo entry
- **WHEN** an authenticated global admin POSTs `{project_code:"foo", project_name:"Foo", repo_url:"https://gitlab.example/foo.git"}`
- **THEN** the response is `201` and the row exists with `enabled == true`, `default_branch == "main"`, `git_token == None`

#### Scenario: Update with masked token is no-op for token
- **WHEN** a global admin PUTs `{git_token: "••••••••", project_name: "Foo Renamed"}` on an entry that already has a stored token
- **THEN** the row's `project_name` is updated and `git_token` is unchanged
- **AND** the response includes `git_token_set: true` and no plaintext token

#### Scenario: Delete unused entry
- **WHEN** a global admin DELETEs an entry whose `project_code` has not been used in any in-flight log analysis
- **THEN** the row is removed and the API returns `204`

#### Scenario: Test connection returns structured result
- **WHEN** `POST /admin/project-repos/{id}/test-connection` runs against a reachable repo for an authorized global admin or project-member admin
- **THEN** the response body is `{success: true, message: "...", auth_method: "token_in_url"|"anonymous"|"ssh_key"}`
- **AND** the response does not include a raw git token

#### Scenario: Project-member admin lists only member projects
- **WHEN** a project-member admin belongs to project A but not project B
- **AND** the user calls `GET /admin/project-repos`
- **THEN** the response has status 200
- **AND** the response contains project A
- **AND** the response does not contain project B

#### Scenario: Project-member admin reads member project
- **WHEN** a project-member admin calls `GET /admin/project-repos/{id}` for a project they belong to
- **THEN** the response has status 200 with that project data
- **AND** the response does not include a raw git token

#### Scenario: Project-member admin cannot read non-member project
- **WHEN** a project-member admin calls `GET /admin/project-repos/{id}` for an enabled project they do not belong to
- **THEN** the response has status 404

#### Scenario: Project-member admin updates allowed project fields
- **WHEN** a project-member admin PUTs `{project_name:"New Name", description:"Updated", repo_url:"https://gitlab.example/new.git", default_branch:"develop"}` to a project they belong to
- **THEN** the response has status 200
- **AND** those fields are updated

#### Scenario: Project-member admin cannot update restricted project fields
- **WHEN** a project-member admin PUTs a payload containing `enabled` or `git_token` for a project they belong to
- **THEN** the response has status 403 or 422
- **AND** the restricted fields are not changed

#### Scenario: Project-member admin cannot create or delete projects
- **WHEN** a project-member admin calls `POST /admin/project-repos` or `DELETE /admin/project-repos/{id}`
- **THEN** the response has status 403

## ADDED Requirements

### Requirement: Project-level system prompt endpoints are project-scoped
The system SHALL expose project-level system prompt read and update endpoints under `/admin/project-repos/{project_code}/system-prompt`. These endpoints SHALL admit global admins for any valid project code and project-member admins only when the normalized project code maps to an enabled project where the current user is a member. Project-member admins SHALL receive 404 for non-member, disabled, or unknown project codes. The prompt content SHALL remain constrained by existing project prompt validation.

#### Scenario: Project-member admin reads own project system prompt
- **WHEN** a project-member admin calls `GET /admin/project-repos/alpha/system-prompt` for a project they belong to
- **THEN** the response has status 200
- **AND** the response includes that project's prompt content metadata

#### Scenario: Project-member admin updates own project system prompt
- **WHEN** a project-member admin calls `PUT /admin/project-repos/alpha/system-prompt` with valid `content` for a project they belong to
- **THEN** the response has status 200
- **AND** subsequent reads return the updated content

#### Scenario: Project-member admin cannot access another project's system prompt
- **WHEN** a project-member admin calls `GET` or `PUT` on `/admin/project-repos/beta/system-prompt` for a project they do not belong to
- **THEN** the response has status 404

#### Scenario: Global admin can manage any valid project system prompt
- **WHEN** a global admin calls `GET` or `PUT` on `/admin/project-repos/beta/system-prompt`
- **THEN** the request is authorized according to the existing project prompt validation rules
