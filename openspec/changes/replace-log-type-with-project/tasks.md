## 1. 数据库迁移

- [x] 1.1 创建 Alembic 迁移：在 `log_records` 表中添加可空 `project_id` 整型外键列，引用 `project_repo.id`，设置 `ON DELETE SET NULL`
- [x] 1.2 在 `project_repo` 表中预置 "full" 项目条目（`project_code='full'`、`project_name='Full Log'`、`repo_url=''`、`enabled=true`），如果尚不存在
- [x] 1.3 通过将 `log_type` 枚举值映射到对应的 `project_repo.project_code` 条目，回填所有现有 `log_records` 的 `project_id`
- [x] 1.4 删除 `log_type` 列和 `logtype` PostgreSQL 枚举类型
- [x] 1.5 编写降级迁移，重新添加 `log_type` 列并从 `project_id` 回填

## 2. 后端模型

- [x] 2.1 从 `app/models/log.py` 中移除 `LogType` 枚举类
- [x] 2.2 将 `LogRecord` 中的 `log_type` 映射列替换为可空 `project_id` 外键列
- [x] 2.3 更新 `LogFileInfo` Pydantic 模型：移除 `log_type`，添加 `project_id`、`project_code`、`project_name`
- [x] 2.4 更新 `LogUploadRequest` Pydantic 模型：移除 `log_type`，添加可选的 `project_code` 和 `project_id`
- [x] 2.5 更新 `LogListRequest` Pydantic 模型：移除 `log_type` 过滤器，添加可选的 `project_id` 过滤器

## 3. 后端服务

- [x] 3.1 将 `app/api/logs.py` 中的 `_infer_log_type_from_filename()` 替换为 `infer_project_from_filename()`，解析到 `ProjectRepo` 条目
- [x] 3.2 将 `_infer_log_type_from_components()` 替换为等效的基于项目的解析
- [x] 3.3 更新 `LogService.create_log()` 以接受和存储 `project_id` 而非 `log_type`
- [x] 3.4 更新 `LogService.get_logs()` 以按 `project_id` 而非 `log_type` 过滤
- [x] 3.5 更新 `LogService._record_to_info()` 以通过与 `project_repo` 关联填充 `project_code` 和 `project_name`
- [x] 3.6 更新 OAM 特有逻辑（状态/进度默认值），通过项目查找检查 `project_code == 'oam_antenna'` 而非 `log_type == LogType.OAM_ANTENNA`

## 4. 上传 API 端点

- [x] 4.1 更新 `POST /api/v1/logs/upload` 端点：将 `log_type` 表单字段替换为可选的 `project_code`/`project_id`，实现解析逻辑（显式 → 推断 → NULL）
- [x] 4.2 更新 `POST /api/v1/logs/upload-simple` 端点，进行相同变更
- [x] 4.3 更新 `POST /api/v1/logs/upload-t04-batch` 端点：将 log_type 推断替换为基于项目的解析，添加可选的 `project_code` 默认参数
- [x] 4.4 更新 `GET /api/v1/logs` 端点：将 `log_type` 查询参数替换为 `project_id` 过滤器

## 5. AI 分析流水线

- [x] 5.1 更新 `app/tasks/ai_analysis.py` 中的 `_resolve_project_code_for_analysis()`，使用 `project_id` 外键查找而非基于 `log_type` 的解析
- [x] 5.2 更新 `_bind_query_to_workspace()`，在工作空间元数据中传递 `project_id` 而非 `log_type`
- [x] 5.3 更新 `app/tasks/log_processing.py`，在日志记录和状态逻辑中引用 `project_id` 而非 `log_type`
- [x] 5.4 更新 `app/agents/log_analysis/workspace.py` 上下文构建，使用 `project_id`/`project_code`
- [x] 5.5 更新 `app/agents/log_analysis/prompts.py` 的 `get_prompts()`，接受 `project_code` 字符串而非 `log_type`
- [x] 5.6 更新 `app/agents/log_analysis/agent.py` 中从 `log_type` 到 `project_code`/`project_id` 的引用
- [x] 5.7 更新 `app/utils/file_upload_validator.py` 的 `determine_log_type_from_filename()`，返回 project_code 字符串或移除该函数，改用集中式推断

## 6. 管理 API

- [x] 6.1 更新 `DELETE /admin/project-repos/{id}`，检查关联的 `LogRecord` 行，如果存在则返回 HTTP 409（除非 `force=true`）
- [x] 6.2 允许 `project_repo` 中 `repo_url` 为空字符串，以支持仅用于分类的项目

## 7. 前端

- [x] 7.1 更新 `frontend/src/types/index.ts`：将 `log_type` 字段替换为 `project_id`、`project_code`、`project_name`
- [x] 7.2 更新 `frontend/src/stores/logs.ts`：将 `log_type` 过滤器替换为 `project_id` 过滤器
- [x] 7.3 更新 `frontend/src/api/index.ts`：将 `log_type` 查询参数替换为 `project_id`
- [x] 7.4 更新 `frontend/src/views/LogList.vue`：将硬编码的日志类型下拉菜单替换为从 `GET /api/v1/project-repos` 获取的动态项目选择器，更新表格列和标签显示
- [x] 7.5 更新 `frontend/src/views/LogDetail.vue`：将日志类型标签替换为项目名称显示
- [x] 7.6 更新 `frontend/src/views/AdminPrompts.vue`：移除 `log_type_keys` 引用（如适用）— 不适用：`log_type_keys` 是提示词配置键（后端 `PromptsSummary` 仍保留该字段），与日志记录的 log_type 无关，仅作默认初始化未渲染，无需改动
- [x] 7.7 处理 `project_id=null` 的情况，在列表和详情视图中显示为"未分类"

## 8. 测试

- [x] 8.1 更新 `tests/test_log_analysis_agent.py`，使用 `project_id` 替代 `log_type`
- [x] 8.2 更新 `tests/test_ai_analysis_repo_injection.py`，使用基于项目的解析
- [x] 8.3 更新 `tests/test_workspace.py`，在工作空间上下文中使用 `project_id`
- [x] 8.4 为 `infer_project_from_filename()` 添加测试，覆盖已知和未知模式
- [x] 8.5 为上传 API 添加测试，覆盖 `project_code`、`project_id` 和无项目场景
- [x] 8.6 为按 `project_id` 过滤日志列表添加测试，包括 NULL 过滤
- [x] 8.7 为管理员删除保护添加测试（当日志引用项目时返回 409）
