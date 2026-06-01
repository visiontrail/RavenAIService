## 为什么

`LogRecord` 模型目前使用硬编码的 `LogType` 枚举（`stack`、`oam_antenna`、`full`）来分类日志，但这种分类方式是固定的，无法在不修改代码的情况下适应新的项目类型。系统中已经有一个动态的 `ProjectRepo` 注册表（`project_repo` 表）来管理项目定义。用指向 `project_repo` 的外键引用替换静态的 `log_type`，可以统一这两个概念，使日志分类完全动态化，并在添加新项目类型时无需部署代码。

## 变更内容

- **破坏性变更**：从 `LogRecord` 中移除 `LogType` 枚举和 `log_type` 列；替换为可空的 `project_id`（外键 → `project_repo.id`）列
- **破坏性变更**：上传 API 端点移除 `log_type` 表单字段；改为添加可选的 `project_id` 或 `project_code` 参数
- **破坏性变更**：日志列表 API 将 `log_type` 过滤器替换为 `project_id` / `project_code` 过滤器
- 更新日志类型推断逻辑（`_infer_log_type_from_filename`、`_infer_log_type_from_components`），改为解析到 `project_repo` 记录而非枚举值
- 更新 `LogFileInfo`、`LogUploadRequest`、`LogListRequest` Pydantic 模型，使用 `project_id`/`project_code`/`project_name` 替代 `log_type`
- 更新前端 `LogList.vue`、`LogDetail.vue`、stores 和类型定义，使用基于项目的过滤和显示
- 更新 `LogService`、`log_processing` 任务、`ai_analysis` 任务和 `LogAnalysisAgent` 提示词，使用 `project_id` 替代 `log_type`
- 添加 Alembic 迁移：添加 `project_id` 列，通过映射 `stack` → 项目 "stack"、`oam_antenna` → 项目 "oam_antenna"、`full` → 项目 "full"（或合理的默认值）回填现有行，然后删除 `log_type` 列和 `LogType` 枚举
- 确保 `project-repos` 下拉菜单（已存在于 `/api/v1/project-repos`）可在上传表单和过滤 UI 中使用

## 能力

### 新能力
- `log-project-association`：定义日志如何与项目关联而非静态日志类型，包括数据库模式变更、迁移策略、上传/查询 API 契约和推断逻辑

### 修改的能力
- `project-repo-registry`：注册表现在作为日志分类的权威来源（不仅仅是代码搜索）。如果不存在 "full" 项目条目，则必须预置。公开列表端点必须保持可用以供上传表单下拉菜单使用。

## 影响

- **数据库**：迁移添加 `project_id` 外键列，回填数据，删除 `log_type` 列和枚举类型
- **后端 API**：`/api/v1/logs` 上传和列表端点的请求/响应结构变更（对 API 使用者是破坏性变更）
- **前端**：`LogList.vue`、`LogDetail.vue`、`stores/logs.ts`、`types/index.ts`、`api/index.ts` 都需要更新
- **AI 分析**：`ai_analysis.py`、`log_processing.py`、代理提示词和工作空间上下文都引用了 `log_type`，需要迁移到 `project_id`
- **测试**：`test_log_analysis_agent.py`、`test_ai_analysis_repo_injection.py`、`test_workspace.py` 需要更新
- **文件上传验证器**：`file_upload_validator.py` 的 `determine_log_type_from_filename` 需要返回项目引用
