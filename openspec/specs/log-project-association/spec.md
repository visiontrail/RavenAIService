## ADDED Requirements

### Requirement: LogRecord 使用 project_id 外键替代 log_type 枚举

`LogRecord` 数据库模型应将 `log_type` 枚举列替换为可空的 `project_id` 整型列，该列是指向 `project_repo.id` 的外键，设置 `ON DELETE SET NULL`。`LogType` 枚举类应从代码库中移除。

#### Scenario: 新 LogRecord 有 project_id 列

- **WHEN** 创建一条 `project_id=3` 的新 `LogRecord` 时
- **THEN** 记录持久化为 `project_id=3`，引用 `project_repo` 行
- **AND** `log_type` 列不存在

#### Scenario: project_id 为 NULL 的 LogRecord

- **WHEN** 创建一条未指定 `project_id` 的新 `LogRecord` 时
- **THEN** 记录持久化为 `project_id=NULL`
- **AND** 该记录可查询且功能完整

#### Scenario: 被引用的项目被删除

- **WHEN** 一个被现有 `LogRecord` 行引用的 `project_repo` 条目被删除时
- **THEN** 那些 `LogRecord` 行的 `project_id` 被设为 `NULL`（ON DELETE SET NULL）

### Requirement: Alembic 迁移从 log_type 回填 project_id 并删除 log_type

系统应提供一个 Alembic 迁移，执行以下操作：（1）在 `log_records` 中添加可空 `project_id` 整型外键列，（2）确保 `project_repo` 中存在 `stack`、`oam_antenna` 和 `full` 的条目，（3）通过将每个 `log_type` 值映射到对应的 `project_repo.id` 来回填 `project_id`，（4）删除 `log_type` 列，（5）删除 `logtype` PostgreSQL 枚举类型。

#### Scenario: 在现有数据上迁移

- **WHEN** 迁移在包含 `log_type='stack'` 行的 `log_records` 数据库上运行时
- **THEN** 那些行的 `project_id` 被设为 `project_code='stack'` 对应的 `project_repo.id`
- **AND** `log_type` 列不再存在
- **AND** `logtype` 枚举类型不再存在

#### Scenario: 迁移在缺失时预置 "full" 项目

- **WHEN** 迁移运行且不存在 `project_code='full'` 的 `project_repo` 条目时
- **THEN** 创建一个新条目，`project_code='full'`、`project_name='Full Log'`、`repo_url=''`、`enabled=true`

#### Scenario: 降级迁移恢复 log_type

- **WHEN** 降级迁移运行时
- **THEN** `log_type` 枚举列重新添加到 `log_records`
- **AND** 值从 `project_id` → `project_code` 映射回填

### Requirement: 上传 API 接受 project_code 或 project_id 替代 log_type

上传端点（`POST /api/v1/logs/upload`、`POST /api/v1/logs/upload-simple`）应接受可选的 `project_code`（字符串）或 `project_id`（整数）表单字段替代 `log_type`。`log_type` 参数应被移除。解析顺序：（1）如果提供了 `project_id`，验证其对应已启用的条目；（2）如果提供了 `project_code`，通过不区分大小写的查找解析；（3）从文件名模式推断；（4）如果无法解析则为 NULL。

#### Scenario: 使用 project_code 上传

- **WHEN** 客户端上传文件并附带 `project_code="stack"` 时
- **THEN** 创建的 `LogRecord` 的 `project_id` 匹配 `project_code='stack'` 的 `project_repo` 条目

#### Scenario: 使用 project_id 上传

- **WHEN** 客户端上传文件并附带 `project_id=5` 时
- **AND** `project_repo` id=5 存在且已启用
- **THEN** 创建的 `LogRecord` 的 `project_id=5`

#### Scenario: 使用无效 project_id 上传

- **WHEN** 客户端上传文件并附带 `project_id=999` 且不存在该条目时
- **THEN** API 返回 HTTP 400，错误消息提示未找到该项目

#### Scenario: 未传项目参数时从文件名推断

- **WHEN** 客户端上传名为 `stack_log_20240101.tar.gz` 的文件，未提供 `project_code` 或 `project_id` 时
- **THEN** 系统从文件名推断 `project_code='stack'`
- **AND** 创建的 `LogRecord` 的 `project_id` 匹配 `stack` 项目条目

#### Scenario: 未传项目参数且文件名无法识别

- **WHEN** 客户端上传名为 `unknown_data.zip` 的文件，未提供 `project_code` 或 `project_id` 时
- **THEN** 创建的 `LogRecord` 的 `project_id=NULL`

### Requirement: T04 批量上传从文件名或显式参数解析项目

`POST /api/v1/logs/upload-t04-batch` 端点应使用与单文件上传端点相同的逻辑解析项目关联。批次中的单个文件可以根据其文件名解析到不同的项目。可选的 `project_code` 表单字段应作为无法推断项目的文件的默认值。

#### Scenario: 包含混合文件类型的 T04 批次

- **WHEN** T04 批次 zip 包含同时匹配 `stack` 和 `oam_antenna` 模式的文件时
- **THEN** 每条生成的 `LogRecord` 的 `project_id` 匹配其单独推断的项目

#### Scenario: 带显式默认 project_code 的 T04 批次

- **WHEN** T04 批量上传包含 `project_code="stack"` 且包含无法识别名称的文件时
- **THEN** 无法识别的文件使用 `stack` 项目作为默认值
- **AND** 可识别的文件仍使用其推断的项目

### Requirement: 日志列表 API 按 project_id 而非 log_type 过滤

`GET /api/v1/logs` 端点应将 `log_type` 查询参数替换为 `project_id`（整数，可选）。当提供 `project_id` 时，仅返回具有该 `project_id` 的日志。`project_id=0` 或 `project_id=none` 值应返回 `project_id IS NULL` 的日志。

#### Scenario: 按 project_id 过滤

- **WHEN** 客户端请求 `GET /api/v1/logs?project_id=3` 时
- **THEN** 仅返回 `project_id=3` 的 `LogRecord` 行

#### Scenario: 过滤未分类日志

- **WHEN** 客户端请求 `GET /api/v1/logs?project_id=0` 时
- **THEN** 仅返回 `project_id IS NULL` 的 `LogRecord` 行

#### Scenario: 无项目过滤时返回所有日志

- **WHEN** 客户端请求 `GET /api/v1/logs` 且不带 `project_id` 参数时
- **THEN** 返回所有未删除的 `LogRecord` 行，不区分 `project_id`

### Requirement: 日志响应包含 project_code 和 project_name

`LogFileInfo` Pydantic 响应模型应包含 `project_id`（可选整数）、`project_code`（可选字符串）和 `project_name`（可选字符串）字段，替代 `log_type`。当日志有非空的 `project_id` 时，通过与 `project_repo` 关联来填充这些字段。

#### Scenario: 有关联项目的日志

- **WHEN** API 返回一条 `project_id=3` 的 `LogFileInfo`，引用项目 `{project_code: "stack", project_name: "Stack"}` 时
- **THEN** 响应包含 `project_id: 3`、`project_code: "stack"`、`project_name: "Stack"`
- **AND** 响应不包含 `log_type` 字段

#### Scenario: 没有项目的日志

- **WHEN** API 返回一条 `project_id=NULL` 的 `LogFileInfo` 时
- **THEN** 响应包含 `project_id: null`、`project_code: null`、`project_name: null`

### Requirement: 文件名推断解析到 project_repo 条目

系统应提供一个函数 `infer_project_from_filename(filename: str, db: Session) -> Optional[ProjectRepo]`，该函数应用文件名模式匹配（与之前的 `_infer_log_type_from_filename` 规则相同）并将结果解析到已启用的 `project_repo` 条目。如果没有匹配或匹配的 project_code 没有已启用的条目，则应返回 `None`。

#### Scenario: 包含 "stack" 的文件名

- **WHEN** 调用 `infer_project_from_filename("stack_20240101.tar.gz", db)` 时
- **AND** 存在一个 `project_code='stack'` 的已启用 `project_repo` 条目
- **THEN** 返回该 `ProjectRepo` 对象

#### Scenario: 不匹配任何模式的文件名

- **WHEN** 调用 `infer_project_from_filename("random_file.zip", db)` 时
- **THEN** 返回 `None`

### Requirement: AI 分析流水线使用 project_id 替代 log_type

AI 分析任务（`ai_analysis.py`）、日志处理任务（`log_processing.py`）、日志分析代理和工作空间上下文应使用 `project_id` 并解析到 `project_repo` 数据，而非引用 `LogType` 枚举值。`_resolve_project_code_for_analysis()` 函数应通过 `LogRecord` 上的 `project_id` 查找项目，而非从 `log_type` 推导。

#### Scenario: AI 分析从日志记录解析项目

- **WHEN** AI 分析任务为 `project_id=3` 的 `LogRecord` 启动时
- **THEN** 分析上下文包含来自 `project_repo` 的项目 `project_code` 和 `project_name`
- **AND** 不引用 `log_type` 值

#### Scenario: project_id 为 NULL 时的 AI 分析

- **WHEN** AI 分析任务为 `project_id=NULL` 的 `LogRecord` 启动时
- **THEN** 分析在没有项目特定上下文的情况下继续
- **AND** 代码搜索功能不可用（无仓库 URL）

### Requirement: 前端按项目而非日志类型显示和过滤

前端日志列表应将硬编码的日志类型下拉菜单替换为从 `GET /api/v1/project-repos` 获取的动态项目选择器。日志详情视图应显示 `project_name` 而非日志类型标签。前端类型定义和 store 应使用 `project_id`/`project_code`/`project_name` 替代 `log_type`。

#### Scenario: 日志列表显示项目过滤下拉菜单

- **WHEN** 日志列表页面加载时
- **THEN** 项目过滤下拉菜单从 API 获取所有已启用的项目
- **AND** 选择一个项目会过滤列表显示具有该 `project_id` 的日志

#### Scenario: 日志详情显示项目名称

- **WHEN** 用户查看关联项目 "Stack" 的日志详情页面时
- **THEN** 详情视图在之前显示日志类型的位置显示 "Stack" 作为项目名称

#### Scenario: 日志列表处理没有项目的日志

- **WHEN** 日志的 `project_id=null` 时
- **THEN** 日志列表在项目列中显示"未分类"或等效文本
