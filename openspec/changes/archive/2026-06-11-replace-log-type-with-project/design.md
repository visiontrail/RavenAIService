## 背景

当前日志系统使用硬编码的 `LogType` 枚举（包含三个值：`stack`、`oam_antenna`、`full`）来分类每条 `LogRecord`。这个枚举嵌入到数据库模式（SQLAlchemy `Enum` 列）、上传 API、列表/过滤 API、前端 UI 和 AI 分析流水线中。如今添加一个新项目类型需要代码修改 + 迁移 + 部署。

与此同时，`project_repo` 表（由 `project-repo-registry` 规格引入）已经提供了一个动态的、管理员管理的项目注册表，包含 `project_code`、`project_name` 和关联的 Git 仓库信息。该注册表最初是为 AI 分析期间的代码搜索设计的，但它是"系统中存在哪些项目"的自然权威来源。

关键利益相关方：上传 API（被自动化工具和手动拖放使用）、日志列表 UI 和 AI 分析流水线。

## 目标 / 非目标

**目标：**
- 用指向 `project_repo` 的动态外键替换静态 `log_type` 枚举，使新项目类型只需一个管理员数据库条目即可
- 保持向后兼容的推断：包含已知模式的文件名（如 `stack`、`oam`、`full`）仍能自动解析到正确的项目
- 提供平滑的迁移路径（根据 `log_type` 值回填 `project_id`）
- 保持上传 API 简单：调用者可以传递 `project_code`（字符串）或 `project_id`（整数）；如果省略，系统从文件名推断

**非目标：**
- 强制每条日志必须属于一个项目（外键可空以处理未知/无法识别的日志）
- 修改 `project_repo` 的管理 CRUD 或 Git 相关功能
- 修改 AI 分析代理的核心逻辑（仅更新其接收项目上下文的方式）
- 支持多项目日志（一条日志 → 一个项目）

## 决策

### 1. 可空外键而非必填外键

添加 `project_id: Optional[int]` 作为指向 `project_repo.id` 的可空外键。选择可空是因为：
- 在项目存在之前上传的历史日志不应中断
- 来自未知来源的自动上传仍应成功（推断可能失败）
- 考虑过的替代方案：必填外键加一个哨兵"未知"项目行——被否决，因为它在注册表中添加了一个虚假项目并使查询复杂化

### 2. 上传时同时接受 `project_code` 和 `project_id`

上传 API 将接受可选的 `project_code`（字符串）或 `project_id`（整数）。解析顺序：
1. 如果提供了 `project_id`，直接使用（验证其存在且已启用）
2. 如果提供了 `project_code`，通过 `project_repo_service.get_by_project_code()` 解析
3. 如果都未提供，使用现有的模式匹配逻辑从文件名推断，但解析到 `project_repo` 记录而非枚举
4. 如果推断失败，`project_id` 保持为 NULL

考虑过的替代方案：仅接受 `project_code`——被否决，因为 `project_id` 对已有该值的程序化调用者更高效。

### 3. 在迁移中预置 "full" 项目条目

现有迁移已从历史配置中预置了 `stack` 和 `oam_antenna` 项目。此变更添加一个 `full` 项目条目（代表完整/合并日志），以便回填现有的 `log_type=full` 记录。

### 4. 两阶段迁移（添加列 → 回填 → 删除列）

单个 Alembic 迁移包含三个步骤：
1. `ADD COLUMN project_id INTEGER REFERENCES project_repo(id)`（可空）
2. `UPDATE log_records SET project_id = (SELECT id FROM project_repo WHERE project_code = log_records.log_type)` 对每个已知映射执行
3. `DROP COLUMN log_type` 和 `DROP TYPE logtype` 枚举

考虑过的替代方案：在过渡期内保留 `log_type` 列与 `project_id` 并存——被否决，因为它会造成双数据源混乱，且系统尚未大规模投产。

### 5. 前端使用 project-repos 下拉菜单进行过滤

用从 `GET /api/v1/project-repos` 获取的动态下拉菜单替换硬编码的日志类型选择器。下拉菜单显示 `project_name` 并按 `project_id` 过滤。"全部"选项显示所有日志，不区分项目。

### 6. 文件名推断映射到 project_code 查找

当前 `_infer_log_type_from_filename()` 返回枚举。替换后的 `_infer_project_from_filename()` 将：
1. 应用相同的文件名模式匹配
2. 将结果映射到 `project_code` 字符串（如 `"stack"`、`"oam_antenna"`、`"full"`）
3. 通过 `project_repo_service.get_by_project_code()` 查找项目
4. 返回 `ProjectRepo` 对象或 `None`

这使推断逻辑保持集中和可测试。

## 风险 / 权衡

- **[迁移失败导致数据丢失]** → 迁移先做加法（添加列、回填）再做减法（删除列）。如果回填失败，旧列仍然存在。回滚：反向迁移重新添加列并从 `project_id` 重新填充。
- **[API 破坏性变更]** → 在上传请求中发送 `log_type` 的调用者将收到验证错误。→ 缓解措施：记录变更；该 API 是内部的，唯一的使用者是前端和 T04 上传脚本，两者都在我们的控制范围内。
- **[项目删除后的孤立 project_id]** → 如果管理员删除一个 `project_repo` 条目，引用它的日志会有悬空外键。→ 缓解措施：删除时使用 `SET NULL`（外键约束使用 `ON DELETE SET NULL`），日志变为"未分类"而非失败。
- **[性能]** → 在一个中等规模的表上添加外键列和索引影响可忽略。列表查询中与 `project_repo` 的 JOIN 增加的开销极小。

## 迁移计划

1. 创建 Alembic 迁移：添加 `project_id` 列，预置 "full" 项目，回填，删除 `log_type`
2. 更新后端模型、服务和 API 端点
3. 更新前端组件和 stores
4. 更新 AI 分析流水线引用
5. 更新并运行测试
6. 先部署后端（迁移运行），再部署前端

回滚：还原 Alembic 迁移（重新添加 `log_type` 列，从 `project_id` 映射重新填充，删除 `project_id`）

## 开放问题

- T04 批量上传端点（`/api/v1/logs/upload-t04-batch`）应该从 zip 结构自动检测项目，还是要求显式的 `project_code`？当前方案：保持自动检测，回退到显式参数。
