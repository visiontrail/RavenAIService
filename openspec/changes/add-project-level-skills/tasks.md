## 1. Configuration & Storage Foundation

- [x] 1.1 Add `project_skills_data_dir` setting to `app/config.py` (default `"data/project_skills"`)
- [x] 1.2 Refactor `skills_service.py` internal helpers to accept a `base_dir` parameter instead of hardcoding `_skills_root() / agent_key` — extract `_SkillStore` or parameterized functions for registry IO, path helpers, and `_enabled_entries` so both agent and project skill paths can reuse them
- [x] 1.3 Add project skill path helpers: `_project_skills_root()`, `_project_root(project_code)`, `_project_store_root(project_code)`, `_project_registry_path(project_code)` with project_code lowercase normalization and empty-string validation

## 2. Project Skill CRUD in skills_service

- [x] 2.1 Implement `list_project_skills(project_code)` — load registry, validate disk presence, return public entries (reuse shared logic from step 1.2)
- [x] 2.2 Implement `install_project_skill(project_code, zip_bytes, source_filename, overwrite)` — reuse `_safe_extract_zip`, `_find_skill_root`, `_parse_skill_frontmatter`, write to project store and registry
- [x] 2.3 Implement `set_project_skill_enabled(project_code, skill_id, enabled)` and `delete_project_skill(project_code, skill_id)`
- [x] 2.4 Implement `list_project_skill_files(project_code, skill_id)` and `read_project_skill_file(project_code, skill_id, rel_path)` for file browsing

## 3. Unified Materialization & Relevance Scoring

- [x] 3.1 Add `_project_enabled_entries(project_code)` function that loads enabled project skills with disk validation
- [x] 3.2 Extend `select_relevant_skill_names()` to accept optional `project_code` and merge project skill entries into the scoring pool, returning `List[Tuple[str, str]]` (source, name) or similar to distinguish agent vs project skills
- [x] 3.3 Extend `materialize_enabled_skills()` to accept optional `project_code` — materialize agent skills first, then project skills (overwriting on name conflict)
- [x] 3.4 Extend `materialize_relevant_enabled_skills()` to accept optional `project_code` and pass through to selection and materialization; update default `max_skills` from 3 to 5
- [x] 3.5 Ensure backward compatibility: all extended functions with `project_code=None` behave identically to pre-change

## 4. Agent Integration — ProjectExpertAgent

- [x] 4.1 Update `ProjectExpertAgent.run()` to extract `project_code` from `task_data["repo_info"]["project_code"]` and pass it to `materialize_relevant_enabled_skills(..., project_code=project_code)`
- [x] 4.2 Verify `loaded_skills` in run result and `run_start` trace event includes both agent and project skills

## 5. Agent Integration — LogAnalysisAgent

- [x] 5.1 Update `LogAnalysisAgent.run()` to extract `project_code` from workspace context metadata or task_data and pass it to `materialize_relevant_enabled_skills(..., project_code=project_code)`
- [x] 5.2 Handle the case where project_code is not yet known at skill materialization time (metadata.json not yet read by agent) — use metadata hints from task_data if available, otherwise pass None

## 6. Admin API Endpoints

- [x] 6.1 Add `GET /admin/project-repos/{project_code}/skills` endpoint in `app/api/admin.py` calling `skills_service.list_project_skills`
- [x] 6.2 Add `POST /admin/project-repos/{project_code}/skills` endpoint for zip upload calling `skills_service.install_project_skill`
- [x] 6.3 Add `PATCH /admin/project-repos/{project_code}/skills/{skill_id}` endpoint for enable/disable
- [x] 6.4 Add `DELETE /admin/project-repos/{project_code}/skills/{skill_id}` endpoint
- [x] 6.5 Add `GET /admin/project-repos/{project_code}/skills/{skill_id}/files` and `GET /admin/project-repos/{project_code}/skills/{skill_id}/file` endpoints for file browsing

## 7. Frontend — Project Skill Management UI

- [x] 7.1 Create `ProjectSkills.vue` component with skill list, upload, enable/disable toggle, delete, and file preview — reuse patterns from existing agent skill management UI
- [x] 7.2 Add Skills tab to the project detail/edit page, wired to `/admin/project-repos/{project_code}/skills` API
- [x] 7.3 Add admin API helper functions in `frontend/src/api/admin.ts` for project skill CRUD
- [x] 7.4 Register route and navigation entry for project skills page

## 8. Testing

- [x] 8.1 Unit tests for project skill storage: install, list, enable/disable, delete, disk validation
- [x] 8.2 Unit tests for unified materialization: merged pool scoring, name conflict resolution, backward compat with project_code=None
- [x] 8.3 Integration tests for admin API endpoints: CRUD operations, auth, error cases
- [x] 8.4 Verify agent integration: ProjectExpertAgent and LogAnalysisAgent load project skills when project_code is available
