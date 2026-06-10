# 提案：重构包检索 Agent 项目化重建（rebuild-package-search-with-project-context）

## Why

重构包检索 Agent（"重构包配置管理员"）目前是平台三个专门 Agent 中能力最弱的一个：

1. **没有项目仓库访问能力** —— 日志分析与项目专家均可克隆项目仓库、检索代码，而重构包 Agent 只能查询 JSON 元数据库的 7 个 MCP 工具，无法回答"这个包对应哪些提交/修复了什么"这类需要 Git 上下文的问题；
2. **系统提示词硬编码** 在 `app/agents/package_search/prompts.py` 里，管理员无法像日志分析（`claude_agent_log_analysis`）、项目专家（`claude_agent_project_expert`）那样在后台提示词管理页调整；
3. **包类型是写死的 6 个枚举**（`lingxi-10` / `ka-tx` 等）。平台已演进出权威的项目身份来源 —— 项目仓库注册表（`project_repo`），日志分析与项目专家都已接入；重构包与项目天然一一对应，继续维护一套独立的硬编码类型既冗余又无法随项目扩展。

本变更将重构包与后台已配置的项目（`project_repo`）关联，并把重构包检索 Agent 重建为与项目专家同构的"项目绑定"Agent，同时赋予其"Git 提交记录优先、必要时才读代码"的差异化分析策略。

## What Changes

- **【BREAKING】包元数据模型项目化**：包元数据中写死的 `packageType` 枚举改为项目关联字段 `projectCode`（取值来自项目仓库注册表 `project_repo.project_code`）；提供存量数据迁移（旧 `packageType` 值平移为 `projectCode`，未匹配注册项目的包标记为"未关联"）；`RavenPackageService.PACKAGE_TYPES` 常量与文件名推断包类型的逻辑废弃。
- **【BREAKING】对外包管理 API 适配**：`GET /packages`（`type` 筛选 → `projectCode` 筛选）、`POST /upload`、`POST /upload/batch`（`packageType` 表单字段 → `projectCode`，并校验是否为已注册项目）、`GET /packages/stats/overview`（按类型分布 → 按项目分布）、`GET /download/type/{package_type}` → `GET /download/project/{project_code}`，以及 `package_activity` 业务指标的维度从包类型改为项目。
- **重构包检索 Agent 重建**（对齐项目专家架构）：
  - 项目绑定：检索请求必须携带 `project_repo_id`，新会话缺失时报 4xx（与项目专家一致）；
  - 工作区与仓库访问：为每次会话准备 `repo/` + `task.json` 工作区，放开 `Bash`/`Read`/`Grep`/`Glob` 工具并复用 `lookup_project_repo` MCP 工具，使 Agent 能克隆所选项目仓库；
  - **Git 提交记录优先策略**：提示词与工具引导明确要求 Agent 先用 `git log` / `git show` 等提交记录分析回答问题，只有在提交记录不足以回答时才读取代码文件；
  - 包元数据 MCP 工具按所选项目自动限定范围（服务端强制，不依赖模型自觉）；
  - 新增 `/package-search/stream`、`/package-search/cancel`、`/package-search/result` 聊天端点（与项目专家三端点同构，含会话级工作区复用）；既有 `POST /packages/agent-search` 保留但要求 `project_repo_id`。
- **提示词后台化**：系统提示词从 Python 常量迁移到 `prompts_config.yaml` 新增的 `claude_agent_package_search` 区块，注册到后台提示词管理元数据（`PROMPT_FUNCTION_META` / `PROMPT_AGENT_META`）并接入缓存失效，管理员可在 AdminPrompts 页面编辑（含多语言变体）。
- **前端适配**：
  - `AIChat.vue`：选择重构包 Agent 后展示项目选择下拉（与日志分析/项目专家同位），且与项目专家一致 **必须选择项目** 才能发送；GeneralAgent 路由建议一键切换到重构包 Agent 时同样触发项目选择；
  - `RavenManager.vue`：上传新包表单的包类型下拉改为项目下拉（数据来自已启用的项目注册表）、列表筛选同步改造、智能检索入口增加必选的项目选择；
  - `RavenPackageDetail.vue` / 类型定义 / i18n（zh、en）同步更新。
- **指标适配**：`package_activity` 持久化事件的 `package_type` 元数据改为 `project_code`；Prometheus 指标维持低基数标签约束（不把项目标识上报为 label）；管理端总览的"包类型分布"改为"包项目分布"。

### 不在本次范围（Out of Scope）

- 重构包 Agent 的 Skill 加载支持（`SUPPORTED_AGENTS` 注册）—— 作为后续增强单独提案；
- 项目成员（`project_repo_member`）级别的包可见性鉴权 —— 与项目专家现状一致，仅校验项目存在且启用；
- 包文件存储结构（`uploads/` 目录、tgz 格式）不变。

## Capabilities

### New Capabilities

- `package-project-association`：重构包与项目仓库注册表的关联模型 —— 包元数据的 `projectCode` 字段、存量数据迁移、包管理 CRUD/上传/下载/统计 API 的项目维度适配、上传与筛选前端改造。

### Modified Capabilities

- `package-search-agent`：检索 Agent 从"无状态元数据问答"升级为"项目绑定 + 仓库访问"形态 —— 必选项目、工作区与 Git 提交记录优先策略、包工具项目限定、提示词后台化、新增聊天三端点、前端必选项目交互。
- `system-user-metrics`：包活动指标（`package_activity`）与管理端总览的包分布维度从"包类型"改为"项目"。

## Impact

- **后端**：
  - `app/services/raven_package_service.py`（字段模型、筛选、迁移、`PACKAGE_TYPES` 废弃）
  - `app/api/packages.py`（CRUD/上传/下载/统计/agent-search 适配）
  - `app/agents/package_search/`（agent.py 重建、新增 workspace.py、prompts.py 改为读 YAML、mcp_tools.py 项目限定）
  - `app/api/ai_chat.py` + 新增 `app/services/package_search_chat_service.py`（聊天三端点）
  - `app/services/prompts_config_service.py`（提示词元数据注册 + 缓存失效）
  - `app/prompts/prompts_config.yaml`（新增 `claude_agent_package_search` 区块）
  - `app/services/metrics_service.py`、`app/utils/metrics.py`（包活动指标维度）
  - `app/i18n/`（新增报错/提示文案）
- **前端**：`frontend/src/views/AIChat.vue`、`RavenManager.vue`、`RavenPackageDetail.vue`、`AdminMetrics.vue`、`frontend/src/api/raven.ts`、`frontend/src/stores/`（run 流程）、`frontend/src/types/index.ts`、`frontend/src/i18n/{zh,en}.ts`
- **数据**：包元数据 JSON 文件一次性迁移（`packageType` → `projectCode`）；无数据库 schema 变更（`project_repo` 表复用）
- **API 兼容性**：包管理对外 API 为 BREAKING 变更（字段与路径更名），需同步通知 API 消费方；`/packages/agent-search` 请求体新增必填 `project_repo_id`
- **测试**：`tests/test_raven_package_service.py`（如有）、`tests/agents/package_search/`、`tests/api/` 相关用例需重写/扩充
