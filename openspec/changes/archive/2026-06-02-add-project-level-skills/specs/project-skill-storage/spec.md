## ADDED Requirements

### Requirement: Project skills are stored in a dedicated directory tree keyed by project_code

The system SHALL store project-level skills under `<project_skills_data_dir>/<project_code>/store/<skill_name>/`, with a per-project registry at `<project_skills_data_dir>/<project_code>/_registry.json`. The `project_skills_data_dir` SHALL be configurable via `settings.project_skills_data_dir` (default `data/project_skills`). The directory layout SHALL mirror the existing agent skills layout (`_registry.json` + `store/<name>/SKILL.md`).

#### Scenario: First skill installed creates directory structure

- **WHEN** a skill is installed for project_code `"my_project"` and no prior project skills exist for that project
- **THEN** the directory `<project_skills_data_dir>/my_project/store/<skill_name>/` is created containing the extracted skill files
- **AND** `<project_skills_data_dir>/my_project/_registry.json` exists and contains exactly one entry

#### Scenario: Directory layout mirrors agent skills

- **WHEN** a project skill is installed
- **THEN** the `_registry.json` entry format matches agent skill entries: `id`, `name`, `description`, `enabled`, `source_filename`, `size_bytes`, `installed_at`, `updated_at`, `dir_name`

### Requirement: Project skill installation reuses the same zip validation and SKILL.md parsing as agent skills

The system SHALL validate project skill zip uploads using the same constraints as agent skills: `MAX_SKILL_ZIP_BYTES` (50 MiB), `MAX_SKILL_EXTRACTED_BYTES` (200 MiB), `MAX_SKILL_FILE_COUNT` (1000). The zip MUST contain a `SKILL.md` with valid frontmatter including a `name` field matching `^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$`. The extraction MUST apply the same security checks (zip-slip prevention, ignored path filtering).

#### Scenario: Valid zip installed successfully

- **WHEN** a valid skill zip containing `SKILL.md` with `name: "android_debug"` is uploaded for project `"my_android"`
- **THEN** the skill is extracted to `<project_skills_data_dir>/my_android/store/android_debug/`
- **AND** the registry entry has `name == "android_debug"` and `enabled == True`

#### Scenario: Zip without SKILL.md is rejected

- **WHEN** a zip file without any `SKILL.md` is uploaded as a project skill
- **THEN** installation fails with `SkillValidationError`
- **AND** no files are written to the project skills directory

#### Scenario: Duplicate name without overwrite is rejected

- **WHEN** a skill with `name == "existing_skill"` is already installed for the project and a new zip with the same name is uploaded without `overwrite=True`
- **THEN** installation fails with `SkillConflictError`

### Requirement: Project skills support enable/disable and deletion

The system SHALL support enabling/disabling individual project skills by updating the `enabled` field in the project's `_registry.json`. Deleting a project skill SHALL remove both the `_registry.json` entry and the on-disk skill directory.

#### Scenario: Disabled skill excluded from listing

- **WHEN** a project skill is disabled via `set_project_skill_enabled(project_code, skill_id, False)`
- **THEN** `list_project_skills(project_code)` returns the skill with `enabled == False`
- **AND** the skill is NOT included in materialization candidates

#### Scenario: Deleted skill removed from disk

- **WHEN** `delete_project_skill(project_code, skill_id)` is called for an existing skill
- **THEN** the skill directory under `store/` no longer exists
- **AND** the `_registry.json` no longer contains an entry for that skill_id

### Requirement: Project skill listing validates disk presence

The system SHALL, when listing project skills, check that each registry entry's on-disk directory and `SKILL.md` file exist. Entries whose disk directory is missing SHALL be silently removed from the registry and excluded from the response.

#### Scenario: Orphaned registry entry cleaned up

- **WHEN** a project skill's on-disk directory is manually deleted but the registry entry remains
- **THEN** `list_project_skills(project_code)` does NOT include the orphaned entry
- **AND** the registry is updated to remove the orphaned entry

### Requirement: Project code validation for skill operations

The system SHALL validate that the `project_code` used in skill operations is a non-empty string. The system SHALL NOT require the project_code to exist in the ProjectRepo database — this allows pre-provisioning skills before a project is registered. The project_code SHALL be normalized to lowercase before use as a directory name.

#### Scenario: Project code normalized to lowercase

- **WHEN** a skill is installed for project_code `"MyProject"`
- **THEN** the skill is stored under `<project_skills_data_dir>/myproject/`

#### Scenario: Empty project code rejected

- **WHEN** a skill operation is attempted with an empty project_code
- **THEN** the operation fails with `SkillValidationError`
