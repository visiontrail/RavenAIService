## ADDED Requirements

### Requirement: List project skills endpoint
The system SHALL expose `GET /admin/project-repos/{project_code}/skills` returning all installed skills for the given project. The response SHALL use the same `SkillListResponse` schema as agent skills (`success`, `data: List[SkillData]`, `message`). The endpoint SHALL require either global admin authentication or project-member admin authorization for the normalized `project_code`. Global admins SHALL retain existing behavior for unknown project codes. Project-member admins SHALL receive 404 for project codes that are unknown, disabled, or not in their memberships.

#### Scenario: List skills for project with installed skills
- **WHEN** `GET /admin/project-repos/my_project/skills` is called by a global admin or a project-member admin for `my_project`
- **AND** project `"my_project"` has 2 installed skills
- **THEN** the response has status 200 with `data` containing 2 `SkillData` entries

#### Scenario: List skills for project with no skills
- **WHEN** `GET /admin/project-repos/my_project/skills` is called by an authorized global admin or project-member admin
- **AND** project `"my_project"` has no installed skills
- **THEN** the response has status 200 with `data` as an empty array

#### Scenario: Global admin lists unknown project skills
- **WHEN** `GET /admin/project-repos/unknown_project/skills` is called by a global admin
- **THEN** the response has status 200 with `data` as an empty array

#### Scenario: Project member cannot list non-member project skills
- **WHEN** a project-member admin for project `alpha` calls `GET /admin/project-repos/beta/skills`
- **THEN** the response has status 404

#### Scenario: Unauthenticated request rejected
- **WHEN** the endpoint is called without credentials
- **THEN** the response has status 401

### Requirement: Upload project skill endpoint
The system SHALL expose `POST /admin/project-repos/{project_code}/skills` accepting a zip file upload and an optional `overwrite` query parameter. The endpoint SHALL install the skill using the project skill storage service. The response SHALL use `SkillResponse` schema with status 201 on success. The endpoint SHALL require either global admin authentication or project-member admin authorization for the normalized `project_code`. Project-member admins SHALL NOT upload Skills for unknown, disabled, or non-member projects.

#### Scenario: Successful upload creates skill
- **WHEN** a valid skill zip is POSTed to `/admin/project-repos/my_project/skills` by a global admin or a project-member admin for `my_project`
- **THEN** the response has status 201 with the installed skill's metadata
- **AND** the skill appears in subsequent `GET /admin/project-repos/my_project/skills`

#### Scenario: Duplicate name without overwrite returns 409
- **WHEN** a zip with the same skill name as an existing project skill is POSTed without `overwrite=true` by an authorized caller
- **THEN** the response has status 409 (Conflict)

#### Scenario: Invalid zip returns 422
- **WHEN** a zip without `SKILL.md` is POSTed by an authorized caller
- **THEN** the response has status 422 with a descriptive error message

#### Scenario: Project member cannot upload to non-member project
- **WHEN** a project-member admin for project `alpha` POSTs a skill zip to `/admin/project-repos/beta/skills`
- **THEN** the response has status 404
- **AND** no files are written under project `beta`

### Requirement: Toggle project skill enabled state endpoint
The system SHALL expose `PATCH /admin/project-repos/{project_code}/skills/{skill_id}` accepting `{"enabled": bool}`. The endpoint SHALL update the skill's enabled state in the project registry. The endpoint SHALL require either global admin authentication or project-member admin authorization for the normalized `project_code`.

#### Scenario: Disable a project skill
- **WHEN** `PATCH /admin/project-repos/my_project/skills/android_debug` is called by a global admin or a project-member admin for `my_project` with `{"enabled": false}`
- **THEN** the response has status 200 with the updated skill data showing `enabled == false`

#### Scenario: Non-existent skill returns 404
- **WHEN** `PATCH /admin/project-repos/my_project/skills/nonexistent` is called by an authorized caller
- **THEN** the response has status 404

#### Scenario: Project member cannot toggle non-member project skill
- **WHEN** a project-member admin for project `alpha` calls `PATCH /admin/project-repos/beta/skills/android_debug`
- **THEN** the response has status 404
- **AND** the skill enabled state is unchanged

### Requirement: Delete project skill endpoint
The system SHALL expose `DELETE /admin/project-repos/{project_code}/skills/{skill_id}` which removes the skill from both registry and disk. The response SHALL have status 204 on success. The endpoint SHALL require either global admin authentication or project-member admin authorization for the normalized `project_code`.

#### Scenario: Successful deletion
- **WHEN** `DELETE /admin/project-repos/my_project/skills/android_debug` is called by a global admin or a project-member admin for `my_project` for an existing skill
- **THEN** the response has status 204
- **AND** the skill no longer appears in the listing

#### Scenario: Delete non-existent skill returns 404
- **WHEN** `DELETE /admin/project-repos/my_project/skills/nonexistent` is called by an authorized caller
- **THEN** the response has status 404

#### Scenario: Project member cannot delete non-member project skill
- **WHEN** a project-member admin for project `alpha` calls `DELETE /admin/project-repos/beta/skills/android_debug`
- **THEN** the response has status 404
- **AND** the skill remains installed for project `beta`

### Requirement: Project skill file browsing endpoints
The system SHALL expose `GET /admin/project-repos/{project_code}/skills/{skill_id}/files` returning the skill's directory tree, and `GET /admin/project-repos/{project_code}/skills/{skill_id}/file?path=<rel_path>` returning a specific file's content. These SHALL reuse the same response schemas (`SkillFilesResponse`, `SkillFileContentResponse`) and logic as agent skill file browsing. The endpoints SHALL require either global admin authentication or project-member admin authorization for the normalized `project_code`.

#### Scenario: Browse skill file tree
- **WHEN** `GET /admin/project-repos/my_project/skills/android_debug/files` is called by a global admin or a project-member admin for `my_project`
- **THEN** the response contains a tree structure with the skill's files

#### Scenario: Read skill file content
- **WHEN** `GET /admin/project-repos/my_project/skills/android_debug/file?path=SKILL.md` is called by a global admin or a project-member admin for `my_project`
- **THEN** the response contains the file content as UTF-8 text

#### Scenario: Project member cannot browse non-member project skill files
- **WHEN** a project-member admin for project `alpha` calls a project skill file browsing endpoint for project `beta`
- **THEN** the response has status 404
