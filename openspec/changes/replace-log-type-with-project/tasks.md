## 1. Database Migration

- [ ] 1.1 Create Alembic migration: add nullable `project_id` integer FK column to `log_records` referencing `project_repo.id` with `ON DELETE SET NULL`
- [ ] 1.2 Seed "full" project entry in `project_repo` table (`project_code='full'`, `project_name='Full Log'`, `repo_url=''`, `enabled=true`) if not already present
- [ ] 1.3 Backfill `project_id` for all existing `log_records` by mapping `log_type` enum values to corresponding `project_repo.project_code` entries
- [ ] 1.4 Drop `log_type` column and `logtype` PostgreSQL enum type
- [ ] 1.5 Write downgrade migration that re-adds `log_type` column and backfills from `project_id`

## 2. Backend Models

- [ ] 2.1 Remove `LogType` enum class from `app/models/log.py`
- [ ] 2.2 Replace `log_type` mapped column with `project_id` nullable FK column in `LogRecord`
- [ ] 2.3 Update `LogFileInfo` Pydantic model: remove `log_type`, add `project_id`, `project_code`, `project_name`
- [ ] 2.4 Update `LogUploadRequest` Pydantic model: remove `log_type`, add optional `project_code` and `project_id`
- [ ] 2.5 Update `LogListRequest` Pydantic model: remove `log_type` filter, add optional `project_id` filter

## 3. Backend Services

- [ ] 3.1 Replace `_infer_log_type_from_filename()` in `app/api/logs.py` with `infer_project_from_filename()` that resolves to a `ProjectRepo` entry
- [ ] 3.2 Replace `_infer_log_type_from_components()` with equivalent project-based resolution
- [ ] 3.3 Update `LogService.create_log()` to accept and store `project_id` instead of `log_type`
- [ ] 3.4 Update `LogService.get_logs()` to filter by `project_id` instead of `log_type`
- [ ] 3.5 Update `LogService._record_to_info()` to populate `project_code` and `project_name` by joining with `project_repo`
- [ ] 3.6 Update OAM-specific logic (status/progress defaults) to check `project_code == 'oam_antenna'` via project lookup instead of `log_type == LogType.OAM_ANTENNA`

## 4. Upload API Endpoints

- [ ] 4.1 Update `POST /api/v1/logs/upload` endpoint: replace `log_type` form field with optional `project_code`/`project_id`, implement resolution logic (explicit → inferred → NULL)
- [ ] 4.2 Update `POST /api/v1/logs/upload-simple` endpoint with same changes
- [ ] 4.3 Update `POST /api/v1/logs/upload-t04-batch` endpoint: replace log_type inference with project-based resolution, add optional `project_code` default parameter
- [ ] 4.4 Update `GET /api/v1/logs` endpoint: replace `log_type` query parameter with `project_id` filter

## 5. AI Analysis Pipeline

- [ ] 5.1 Update `_resolve_project_code_for_analysis()` in `app/tasks/ai_analysis.py` to use `project_id` FK lookup instead of `log_type`-based resolution
- [ ] 5.2 Update `_bind_query_to_workspace()` to pass `project_id` instead of `log_type` in workspace metadata
- [ ] 5.3 Update `app/tasks/log_processing.py` to reference `project_id` instead of `log_type` in logging and status logic
- [ ] 5.4 Update `app/agents/log_analysis/workspace.py` context building to use `project_id`/`project_code`
- [ ] 5.5 Update `app/agents/log_analysis/prompts.py` `get_prompts()` to accept `project_code` string instead of `log_type`
- [ ] 5.6 Update `app/agents/log_analysis/agent.py` references from `log_type` to `project_code`/`project_id`
- [ ] 5.7 Update `app/utils/file_upload_validator.py` `determine_log_type_from_filename()` to return project_code string or remove in favor of centralized inference

## 6. Admin API

- [ ] 6.1 Update `DELETE /admin/project-repos/{id}` to check for associated `LogRecord` rows and return HTTP 409 if found (unless `force=true`)
- [ ] 6.2 Allow `repo_url` empty string in `project_repo` for categorization-only projects

## 7. Frontend

- [ ] 7.1 Update `frontend/src/types/index.ts`: replace `log_type` field with `project_id`, `project_code`, `project_name`
- [ ] 7.2 Update `frontend/src/stores/logs.ts`: replace `log_type` filter with `project_id` filter
- [ ] 7.3 Update `frontend/src/api/index.ts`: replace `log_type` query parameter with `project_id`
- [ ] 7.4 Update `frontend/src/views/LogList.vue`: replace hardcoded log-type dropdown with dynamic project selector from `GET /api/v1/project-repos`, update table column and pill display
- [ ] 7.5 Update `frontend/src/views/LogDetail.vue`: replace log type label/pill with project name display
- [ ] 7.6 Update `frontend/src/views/AdminPrompts.vue`: remove `log_type_keys` references if applicable
- [ ] 7.7 Handle `project_id=null` display as "Unclassified" in both list and detail views

## 8. Tests

- [ ] 8.1 Update `tests/test_log_analysis_agent.py` to use `project_id` instead of `log_type`
- [ ] 8.2 Update `tests/test_ai_analysis_repo_injection.py` to use project-based resolution
- [ ] 8.3 Update `tests/test_workspace.py` to use `project_id` in workspace context
- [ ] 8.4 Add test for `infer_project_from_filename()` with known and unknown patterns
- [ ] 8.5 Add test for upload API with `project_code`, `project_id`, and no-project scenarios
- [ ] 8.6 Add test for log list filtering by `project_id` including NULL filter
- [ ] 8.7 Add test for admin delete protection (409 when logs reference the project)
