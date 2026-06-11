## 新增需求

### 需求：LogRecord 使用 project_id 外键替代 log_type 枚举

`LogRecord` 数据库模型应将 `log_type` 枚举列替换为可空的 `project_id` 整型列，该列是指向 `project_repo.id` 的外键，设置 `ON DELETE SET NULL`。`LogType` 枚举类应从代码库中移除。

#### 场景：新 LogRecord 有 project_id 列

- **当** 创建一条 `project_id=3` 的新 `LogRecord` 时
- **那么** 记录持久化为 `project_id=3`，引用 `project_repo` 行
- **并且** `log_type` 列不存在

#### 场景：project_id 为 NULL 的 LogRecord

- **当** 创建一条未指定 `project_id` 的新 `LogRecord` 时
- **那么** 记录持久化为 `project_id=NULL`
- **并且** 该记录可查询且功能完整

#### 场景：被引用的项目被删除

- **当** 一个被现有 `LogRecord` 行引用的 `project_repo` 条目被删除时
- **那么** 那些 `LogRecord` 行的 `project_id` 被设为 `NULL`（ON DELETE SET NULL）

### 需求：Alembic 迁移从 log_type 回填 project_id 并删除 log_type

系统应提供一个 Alembic 迁移，执行以下操作：（1）在 `log_records` 中添加可空 `project_id` 整型外键列，（2）确保 `project_repo` 中存在 `stack`、`oam_antenna` 和 `full` 的条目，（3）通过将每个 `log_type` 值映射到对应的 `project_repo.id` 来回填 `project_id`，（4）删除 `log_type` 列，（5）删除 `logtype` PostgreSQL 枚举类型。

#### 场景：在现有数据上迁移

- **当** 迁移在包含 `log_type='stack'` 行的 `log_records` 数据库上运行时
- **那么** 那些行的 `project_id` 被设为 `project_code='stack'` 对应的 `project_repo.id`
- **并且** `log_type` 列不再存在
- **并且** `logtype` 枚举类型不再存在

#### 场景：迁移在缺失时预置 "full" 项目

- **当** 迁移运行且不存在 `project_code='full'` 的 `project_repo` 条目时
- **那么** 创建一个新条目，`project_code='full'`、`project_name='Full Log'`、`repo_url=''`、`enabled=true`

#### 场景：降级迁移恢复 log_type

- **当** 降级迁移运行时
- **那么** `log_type` 枚举列重新添加到 `log_records`
- **并且** 值从 `project_id` → `project_code` 映射回填

### 需求：上传 API 接受 project_code 或 project_id 替代 log_type

上传端点（`POST /api/v1/logs/upload`、`POST /api/v1/logs/upload-simple`）应接受可选的 `project_code`（字符串）或 `project_id`（整数）表单字段替代 `log_type`。`log_type` 参数应被移除。解析顺序：（1）如果提供了 `project_id`，验证其对应已启用的条目；（2）如果提供了 `project_code`，通过不区分大小写的查找解析；（3）从文件名模式推断；（4）如果无法解析则为 NULL。

#### 场景：使用 project_code 上传

- **当** 客户端上传文件并附带 `project_code="stack"` 时
- **那么** 创建的 `LogRecord` 的 `project_id` 匹配 `project_code='stack'` 的 `project_repo` 条目

#### 场景：使用 project_id 上传

- **当** 客户端上传文件并附带 `project_id=5` 时
- **并且** `project_repo` id=5 存在且已启用
- **那么** 创建的 `LogRecord` 的 `project_id=5`

#### 场景：使用无效 project_id 上传

- **当** 客户端上传文件并附带 `project_id=999` 且不存在该条目时
- **那么** API 返回 HTTP 400，错误消息提示未找到该项目

#### 场景：未传项目参数时从文件名推断

- **当** 客户端上传名为 `stack_log_20240101.tar.gz` 的文件，未提供 `project_code` 或 `project_id` 时
- **那么** 系统从文件名推断 `project_code='stack'`
- **并且** 创建的 `LogRecord` 的 `project_id` 匹配 `stack` 项目条目

#### 场景：未传项目参数且文件名无法识别

- **当** 客户端上传名为 `unknown_data.zip` 的文件，未提供 `project_code` 或 `project_id` 时
- **那么** 创建的 `LogRecord` 的 `project_id=NULL`

### 需求：T04 批量上传从文件名或显式参数解析项目

`POST /api/v1/logs/upload-t04-batch` 端点应使用与单文件上传端点相同的逻辑解析项目关联。批次中的单个文件可以根据其文件名解析到不同的项目。可选的 `project_code` 表单字段应作为无法推断项目的文件的默认值。

#### 场景：包含混合文件类型的 T04 批次

- **当** T04 批次 zip 包含同时匹配 `stack` 和 `oam_antenna` 模式的文件时
- **那么** 每条生成的 `LogRecord` 的 `project_id` 匹配其单独推断的项目

#### 场景：带显式默认 project_code 的 T04 批次

- **当** T04 批量上传包含 `project_code="stack"` 且包含无法识别名称的文件时
- **那么** 无法识别的文件使用 `stack` 项目作为默认值
- **并且** 可识别的文件仍使用其推断的项目

### 需求：日志列表 API 按 project_id 而非 log_type 过滤

`GET /api/v1/logs` 端点应将 `log_type` 查询参数替换为 `project_id`（整数，可选）。当提供 `project_id` 时，仅返回具有该 `project_id` 的日志。`project_id=0` 或 `project_id=none` 值应返回 `project_id IS NULL` 的日志。

#### 场景：按 project_id 过滤

- **当** 客户端请求 `GET /api/v1/logs?project_id=3` 时
- **那么** 仅返回 `project_id=3` 的 `LogRecord` 行

#### 场景：过滤未分类日志

- **当** 客户端请求 `GET /api/v1/logs?project_id=0` 时
- **那么** 仅返回 `project_id IS NULL` 的 `LogRecord` 行

#### 场景：无项目过滤时返回所有日志

- **当** 客户端请求 `GET /api/v1/logs` 且不带 `project_id` 参数时
- **那么** 返回所有未删除的 `LogRecord` 行，不区分 `project_id`

### 需求：日志响应包含 project_code 和 project_name

`LogFileInfo` Pydantic 响应模型应包含 `project_id`（可选整数）、`project_code`（可选字符串）和 `project_name`（可选字符串）字段，替代 `log_type`。当日志有非空的 `project_id` 时，通过与 `project_repo` 关联来填充这些字段。

#### 场景：有关联项目的日志

- **当** API 返回一条 `project_id=3` 的 `LogFileInfo`，引用项目 `{project_code: "stack", project_name: "Stack"}` 时
- **那么** 响应包含 `project_id: 3`、`project_code: "stack"`、`project_name: "Stack"`
- **并且** 响应不包含 `log_type` 字段

#### 场景：没有项目的日志

- **当** API 返回一条 `project_id=NULL` 的 `LogFileInfo` 时
- **那么** 响应包含 `project_id: null`、`project_code: null`、`project_name: null`

### 需求：文件名推断解析到 project_repo 条目

系统应提供一个函数 `infer_project_from_filename(filename: str, db: Session) -> Optional[ProjectRepo]`，该函数应用文件名模式匹配（与之前的 `_infer_log_type_from_filename` 规则相同）并将结果解析到已启用的 `project_repo` 条目。如果没有匹配或匹配的 project_code 没有已启用的条目，则应返回 `None`。

#### 场景：包含 "stack" 的文件名

- **当** 调用 `infer_project_from_filename("stack_20240101.tar.gz", db)` 时
- **并且** 存在一个 `project_code='stack'` 的已启用 `project_repo` 条目
- **那么** 返回该 `ProjectRepo` 对象

#### 场景：不匹配任何模式的文件名

- **当** 调用 `infer_project_from_filename("random_file.zip", db)` 时
- **那么** 返回 `None`

### 需求：AI 分析流水线使用 project_id 替代 log_type

AI 分析任务（`ai_analysis.py`）、日志处理任务（`log_processing.py`）、日志分析代理和工作空间上下文应使用 `project_id` 并解析到 `project_repo` 数据，而非引用 `LogType` 枚举值。`_resolve_project_code_for_analysis()` 函数应通过 `LogRecord` 上的 `project_id` 查找项目，而非从 `log_type` 推导。

#### 场景：AI 分析从日志记录解析项目

- **当** AI 分析任务为 `project_id=3` 的 `LogRecord` 启动时
- **那么** 分析上下文包含来自 `project_repo` 的项目 `project_code` 和 `project_name`
- **并且** 不引用 `log_type` 值

#### 场景：project_id 为 NULL 时的 AI 分析

- **当** AI 分析任务为 `project_id=NULL` 的 `LogRecord` 启动时
- **那么** 分析在没有项目特定上下文的情况下继续
- **并且** 代码搜索功能不可用（无仓库 URL）

### 需求：前端按项目而非日志类型显示和过滤

前端日志列表应将硬编码的日志类型下拉菜单替换为从 `GET /api/v1/project-repos` 获取的动态项目选择器。日志详情视图应显示 `project_name` 而非日志类型标签。前端类型定义和 store 应使用 `project_id`/`project_code`/`project_name` 替代 `log_type`。

#### 场景：日志列表显示项目过滤下拉菜单

- **当** 日志列表页面加载时
- **那么** 项目过滤下拉菜单从 API 获取所有已启用的项目
- **并且** 选择一个项目会过滤列表显示具有该 `project_id` 的日志

#### 场景：日志详情显示项目名称

- **当** 用户查看关联项目 "Stack" 的日志详情页面时
- **那么** 详情视图在之前显示日志类型的位置显示 "Stack" 作为项目名称

#### 场景：日志列表处理没有项目的日志

- **当** 日志的 `project_id=null` 时
- **那么** 日志列表在项目列中显示"未分类"或等效文本
