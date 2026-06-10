# 任务清单：重构包检索 Agent 项目化重建

## 1. 包-项目关联数据层（package-project-association）

- [x] 1.1 `raven_package_service.py`：移除 `PACKAGE_TYPES` 常量与 `determine_package_type()` 文件名启发式；新增 `projectCode` 字段语义与 `load_packages()` 中的幂等惰性规范化（`projectCode` ← 旧 `packageType` 值，保留原键；读路径不主动落盘）
- [x] 1.2 `raven_package_service.py`：`iter_brief()` 投影 `packageType` → `projectCode`；`filter_packages()` 支持 `projectCode` 筛选与 `__unassociated__` 特殊值；`query_packages` / `text_search` / `version_filter` / `list_components` / `find_by_component` / `stats_by` 全部改为项目维度（`stats_by` 移除 `type` 维度）
- [x] 1.3 `raven_package_service.py`：`build_package_info()` / `extract_package_metadata()` / `scan_uploads_directory()` 适配——上传走显式 `projectCode`，扫描入库 `projectCode=""`（未关联）
- [x] 1.4 新增项目校验 helper：`projectCode` 必须对应 `project_repo` 中存在且 `enabled=true` 的记录（供上传 API 复用，校验失败抛 400 语义错误）
- [x] 1.5 后端单元测试：惰性迁移幂等性、回滚兼容（旧键保留）、未关联筛选、各查询方法的项目过滤

## 2. 包管理对外 API 适配（BREAKING）

- [x] 2.1 `app/api/packages.py`：`GET /packages` 新增 `projectCode` 查询参数，旧 `type` 参数作为 deprecated 别名按 `projectCode` 解释；`GET /packages/stats/overview` 返回 `packagesByProject`（含 `unassociated` 桶）并移除 `packagesByType`
- [x] 2.2 `POST /upload`、`POST /upload/batch`：表单字段 `packageType` → `projectCode`（必填），接入 1.4 的项目校验，校验失败清理已落盘文件
- [x] 2.3 移除 `GET /download/type/{package_type}` 路由，新增 `GET /download/project/{project_code}`（单包直发文件、多包打 zip）
- [x] 2.4 `_record_package_activity()`：metadata `package_type` → `project_code`（空值记 `unassociated`）；`app/utils/metrics.py` 的 `raven_package_activity_total` 移除 `package_type` label，仅保留 `action` + `status`
- [x] 2.5 `app/i18n/messages`：新增上传项目校验失败、`project_repo_required` 等文案（zh/en）
- [x] 2.6 API 集成测试：项目筛选、旧 `type` 别名、上传必填校验与失败清理、scan 未关联入库、按项目下载、stats 新结构、Prometheus label 断言

## 3. Agent 重建：工作区与项目绑定

- [x] 3.1 新增 `app/agents/package_search/workspace.py`（同构 `project_expert/workspace.py`）：`prepare(project_repo, question, hints, session_id)` 创建 `repo/` + `task.json`（`repo_info` 含 project_code/repo_url/default_branch，`source="user_selected_project_repo"`，不落 token）、`cleanup()` 幂等清理、`MissingProjectRepoError`
- [x] 3.2 `app/agents/package_search/mcp_tools.py`：`get_mcp_server(project_code)` 按运行构建，7 个工具服务端强制 `projectCode` 过滤；移除 `list_packages.filters.type`、`filter_packages_by_version.package_type`、`list_components.package_type` 参数；`package_stats.group_by` 合法值改为 `version_major|tag|isPatch`；`get_package_by_id` 对非本项目 ID 返回 `not_found`
- [x] 3.3 重写 `app/agents/package_search/agent.py`：复用 `log_analysis` trace 层与 `_RunState` 状态机（对齐 `project_expert/agent.py`），ALLOWED_TOOLS = `Bash/Read/Grep/Glob` + `mcp__project_repo__lookup_project_repo` + 7 个包工具（`mcp_servers` 同时挂 `project_repo` 与 `package_search` 两个 server）；保留包检索自有的最终结果契约（fenced JSON → recommended/relevant ID 校验过滤，校验范围限定所选项目）；支持 `cancel_event` 与 `trace_emitter`；删除 `app/agents/package_search/trace.py` 及其引用
- [x] 3.4 Agent 单元测试（monkeypatch SDK loop）：项目限定工具过滤、跨项目 ID 拦截、取消路径、降级（无 fenced JSON）路径

## 4. 提示词后台化

- [x] 4.1 `app/prompts/prompts_config.yaml`：新增 `claude_agent_package_search.generic` 区块（`system_prompt.zh` + `user_prompt_template.zh`），内容从现 `prompts.py` 迁移并补充：项目绑定上下文、工作区路径说明、Git 提交记录优先三级契约（元数据 → git log/show → 必要时才读代码并说明理由）、partial clone 建议、fenced JSON 输出契约
- [x] 4.2 重写 `app/agents/package_search/prompts.py` 为 YAML 加载器（同构 `project_expert/prompts.py`：`_PROMPTS_CACHE` + `get_prompts(locale)` + `render_user_prompt`），删除硬编码 `SYSTEM_PROMPT` 与 `PACKAGE_TYPES` 元组
- [x] 4.3 `prompts_config_service.py`：`PROMPT_FUNCTION_META` 增加 `claude_agent_package_search`（"重构包检索"）、`PROMPT_AGENT_META` 增加 `(claude_agent_package_search, generic)`（"重构包配置管理员"）、`_invalidate_prompt_caches()` 清理 package_search 缓存
- [x] 4.4 测试：后台保存后缓存失效即时生效、AdminPrompts 条目列表包含新区块（service 层断言）

## 5. 聊天服务与端点

- [x] 5.1 新增 `app/services/package_search_chat_service.py`（镜像 `project_expert_chat_service`）：新会话必填 `project_repo_id` + `_resolve_project_repo` 校验（存在且启用）、会话级工作区复用与项目绑定不漂移、后台线程 + cancel_event、SSE 透传 trace、`final` 事件含 recommended/relevant ID、登录态会话持久化、`get_status` 轮询、owner 鉴权（非所有者 cancel/result 抛 PermissionError）、`session_has_workspace()`
- [x] 5.2 `app/api/ai_chat.py`：注册 `POST /package-search/stream`（新会话缺 `project_repo_id` 返回 400 `reason="project_repo_required"`）、`POST /package-search/cancel`、`GET /package-search/result`，结构对齐项目专家三端点
- [x] 5.3 `app/api/packages.py` 的 `POST /packages/agent-search`：请求体新增必填 `project_repo_id`（缺失/无效项目返回 400），内部走重建后的 Agent（每请求独立工作区，结束即清理）；保留 `stream` 双模式与既有响应契约；ai_usage 指标记录保留
- [x] 5.4 集成测试：三端点流（mock agent）、缺项目 400、项目绑定不漂移、取消鉴权、agent-search 必填校验

## 6. 前端：对话框（AIChat.vue + runs store）

- [ ] 6.1 runs store（`frontend/src/stores/`）：新增 `startPackageSearchRun`（对齐 `startProjectExpertRun`：FormData 携带 message/history/project_repo_id/remember，订阅 SSE、恢复、取消走 `/package-search/*`）；`frontend/src/api/` 增加对应 API 封装
- [ ] 6.2 `AIChat.vue`：`isProjectRepoSelectVisible` 与 `isProjectRepoRequiredMissing` 纳入 `isPackageAgentSelected`；`setTargetAgent` 对 `package-manager` 调用 `ensureProjectRepoOptions()`；`sendMessage` 的包 Agent 分支改走 `startPackageSearchRun` 并删除 `runPackageAgent` 旧 SSE 处理；未选项目时阻止发送并提示 `selectProjectFirst`
- [ ] 6.3 GeneralAgent 建议切换（`chooseSuggestedAgent('package_search')`）验证项目必选链路自然生效；欢迎页能力卡片点击"包"卡片后同样触发项目选项加载
- [ ] 6.4 `frontend/src/i18n/{zh,en}.ts`：重构包 Agent 项目必选相关文案

## 7. 前端：包管理（RavenManager / 详情 / 类型）

- [ ] 7.1 `RavenManager.vue`：上传表单包类型下拉 → 项目下拉（`projectRepoApi.listEnabled()`，必选，未选阻止提交）；批量上传同理；上传请求体 `packageType` → `projectCode`
- [ ] 7.2 `RavenManager.vue`：列表筛选下拉改为项目 + "未关联"选项；包列表/检索结果卡片的类型 pill 改为项目名（反查不到显示"未关联"+原始 code）
- [ ] 7.3 `RavenManager.vue` 智能检索：新增必选项目下拉（未选禁用检索），`agent-search` 请求体带 `project_repo_id`
- [ ] 7.4 `RavenPackageDetail.vue`：展示项目名称/未关联占位；`frontend/src/types/index.ts` 的 Package 类型 `packageType` → `projectCode`；`frontend/src/api/raven.ts` 参数适配
- [ ] 7.5 `frontend/src/i18n/{zh,en}.ts`：包管理项目维度文案（移除/替换 `raven.packageType.*` 系列）

## 8. 指标与管理端

- [x] 8.1 `metrics_service.py` / 总览 API：包分布从类型改为项目（`packagesByProject` 含 `unassociated`）
- [ ] 8.2 `AdminMetrics.vue`：包分布图表字段与文案改为项目维度
- [ ] 8.3 指标测试：overview 新结构、`package_activity` 事件 metadata 含 `project_code`

## 9. 收尾验证

- [ ] 9.1 全量后端测试通过（`pytest`），前端构建通过（`npm run build`）；grep 确认 `PACKAGE_TYPES` / `determine_package_type` / `download/type/` / `packagesByType` 无残留引用
- [ ] 9.2 迁移说明：在变更文档/部署说明中列出 BREAKING API 清单、部署前预创建项目建议、Grafana 旧 `package_type` label 失效提示
- [ ] 9.3 手工冒烟：选项目 → 重构包 Agent 问"两个版本间项目改了什么"（验证 git log 优先且不读代码）；问包元数据问题（验证不克隆仓库）；后台改提示词后再次提问验证即时生效；上传新包全流程
