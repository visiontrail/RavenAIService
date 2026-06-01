## 修改的需求

### 需求：项目仓库注册表在数据库中持久化 project_code → 仓库 URL 映射

系统应提供一个 `project_repo` 数据库表（通过 Alembic 迁移管理），至少包含以下列：`id`（主键）、`project_code`（唯一，非空）、`project_name`（非空）、`repo_url`（非空）、`default_branch`（非空，默认 `"main"`）、`git_token`（可空；每仓库覆盖全局 `code_repo_git_token`）、`description`（可空）、`enabled`（布尔，默认 true）、`created_at`、`updated_at`。

`repo_url` 字段应允许空字符串值，以支持仅用于日志分类而没有关联 Git 仓库的项目条目。

#### 场景：迁移创建表

- **当** Alembic 迁移在全新数据库上运行时
- **那么** `project_repo` 表存在并包含所有列出的列
- **并且** 唯一索引覆盖 `project_code`

#### 场景：迁移从历史设置预置数据

- **当** Alembic 迁移运行且 `settings.code_repo_oam_url` 非空时
- **那么** 插入一行 `project_code == "oam_antenna"`、`project_name == "OAM Antenna"`、`repo_url == settings.code_repo_oam_url`
- **并且** `code_repo_stack_url` 同理，`project_code == "stack"`

#### 场景：迁移预置 "full" 项目条目

- **当** 日志类型转项目的迁移运行时
- **那么** 存在一个 `project_repo` 条目，`project_code='full'`、`project_name='Full Log'`、`repo_url=''`
- **并且** 该条目 `enabled=true`

#### 场景：没有仓库 URL 的项目条目

- **当** 项目条目的 `repo_url=''` 时
- **那么** 该条目有效且可用于日志分类
- **并且** 当 AI 代理尝试基于仓库的操作时，代码搜索工具报告"未配置仓库"

## 新增需求

### 需求：管理员在没有确认的情况下不能删除有关联日志的 project_repo 条目

管理员 `DELETE /admin/project-repos/{id}` 端点应检查是否有任何 `LogRecord` 行引用该项目。如果存在引用，端点应返回 HTTP 409 并附带受影响日志的数量，且要求 `force=true` 查询参数才能继续。强制删除时，删除操作继续执行，受影响的日志 `project_id` 被设为 NULL（通过外键 ON DELETE SET NULL）。

#### 场景：删除有关联日志的项目但未强制

- **当** 管理员删除一个被 15 条日志记录引用的 project_repo 条目时
- **并且** `force` 参数未设置或为 `false`
- **那么** API 返回 HTTP 409，响应体为 `{"affected_logs": 15, "message": "该项目有关联的日志记录。使用 force=true 进行删除。"}`

#### 场景：强制删除有关联日志的项目

- **当** 管理员使用 `force=true` 删除一个被 15 条日志记录引用的 project_repo 条目时
- **那么** project_repo 条目被删除
- **并且** 所有 15 条日志记录的 `project_id` 被设为 NULL
