## 1. 数据模型与迁移

- [x] 1.1 在 `app/models/bug_fix.py` 新增 `BugFixTask` 模型（字段见 `bug-fix-task-registry` spec：状态枚举、来源日志/分析、proposed_fixes_json、celery_task_id、时间戳）
- [x] 1.2 在 `app/models/bug_fix.py` 新增 `BugFixMergeRequest` 模型（branch/base/mr_url/mr_iid/commit_sha/changed_files_json/diff_stat_json/status），建立到 `BugFixTask` 的一对多关系
- [x] 1.3 在 `app/models/project_repo.py` 新增 `ProjectRepoMember` 模型，含 `(project_repo_id, user_id)` 唯一约束
- [x] 1.4 编写 alembic 迁移创建 `bug_fix_task`、`bug_fix_merge_request`、`project_repo_member` 三张表与索引/外键/唯一约束
- [x] 1.5 在模型导出处（`app/models/__init__.py` 等）注册新模型，确保被 metadata 收集

## 2. 项目成员服务与管理端点

- [x] 2.1 新增 `app/services/project_repo_member_service.py`：list_members、list_user_projects、is_member、add_member（幂等）、remove_member
- [x] 2.2 在 `app/api/admin.py` 新增 `GET/POST /admin/project-repos/{id}/members` 与 `DELETE /admin/project-repos/{id}/members/{user_id}`，复用 `require_admin`，响应不含密码哈希
- [x] 2.3 在 `_repo_to_data`（`app/api/admin.py`）与对应 Pydantic 响应模型加入 `member_count`
- [x] 2.4 后端单测：成员增删查、幂等、非 admin 拒绝、member_count 正确

## 3. 日志分析结果的 code-fix 信号

- [x] 3.1 在 `app/agents/log_analysis/prompts.py` 的输出契约中加入 `requires_code_fix` 与 `proposed_fixes` 字段说明与判定准则
- [x] 3.2 在 `app/agents/log_analysis/agent.py` 结果解析中提取/校验这两个字段，缺省安全降级（`false` / `[]`）
- [x] 3.3 单测：含代码缺陷 → 置位；非代码问题 → 清空；legacy 响应 → 安全默认

## 4. Bug Fix 任务派发

- [x] 4.1 新增 `app/services/bug_fix_service.py`：create_task_from_analysis（写入 title/summary/proposed_fixes/来源）、状态流转、汇总查询
- [x] 4.2 在 `app/tasks/ai_analysis.py` 分析成功写入结果后，按 `requires_code_fix && proposed_fixes && repo_info` 条件创建任务并 `run_bug_fix_task.delay()`；整体 try/except 尽力而为，不影响分析结果持久化
- [x] 4.3 新增配置：自动派发开关、Bug Fix Agent 模型/超时、Git 平台类型与 API base 解析（`app/config.py`）
- [x] 4.4 单测：触发/不触发派发；派发异常不破坏分析结果

## 5. Bug Fix Coding Agent

- [x] 5.1 新增 `app/agents/bug_fix/workspace.py`：准备隔离工作区、解析带 token 的 clone_url（复用 `build_clone_url`）、git clone、写入 task.json、运行后清理
- [x] 5.2 新增 `app/agents/bug_fix/prompts.py`：系统提示词强约束「最小改动原则」「按问题拆分多 MR」「不碰默认分支」「分支命名/提交信息规范」，并定义最终 fenced JSON 输出契约（含 `merge_requests` 数组）
- [x] 5.3 新增 `app/agents/bug_fix/git_tools.py`：分支创建/提交/推送辅助；按平台（首期 GitLab）创建 MR 的 REST 封装，token 脱敏；GitHub PR 走同一抽象预留
- [x] 5.4 新增 `app/agents/bug_fix/agent.py`：基于 Claude Agent SDK 的写入型 Agent（allowed_tools 含 Edit/Write/Bash，bypassPermissions，cwd=工作区），复用 trace 设施与 token 脱敏，解析输出为结构化 `merge_requests`
- [x] 5.5 单测：最小改动/不碰默认分支约束的契约校验；多 proposed_fixes → 多分支多 MR；输出 JSON 解析；token 全程脱敏

## 6. Bug Fix Celery 任务

- [x] 6.1 新增 `app/tasks/bug_fix.py` 的 `run_bug_fix_task`：置 `running` → 运行 Agent → 为每个 MR 写 `bug_fix_merge_request` 行 → 依结果置 `succeeded`/`partial`/`failed`，失败写 typed `error`
- [x] 6.2 配置独立队列/并发限制，避免与分析任务争抢；复用克隆 base dir 与清理
- [x] 6.3 单测：全部成功/部分成功/无产出三种终态；MR 行落库且不含 token

## 7. Bug Fix 读取 API

- [x] 7.1 新增 `app/api/bug_fixes.py`：`GET /api/v1/bug-fixes`（分页，按成员资格过滤，admin 全量），summary 字段含 project_code/project_name/status/merge_request_count/source_log_id
- [x] 7.2 `GET /api/v1/bug-fixes/{id}`：返回任务详情 + proposed_fixes + 每个 MR 字段；非成员非 admin 返回 404
- [x] 7.3 在 `app/main.py` 注册新路由
- [x] 7.4 单测：成员可见范围、admin 全量、未认证 401、非成员详情 404、响应无 token

## 8. 前端

- [x] 8.1 在 `frontend/src/router/index.ts` 的 WorkbenchLayout 子路由下新增 `/bug-fixes`（BugFixList）与 `/bug-fixes/:id`（BugFixDetail）
- [x] 8.2 在 `frontend/src/layouts/WorkbenchLayout.vue` 用户菜单（`showUserMenu` 区块）新增「Bug 修复」入口，仅登录可见，点击 `router.push('/bug-fixes')`
- [x] 8.3 新增 `frontend/src/api` 的 bug-fix 客户端与 `frontend/src/stores` 的 bug-fix store；补充 `frontend/src/types` 类型
- [x] 8.4 新增 `frontend/src/views/BugFixList.vue`：列（任务标题/所属项目/状态徽标/MR 数量/来源日志/创建时间），行点击进详情
- [x] 8.5 新增 `frontend/src/views/BugFixDetail.vue`：任务总结 + proposed_fixes + 每个 MR 卡片（标题/状态/分支/改动文件+diff 统计/可点击 MR 链接）
- [x] 8.6 在 `frontend/src/views/AdminProjectRepos.vue` 增加成员管理（按用户名/邮箱检索注册用户并加入/移除，展示成员列表与 member_count）

## 9. 收尾与验证

- [ ] 9.1 端到端联调：模拟一次含代码缺陷的分析 → 自动派发 → Agent 产出 ≥1 个 MR → 列表/详情正确展示
- [ ] 9.2 验证多问题场景产出多个独立 MR；验证 token 在 trace/日志/响应/MR 链接中全部脱敏
- [ ] 9.3 运行后端与前端测试套件，更新相关文档/CLAUDE.md（如涉及）
