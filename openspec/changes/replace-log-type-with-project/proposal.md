## Why

The `LogRecord` model currently uses a hardcoded `LogType` enum (`stack`, `oam_antenna`, `full`) to categorize logs, but this classification is rigid and cannot accommodate new project types without code changes. The system already has a dynamic `ProjectRepo` registry (`project_repo` table) that manages project definitions. Replacing the static `log_type` with a foreign-key reference to `project_repo` unifies the two concepts, makes log categorization fully dynamic, and eliminates the need for code deploys when new project types are added.

## What Changes

- **BREAKING**: Remove `LogType` enum and `log_type` column from `LogRecord`; replace with a nullable `project_id` (FK → `project_repo.id`) column
- **BREAKING**: Upload API endpoints drop the `log_type` form field; add optional `project_id` or `project_code` parameter instead
- **BREAKING**: Log list API replaces `log_type` filter with `project_id` / `project_code` filter
- Update log type inference logic (`_infer_log_type_from_filename`, `_infer_log_type_from_components`) to resolve to a `project_repo` record instead of an enum value
- Update `LogFileInfo`, `LogUploadRequest`, `LogListRequest` Pydantic models to use `project_id`/`project_code`/`project_name` instead of `log_type`
- Update frontend `LogList.vue`, `LogDetail.vue`, stores, and types to use project-based filtering and display
- Update `LogService`, `log_processing` task, `ai_analysis` task, and `LogAnalysisAgent` prompts to work with `project_id` instead of `log_type`
- Add Alembic migration to: add `project_id` column, backfill existing rows by mapping `stack` → project "stack", `oam_antenna` → project "oam_antenna", `full` → project "full" (or a sensible default), then drop `log_type` column and `LogType` enum
- Ensure the `project-repos` dropdown (already exists at `/api/v1/project-repos`) can be used in the upload form and filter UI

## Capabilities

### New Capabilities
- `log-project-association`: Defines how logs are associated with projects instead of static log types, including the DB schema change, migration strategy, upload/query API contract, and inference logic

### Modified Capabilities
- `project-repo-registry`: The registry now serves as the source of truth for log categorization (not just code search). A "full" project entry must be seeded if it doesn't exist. The public list endpoint must remain available for the upload form dropdown.

## Impact

- **Database**: Migration adds `project_id` FK column, backfills data, drops `log_type` column and enum type
- **Backend API**: `/api/v1/logs` upload and list endpoints change request/response shape (breaking for API consumers)
- **Frontend**: `LogList.vue`, `LogDetail.vue`, `stores/logs.ts`, `types/index.ts`, `api/index.ts` all need updates
- **AI Analysis**: `ai_analysis.py`, `log_processing.py`, agent prompts, and workspace context all reference `log_type` and need migration to `project_id`
- **Tests**: `test_log_analysis_agent.py`, `test_ai_analysis_repo_injection.py`, `test_workspace.py` need updates
- **File upload validator**: `file_upload_validator.py` `determine_log_type_from_filename` needs to return a project reference
