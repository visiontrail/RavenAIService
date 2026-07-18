## Context

`LogAnalysisAgent`（`app/agents/log_analysis/`）通过 Claude Agent SDK 在 Celery 任务 `run_ai_analysis_task`（`app/tasks/ai_analysis.py`）中运行。它已经：

- 从 `project_repo` 表或 `metadata.json` 解析出仓库信息，把带 token 的 `clone_url` 注入 `task.json` 的 `repo_info`；
- 在隔离工作区（`WorkspaceContext`，含 `temp_dir` / `logs_dir` / `repo_dir`）内基于真实源码做查证；
- 产出结构化结果（`status`/`severity`/`question_type`/`answer`/`summary`/`root_cause_hypotheses`/`recommended_actions`/...），持久化进 `LogRecord.ai_analysis_result`。

`project_repo`（`app/models/project_repo.py`）已存储 `repo_url`、`default_branch`、`git_token` 等，并有完整的 admin CRUD（`app/api/admin.py` 的 `/admin/project-repos`）与 Agent 侧 MCP 查询工具。`User`（`app/models/user.py`）有 `id`(uuid)/`username`/`email`/`role`。前端 `WorkbenchLayout.vue` 的左侧导航 `navItems`（日志列表/设备机柜/重构包仓库）是 router-link，点击在右侧主区域呈现对应视图；左下角用户卡片有一个展开菜单（`showUserMenu`）。

本设计在这些既有设施之上，补齐「分析结论 → 自动修复 → MR 汇总 → 授权可见」的闭环。

## Goals / Non-Goals

**Goals:**
- 分析任务成功结束、且判定需要代码修复时，自动把结论总结为一个 Bug 修复任务并异步派发，不阻塞分析结果返回。
- Bug Fix Coding Agent 按**最小改动原则**修复；一次任务可按问题维度产出**多个独立 MR**。
- 每个 MR 的改动摘要、diff 统计、分支、MR 链接/IID、提交 SHA、状态都汇总到项目级 Bug 修复列表。
- 项目仓库可登记成员（注册用户）；成员与管理员才能看到该项目的 Bug 修复列表/详情。
- 前端入口放在左下角用户菜单，点击后在右侧主区域呈现列表，行可进入详情。
- token 全程脱敏，写入型 Agent 在隔离工作区内运行，且只推分支、不自动合并。

**Non-Goals:**
- 不自动合并 MR，也不触碰默认分支——合并由人工评审决定。
- 不做跨项目的全局 Bug 看板或统计报表（本期只做项目级列表+详情）。
- 不替换或重写既有日志分析链路；只在其完成回调处挂接派发。
- 不实现 MR 评论回链、CI 触发、自动重试修复等高级编排（列为 Open Questions / 后续）。
- 不支持任意 Git 平台；首期覆盖 GitLab（Merge Request）并为 GitHub（Pull Request）预留抽象。

## Decisions

### 决策 1：用结构化信号驱动派发，而非自然语言判断

在日志分析结果 schema（v3）中新增字段：
- `requires_code_fix: bool` —— 分析是否判定需要改代码；
- `proposed_fixes: array` —— 每项含 `title`、`description`、`rationale`（关联根因）、可选 `suspected_files`/`suspected_symbols`。

`run_ai_analysis_task` 在成功写入分析结果后，读取该信号：当 `status == "completed"`、`requires_code_fix == true`、`proposed_fixes` 非空、且已解析出 `repo_info` 时，创建 `bug_fix_task`（状态 `pending`）并 `delay()` 一个新的 Celery 任务 `run_bug_fix_task`。

**为什么**：派发条件可测试、可回放，且避免在 Celery 任务里再跑一次 LLM 做意图判断。**替代方案**：在派发前用一次轻量 LLM 调用做 triage —— 成本与时延更高，且把不确定性塞进关键路径，否决。

派发是**尽力而为**的副作用：包在 try/except 中，失败只记日志，绝不影响分析结果本身的持久化（与现有 metrics 记录的处理方式一致）。

### 决策 2：Coding Agent 复用 Log Analysis 的工作区与仓库解析模式

新增 `app/agents/bug_fix/`，结构对齐 `log_analysis/`：`agent.py`（SDK loop + trace）、`prompts.py`、`workspace.py`、`git_tools.py`。`run_bug_fix_task`（`app/tasks/bug_fix.py`）：

1. 读取 `bug_fix_task` 与其关联 `project_repo`，用既有 `build_clone_url` 解析带 token 的 `clone_url`；
2. 准备隔离工作区并 `git clone`（浅克隆，复用 `code_repo_clone_base_dir` 约定）；
3. 写入 `task.json`，含任务总结、`proposed_fixes`、源日志/分析摘要、`default_branch`、git 身份信息；
4. 运行 Bug Fix Agent（`allowed_tools = [Read, Grep, Glob, Edit, Write, Bash]`，`permission_mode="bypassPermissions"`，`cwd=工作区`）；
5. 运行结束后清理工作区。

**为什么**：最大化复用既有的仓库解析、token 注入、trace、超时与脱敏设施，减少新代码面。**替代方案**：让 Log Analysis Agent 直接带写权限顺手改代码 —— 违反职责单一、且把高风险写操作塞进只读分析路径，否决。

### 决策 3：最小改动原则与「多 MR」由 prompt + 工作流强约束

Agent 系统提示词强约束：
- **最小改动**：只改定位到的根因相关代码，不顺手重构/格式化无关文件，不引入无关依赖；改动应尽量小且聚焦。
- **按问题拆 MR**：`proposed_fixes` 中**每个相互独立**的问题各自走一条 `git checkout -b <prefix>/<task>-<slug>` 分支、独立提交、独立推送、独立创建 MR；只有当多处改动属于同一根因、必须一起合并才有意义时才并入一个 MR。
- **分支命名**：统一前缀（如 `bugfix/ai-<task_id>-<index>`），从 `default_branch` 拉出，绝不直接提交到默认分支。
- **提交信息**：包含来源日志 ID 与修复项标题，便于追溯。
- 每完成一个 MR，Agent 通过 `git_tools` 暴露的能力创建 MR 并把结构化结果（分支、MR URL/IID、改动文件、diff 统计、提交 SHA）记录到最终输出 JSON 的 `merge_requests` 数组。

任务终态：全部成功 → `succeeded`；部分成功 → `partial`；无任何 MR 产出/全部失败 → `failed`。

**为什么**：把「最小改动」和「拆分粒度」放在 prompt+输出契约里，配合 schema 校验落库，比事后人工把关更可控。

### 决策 4：MR 创建走 Git 平台 REST API，平台类型可配置

`git_tools` 提供推送后创建 MR 的能力：根据平台类型（首期 GitLab）调用其 REST API（GitLab: `POST /projects/:id/merge_requests`，source=新分支，target=`default_branch`），认证复用 `project_repo.git_token` 或全局 `code_repo_git_token`。平台类型、API base 通过配置解析（可由 `repo_url` host 推断，必要时在 `project_repo` 上加 `git_provider` 覆盖，列入 Open Questions）。

Agent 既可经由暴露给它的工具创建 MR，也可在不支持该工具的 provider 下退化为 `glab`/`gh` CLI 或纯 `curl`（与 Log Analysis 对 MCP 不可用时的退化策略一致）。无论哪条路径，**API token 与 clone token 在 trace/日志/响应中一律脱敏**。

**替代方案**：只推分支、不建 MR，让人去平台手动开 —— 不满足「汇总 MR 链接」的需求，否决。

### 决策 5：数据模型——任务与 MR 一对多，成员关系独立表

- `bug_fix_task`：`id`(uuid)、`project_repo_id`(FK)、`source_log_id`(nullable)、`source_analysis_task_id`(nullable)、`title`、`summary`(Text)、`proposed_fixes_json`(Text)、`status`(pending/running/succeeded/partial/failed/cancelled)、`error`(nullable)、`agent_run_id`/`celery_task_id`、`started_at`/`finished_at`、时间戳。
- `bug_fix_merge_request`：`id`(uuid)、`task_id`(FK)、`title`、`description`(Text)、`branch_name`、`base_branch`、`mr_url`(nullable)、`mr_iid`(nullable)、`commit_sha`(nullable)、`changed_files_json`(Text，文件名+增删行)、`diff_stat`(JSON/字段)、`status`(open/created/push_failed/...)、时间戳。
- `project_repo_member`：`id`、`project_repo_id`(FK)、`user_id`(FK→users.id)、`created_at`，唯一约束 `(project_repo_id, user_id)`。

均由一支 alembic 迁移创建。MR 中**不存** token；`mr_url` 为平台可点击地址（不含凭据）。

**为什么**一对多独立表：天然支持「一次任务多个 MR」的汇总查询；成员关系独立表便于多对多与后续扩展（如角色）。

### 决策 6：可见性鉴权——成员 + 管理员

新增 `/api/v1/bug-fixes`（list）与 `/api/v1/bug-fixes/{id}`（detail），要求已登录。可见集合 = 当前用户作为成员的 `project_repo` 之下的任务；`role == "admin"` 的用户可见全部。非成员访问某任务详情返回 404（不泄露存在性）。管理端 `/admin/project-repos/{id}/members` 提供成员增删查，复用既有 `require_admin`。

### 决策 7：前端——入口在用户菜单，视图复用导航式右侧主区域

- 路由：在 `WorkbenchLayout` 子路由下新增 `/bug-fixes`(`BugFixList.vue`) 与 `/bug-fixes/:id`(`BugFixDetail.vue`)。
- 入口：在左下角用户菜单（`showUserMenu` 区块）新增「Bug 修复」按钮，`router.push('/bug-fixes')`；行为与 `navItems` 的「日志列表/设备机柜」一致（在右侧主区域呈现）。
- 列表列（最佳实践）：任务标题 / 所属项目 / 状态（带色徽标）/ MR 数量 / 来源日志 / 创建时间。行点击进入详情。
- 详情：任务总结 + `proposed_fixes`；每个 MR 卡片展示标题、状态、分支、改动文件清单与 diff 统计、可点击的 MR 链接。
- 后台 `AdminProjectRepos.vue` 增加成员管理（按用户名/邮箱检索注册用户并加入/移除）。

## Risks / Trade-offs

- **写入型 Agent 改坏代码** → 仅推非默认分支、不自动合并，强制人工评审 MR；隔离工作区运行；最小改动原则写入 prompt 并在输出契约中要求列明改动文件供核对。
- **Token 泄露**（clone/MR API） → 全程沿用 `https://***@` 脱敏；MR 表与 API 响应不含 token；`git_tools` 输出在进 trace 前脱敏（与 `project-repo-registry` 既有要求一致）。
- **Git 平台差异（GitLab/GitHub）** → 首期只保证 GitLab 全链路，GitHub 走同一抽象接口预留；平台不可识别时任务以明确 `error_kind` 失败并在详情中可见，不静默吞掉。
- **派发误触发 / 噪声 MR** → 由结构化 `requires_code_fix` + 非空 `proposed_fixes` 双条件把关；可加全局/项目级开关（配置）一键关闭自动派发。
- **Agent 创建 MR 部分失败** → 任务支持 `partial` 终态，已成功的 MR 照常入库展示，失败项在 `error`/MR 状态中标注。
- **并发与配额** → Coding Agent 走独立 Celery 队列/并发限制，避免与分析任务争抢；克隆复用既有 base dir 与清理逻辑。

## Migration Plan

1. 上线 alembic 迁移创建三张新表（向后兼容，纯新增）。
2. 部署后端（新 Agent / 任务 / API / schema 扩展）；自动派发默认可由配置开关控制，建议首发置于「关闭」或「灰度某项目」状态观察。
3. 部署前端（新路由/视图/入口与后台成员管理）。
4. 回滚：关闭自动派发开关即可停止新任务产生；新表与新路由对既有功能无副作用，可独立保留或随版本回退删除。

## Open Questions

- `project_repo` 是否需要新增 `git_provider`/`git_api_base` 列来显式声明平台，还是仅靠 `repo_url` host 推断？（倾向：先推断 + 全局默认，必要时再加列。）
- 自动派发开关的粒度：仅全局，还是 `project_repo` 级别也提供开关？
- 是否需要在 Bug 修复详情里内联展示 diff 内容（而非仅文件清单+统计）？涉及 diff 体积与存储取舍。
- 同一日志重复分析时的去重策略：是否对「相同来源 + 相似 proposed_fixes」做幂等，避免重复建任务/重复 MR？
