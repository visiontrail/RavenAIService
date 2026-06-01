## ADDED Requirements

### Requirement: List project skills endpoint

The system SHALL expose `GET /admin/project-repos/{project_code}/skills` returning all installed skills for the given project. The response SHALL use the same `SkillListResponse` schema as agent skills (`success`, `data: List[SkillData]`, `message`). The endpoint SHALL require admin authentication.

#### Scenario: List skills for project with installed skills

- **WHEN** `GET /admin/project-repos/my_project/skills` is called with valid admin credentials
- **AND** project `"my_project"` has 2 installed skills
- **THEN** the response has status 200 with `data` containing 2 `SkillData` entries

#### Scenario: List skills for project with no skills

- **WHEN** `GET /admin/project-repos/unknown_project/skills` is called
- **THEN** the response has status 200 with `data` as an empty array

#### Scenario: Unauthenticated request rejected

- **WHEN** the endpoint is called without admin credentials
- **THEN** the response has status 401

### Requirement: Upload project skill endpoint

The system SHALL expose `POST /admin/project-repos/{project_code}/skills` accepting a zip file upload and an optional `overwrite` query parameter. The endpoint SHALL install the skill using the project skill storage service. The response SHALL use `SkillResponse` schema with status 201 on success.

#### Scenario: Successful upload creates skill

- **WHEN** a valid skill zip is POSTed to `/admin/project-repos/my_project/skills`
- **THEN** the response has status 201 with the installed skill's metadata
- **AND** the skill appears in subsequent `GET /admin/project-repos/my_project/skills`

#### Scenario: Duplicate name without overwrite returns 409

- **WHEN** a zip with the same skill name as an existing project skill is POSTed without `overwrite=true`
- **THEN** the response has status 409 (Conflict)

#### Scenario: Invalid zip returns 422

- **WHEN** a zip without `SKILL.md` is POSTed
- **THEN** the response has status 422 with a descriptive error message

### Requirement: Toggle project skill enabled state endpoint

The system SHALL expose `PATCH /admin/project-repos/{project_code}/skills/{skill_id}` accepting `{"enabled": bool}`. The endpoint SHALL update the skill's enabled state in the project registry.

#### Scenario: Disable a project skill

- **WHEN** `PATCH /admin/project-repos/my_project/skills/android_debug` is called with `{"enabled": false}`
- **THEN** the response has status 200 with the updated skill data showing `enabled == false`

#### Scenario: Non-existent skill returns 404

- **WHEN** `PATCH /admin/project-repos/my_project/skills/nonexistent` is called
- **THEN** the response has status 404

### Requirement: Delete project skill endpoint

The system SHALL expose `DELETE /admin/project-repos/{project_code}/skills/{skill_id}` which removes the skill from both registry and disk. The response SHALL have status 204 on success.

#### Scenario: Successful deletion

- **WHEN** `DELETE /admin/project-repos/my_project/skills/android_debug` is called for an existing skill
- **THEN** the response has status 204
- **AND** the skill no longer appears in the listing

#### Scenario: Delete non-existent skill returns 404

- **WHEN** `DELETE /admin/project-repos/my_project/skills/nonexistent` is called
- **THEN** the response has status 404

### Requirement: Project skill file browsing endpoints

The system SHALL expose `GET /admin/project-repos/{project_code}/skills/{skill_id}/files` returning the skill's directory tree, and `GET /admin/project-repos/{project_code}/skills/{skill_id}/file?path=<rel_path>` returning a specific file's content. These SHALL reuse the same response schemas (`SkillFilesResponse`, `SkillFileContentResponse`) and logic as agent skill file browsing.

#### Scenario: Browse skill file tree

- **WHEN** `GET /admin/project-repos/my_project/skills/android_debug/files` is called
- **THEN** the response contains a tree structure with the skill's files

#### Scenario: Read skill file content

- **WHEN** `GET /admin/project-repos/my_project/skills/android_debug/file?path=SKILL.md` is called
- **THEN** the response contains the file content as UTF-8 text
