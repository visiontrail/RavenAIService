## Why

当前日志分析 Agent（`LogAnalysisAgent`）只能产出诊断结论与「建议动作」（`recommended_actions`），所有修复仍需人工读懂结论、手动改代码、手动提交合并请求（MR）。当结论明确指向代码缺陷时，这一段「从结论到修复」的链路完全靠人力承接，既慢又容易遗漏。

由于分析 Agent 已经会把对应项目仓库克隆到工作区并基于真实源码做查证，我们已经具备「让一个后台编码 Agent 接力把修复落地为 MR」的全部前提。本提案补齐这条闭环：分析完成 → 自动总结为修复任务 → 后台 Bug Fix Coding Agent 按最小改动原则修复并提交（可多个）MR → 在项目级的 Bug 修复列表中汇总呈现，授权用户可见。

## What Changes

- **新增后台 Bug Fix Coding Agent**：基于 Claude Agent SDK 的写入型 Agent（具备 `Edit`/`Write`/`Bash` 等工具），在克隆出的项目仓库工作区内按「最小改动原则」修复问题，创建分支、提交并推送、调用 Git 托管平台 API 创建 MR。**一次任务允许产出多个 MR**——当一次分析定位到多处互相独立的问题时，按问题维度拆分为多个分支/MR，互不耦合。
- **日志分析结果触发修复**：扩展日志分析结果 schema，新增结构化的「是否需要改代码 / 拟修复项」信号；当分析以成功状态结束且判定需要代码修复时，后台自动把分析结论总结为一个 Bug 修复任务并派发给 Coding Agent（异步 Celery 任务，不阻塞分析结果返回）。
- **新增 Bug 修复任务与 MR 的持久化与状态机**：记录任务来源（日志、项目、分析结论）、整体状态、以及每个 MR 的分支名、标题、改动文件与 diff 摘要、MR 链接/IID、提交 SHA、状态等汇总信息。
- **项目仓库管理新增「项目成员」**：后台「项目仓库管理」中，每个项目可登记若干注册用户为成员；只有成员（及管理员）能在前台看到该项目的 Bug 修复列表与详情。
- **前端新增 Bug 修复列表入口与视图**：在左下角用户信息展开菜单中新增「Bug 修复」入口；点击后与「日志列表」「设备机柜」一致，在聊天历史右侧主区域呈现列表；列表行可点击进入详情，展示任务总结、各 MR 的改动内容与跳转链接。

## Capabilities

### New Capabilities
- `bug-fix-coding-agent`: 后台编码修复 Agent —— 接收一个修复任务，在项目仓库工作区按最小改动原则修复，按问题拆分创建一个或多个分支并推送，调用 Git 托管平台 API 创建对应 MR，回填结果。
- `bug-fix-task-registry`: Bug 修复任务与其 MR 子记录的数据模型、状态机、汇总查询，以及把分析结论总结为任务的派发逻辑。
- `bug-fix-list-api`: 面向已登录用户、按项目成员资格鉴权的 Bug 修复列表/详情读取 API。
- `bug-fix-list-ui`: 前端用户菜单入口、右侧主区域的 Bug 修复列表视图与详情视图。
- `project-repo-membership`: 项目仓库 ↔ 注册用户的成员关系模型与后台管理端点，作为 Bug 修复列表可见性的鉴权依据。

### Modified Capabilities
- `log-analysis-agent`: 分析结果 schema 新增「需要代码修复」触发信号与拟修复项；分析任务成功结束后按该信号派发 Bug 修复任务。
- `project-repo-registry`: 项目仓库新增成员管理 admin 端点（增删查项目成员），并在响应中暴露成员摘要。

## Impact

- **后端代码**：
  - 新增 `app/agents/bug_fix/`（agent、prompts、workspace、git/MR 工具）。
  - 新增 `app/tasks/bug_fix.py`（Coding Agent 的 Celery 任务）；修改 `app/tasks/ai_analysis.py` 在分析完成后派发修复任务。
  - 新增模型 `app/models/bug_fix.py`（`bug_fix_task`、`bug_fix_merge_request`）与 `project_repo_member`（置于 `app/models/project_repo.py`）。
  - 新增服务 `app/services/bug_fix_service.py`、`project_repo_member_service.py`。
  - 新增 API `app/api/bug_fixes.py`；扩展 `app/api/admin.py`（项目成员管理）。
  - 扩展 `LogAnalysisAgent` 结果 schema（`app/agents/log_analysis/prompts.py`、`agent.py`）。
- **数据库**：新增 alembic 迁移，创建 `bug_fix_task`、`bug_fix_merge_request`、`project_repo_member` 三张表。
- **配置**：新增 Git 托管平台 API 配置（平台类型 GitLab/GitHub、API base、token 复用 `project_repo.git_token` / 全局 `code_repo_git_token`），以及 Bug Fix Agent 的开关与模型/超时设置。
- **前端**：新增路由 `/bug-fixes`、`/bug-fixes/:id` 与 `BugFixList.vue`、`BugFixDetail.vue`；修改 `WorkbenchLayout.vue`（用户菜单入口）与 `AdminProjectRepos.vue`（成员管理）；新增 `frontend/src/api` 与 `stores` 中的 Bug 修复模块。
- **安全**：MR/clone URL 中的 token 必须沿用现有脱敏规则（`https://***@`），不得写入 trace、日志或 API 响应。写入型 Agent 仅允许在隔离工作区操作，并限定只能推送到非默认分支、由人工评审后再合并。
