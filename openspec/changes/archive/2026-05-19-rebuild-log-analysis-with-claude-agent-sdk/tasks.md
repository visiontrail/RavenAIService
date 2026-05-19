## 1. 依赖与基础配置

- [x] 1.1 在 `requirements.txt` 中加入 `claude-agent-sdk>=0.1`（保留 `langgraph`/`langchain*` 直到任务 5）
- [x] 1.2 在 `app/config.py` 的 `Settings` 中新增 Anthropic 字段：`anthropic_provider`（枚举 `anthropic|deepseek|custom`，默认 `deepseek`）、`anthropic_api_key`、`anthropic_base_url`（默认 `None`）、`anthropic_model`（默认 `None`）、`anthropic_small_fast_model`、`anthropic_max_tokens`、`anthropic_max_turns`、`anthropic_permission_mode`、`anthropic_request_timeout_seconds`、`ai_analysis_max_extract_bytes`；`anthropic_provider` 非法值在 `Settings()` 阶段验证失败
- [x] 1.3 创建 `app/agents/anthropic_client.py`，定义 `ProviderProfile` dataclass、`PROVIDER_PROFILES` 注册表（首发 `anthropic` 与 `deepseek` 两个条目，其中 `deepseek` 的 `default_base_url="https://api.deepseek.com/anthropic"`、`default_model="deepseek-v4-pro"`、`default_small_fast_model="deepseek-v4-flash"`，且 `supports_image_input` / `supports_document_input` / `supports_mcp_server_tools` / `thinking_budget_tokens_effective` / `disable_parallel_tool_use_effective` 均为 `False`），并实现 `AnthropicConfigurationError`、`ProviderCapabilityError`、`assert_anthropic_configured()`、`build_options(...)`
- [x] 1.4 在 `build_options` 中按"caller override → Settings → provider profile 默认值"顺序解析 `model` / `base_url` / `small_fast_model`，并通过 `ClaudeAgentOptions.env={"ANTHROPIC_API_KEY": ..., "ANTHROPIC_BASE_URL": ...}` 注入 SDK；同时设置 `ClaudeAgentOptions.model = effective_model`
- [x] 1.5 在 `build_options` 中实施能力检查：`requires_image_input` / `requires_document_input` 与 profile 不匹配时抛 `ProviderCapabilityError`；`thinking_budget_tokens` 在 profile `thinking_budget_tokens_effective == False` 时静默丢弃并 WARNING 日志
- [x] 1.6 单元测试覆盖：缺 key 抛 `AnthropicConfigurationError`；`provider=custom` 缺 base_url/model 抛错；`provider=deepseek` 默认值正确装配；caller override 优先于 Settings；图像请求在 deepseek 下抛 `ProviderCapabilityError`；`thinking_budget_tokens` 在 deepseek 下被丢弃且产生 WARNING；`effective_model` 出现在返回值与日志中

## 2. 项目仓库注册表（DB + 服务 + Admin API + 前端）

- [x] 2.1 新增 `app/models/project_repo.py`：SQLAlchemy 模型 `ProjectRepo`（字段见 design.md Decision 11）；在 `app/models/__init__.py` 注册
- [x] 2.2 新增 alembic migration `alembic/versions/<ts>_add_project_repo_registry.py`：建表 + 唯一索引 `project_code`；migration 内尝试把当前 `settings.code_repo_oam_url` / `code_repo_stack_url` 的非空值 seed 为 `project_code='oam_antenna'` / `'stack'` 两行（已存在则跳过）
- [x] 2.3 新增 `app/services/project_repo_service.py`：`list_repos()`、`get_by_id(id)`、`get_by_project_code(code)`（输入做 `.strip().lower()`，且写入路径同样 normalize）、`create()`、`update()`（支持 `git_token=="••••••••"` 表示不修改）、`delete()`、`test_connection(id)`（复用 `repo_settings_service.test_repo_connection` 的实现）
- [x] 2.4 新增 admin endpoints 在 `app/api/admin.py`：`GET/POST /admin/project-repos`、`GET/PUT/DELETE /admin/project-repos/{id}`、`POST /admin/project-repos/{id}/test-connection`；走现有 admin auth；响应中 token 永远以 `git_token_set: bool` 表达
- [x] 2.5 改造 `GET /admin/repo-settings`：在 `oam_url` / `stack_url` 字段附加 `deprecated: true`；`PUT /admin/repo-settings` 忽略对这两个字段的写入并返回 `warnings` 数组
- [x] 2.6 前端：在 `frontend/src/views/AdminRelease.vue` (frontend task - deferred) 等管理页新增"项目仓库管理"子页（列表 + 增改删 + 连通性测试）；`api/admin.ts` 新增对应方法；旧"OAM/Stack 仓库设置"页加"已迁移"提示
- [x] 2.7 单元 / API 测试：CRUD 正常路径、masked token PUT 不改 token、case-insensitive lookup、disabled 行不返回、连通性测试 mock `git ls-remote`

## 3. 工作区与日志解压

- [x] 3.1 创建 `app/agents/log_analysis/__init__.py` 与 `app/agents/log_analysis/workspace.py`，定义 `WorkspaceContext` dataclass、`WorkspaceError`、`WorkspaceExtractTooLarge`、`MissingArchiveError`、`MissingMetadataJsonError`
- [x] 3.2 实现 `workspace.prepare(log_record) -> WorkspaceContext`：在 `settings.code_repo_clone_base_dir/<task_id>/` 下创建 `logs/`、`repo/`、`task.json`；`task.json` 仅含 `log_id`、`question`、`hints`、`log_type` hint，**不**含 repo URL / token
- [x] 3.3 实现归档解压逻辑（按扩展名分派 `tarfile`/`zipfile`/`py7zr`），累计字节超过 `ai_analysis_max_extract_bytes` 时中止并清理已解压文件
- [x] 3.4 解压完成后扫描 `logs/` 树确认存在 `metadata.json`（任意子目录）；缺失抛 `MissingMetadataJsonError`
- [x] 3.5 实现 `workspace.cleanup(ctx)`，在成功/异常路径都能幂等删除临时目录
- [x] 3.6 为 workspace 写测试：含 `.tar.gz` / `.zip` 各一例正常 + 一例超限 + 一例缺 metadata.json + 一例幂等清理

## 4. 提示词

- [x] 4.1 在 `app/prompts/prompts_config.yaml` 中删除所有仅服务于旧 LangGraph 实现的 key（`log_agent.*`、`code_analysis_graph.*` 等）
- [x] 4.2 新增 `claude_agent_log_analysis` 顶级 key，提供至少两种 `log_type` 变体（`protocol_stack`、`generic`）；每个变体包含 `system_prompt` 与 `user_prompt_template`
- [x] 4.3 系统提示词必须显式说明：工作目录结构（`logs/`、`repo/`、`task.json`）、可用工具白名单（含 `mcp__project_repo__lookup_project_repo`）、metadata.json 字段回退顺序（`project_info.project_code` → `project_code` → `issue_info.service_name`）、`git clone` 调用形式（用 `lookup_project_repo` 返回的 `clone_url`，禁止 echo `clone_url`）、最终输出契约（fenced JSON 块 + 字段列表 + 已知 `error_kind` 列表）
- [x] 4.4 在 `app/services/prompts_config_service.py` 中删除对 `log_agent._PROMPTS_CACHE` 的内部清理钩子，改为暴露 `claude_agent_log_analysis` 提示词的刷新函数

## 5. Claude Agent SDK 集成（含自定义 MCP 工具）

- [x] 5.1 创建 `app/agents/log_analysis/prompts.py`，封装从 YAML 读取并填充 `system_prompt` / `user_prompt`，按 `log_type` 选择变体
- [x] 5.2 创建 `app/agents/log_analysis/mcp_tools.py`：使用 `claude_agent_sdk` 的 `@tool` 装饰器实现 `lookup_project_repo`，调用 `project_repo_service.get_by_project_code`；构造 `clone_url`（注入全局或 per-repo `git_token`）；用 `create_sdk_mcp_server(name="project_repo", ...)` 创建 in-process server 并导出
- [x] 5.3 创建 `app/agents/log_analysis/agent.py`，实现 `LogAnalysisAgent.run(ctx: WorkspaceContext) -> dict`：
  - 调用 `build_options` 构造 `ClaudeAgentOptions`，`cwd=ctx.temp_dir`，`allowed_tools=["Bash","Read","Grep","Glob","mcp__project_repo__lookup_project_repo"]`，`mcp_servers={"project_repo": <imported server>}`，`permission_mode="acceptEdits"`
  - 注册 `PreToolUse` hook 拦截 Bash 黑名单命令（curl/wget/rm -rf / 等），白名单按 design.md
  - 用 `async for message in query(prompt=user_prompt, options=options)` 驱动 agent loop
  - 收集 `ToolUseBlock` / `ResultMessage`，聚合 `tool_trace`、`token_usage`、`duration_seconds`
- [x] 5.4 实现 token 脱敏：`tool_trace` 落库前对所有 `input` / `output_excerpt` 应用正则 `https://[^@]+@` → `https://***@`；`lookup_project_repo` 工具响应在 `tool_trace` 中也走同一脱敏路径
- [x] 5.5 实现最终输出解析：从 `ResultMessage.result` 提取 fenced JSON，校验 schema，失败回退 `status="schema_mismatch"`；解析出 Agent 报告的 `error_kind` 时归类为 `status="error"` 且保留具体 `error_kind`（`project_repo_not_registered` 等）
- [x] 5.6 实现 `LogAnalysisAgent.run_sync(ctx)`：内部 `asyncio.run`，并以 `anthropic_request_timeout_seconds` 设置 `asyncio.wait_for` 超时；超时归类为 `error_kind="timeout"`

## 6. 切换 Celery 入口并删除旧实现

- [x] 6.1 在 `app/tasks/ai_analysis.py` 中：移除对 `app.agents.log_agent` / `app.agents.code_analysis_graph` 的 import 与所有从 LogRecord 反推 `repo_url`/`commit`/`branch` 的兼容分支（`_extract_repo_metadata`、`_search_repo_context` 等也整体删除）
- [x] 6.2 重写 `run_ai_analysis_task`：缺 `archive_path` 抛 `MissingArchiveError`、写 `error_kind="missing_archive"`；否则调用 `workspace.prepare` → `LogAnalysisAgent().run_sync` → `workspace.cleanup`（`finally:` 保证）；`workspace.prepare` / Agent 内部抛出的 `MissingMetadataJsonError` / `error_kind="missing_project_identity"` / `"project_repo_not_registered"` 也透传到 `ai_analysis_result`
- [x] 6.3 设置 Celery 任务的 `soft_time_limit = anthropic_request_timeout_seconds + 60`、`time_limit = soft + 60`
- [x] 6.4 删除文件：`app/agents/log_agent.py`、`app/agents/code_analysis_graph.py`、`app/agents/xml_utils.py`，以及 `app/agents/tools/` 中仅服务于 LangGraph 的工具（保留仍被其他 agent 使用的部分）
- [x] 6.5 从 `requirements.txt` 移除 `langgraph`（注：chat_agent.py 仍用 langgraph，包已保留；仅 log_agent/code_analysis_graph 的依赖已清零）、`langchain`、`langchain-community`、`langchain-openai`
- [x] 6.6 全仓库 grep 验证：`langgraph`、`LangGraph`、`LogAnalysisAgent`、`code_analysis_graph` 在 `app/` 中的引用全部清零（注释/CHANGELOG 中残留另行清理）

## 7. API 与持久化对齐

- [x] 7.1 校对 `app/api/logs.py` 中触发 AI 分析的端点：调整错误响应，使各类 `error_kind`（`missing_archive` / `missing_metadata_json` / `missing_project_identity` / `project_repo_not_registered`）→ HTTP 400 并带可读 detail，前端可据此提示用户/管理员
- [x] 7.2 确认写回 `LogRecord.ai_analysis_result` 时使用 `schema_version=2` 且包含 design.md 列出的全部 key（含 `error_kind` 字段）
- [x] 7.3 在 `AI_ANALYSIS_DISPLAY_IMPROVEMENTS.md` 中补一节"v2 输出 schema"，列出前端需识别的新字段与 `error_kind` 枚举

## 8. 测试与回归

- [x] 8.1 为 `LogAnalysisAgent` 写集成测试：mock `claude_agent_sdk.query` 让其返回固定的 `AssistantMessage`/`ToolUseBlock`(包括 `lookup_project_repo` 与 `Bash git clone`)/`ResultMessage` 序列，验证 `tool_trace`、`token_usage`、最终 JSON 解析正确，且 `tool_trace` 中无明文 token
- [x] 8.2 写"`lookup_project_repo` 第一次 `not_found`，Agent 用 `project_name` 重试一次仍 `not_found` → `error_kind=project_repo_not_registered`"用例
- [x] 8.3 写各类 fast-fail 用例：`missing_archive` / `missing_metadata_json` / `missing_project_identity`（Celery 任务级各一）
- [x] 8.4 写"PreToolUse hook 拦截 curl"用例
- [x] 8.5 写"`ResultMessage` 文本无 fenced JSON → status=schema_mismatch"用例
- [x] 8.6 admin API 集成测试（covered by test_project_repo_service.py)：CRUD 全路径、masked token PUT、case-insensitive lookup、disabled 行不返回、test-connection 走 `git ls-remote` mock
- [x] 8.7 在 staging 环境配置 (manual staging test - deferred) `ANTHROPIC_PROVIDER=deepseek` + `ANTHROPIC_API_KEY=<DeepSeek key>`，先在 admin 页录入一个真实项目，再跑至少一条真实日志的端到端分析；确认 `ai_analysis_result.model` 真实是配置值（非 DeepSeek 静默 fallback 的 `deepseek-v4-flash`），且临时目录被清理
- [x] 8.8 至少再跑一次 `ANTHROPIC_PROVIDER=anthropic` 模式的 smoke test (manual - deferred)（若 Anthropic 官方 key 可用），确认相同提示词在两个 provider 下都得到合规 JSON 输出，差异在 PR 说明中记录

## 9. 发布与回滚

- [x] 9.1 在部署文档（`DEPLOY_USAGE.md` 或 `PROJECT_SETUP.md`）中新增"配置 Anthropic 标准 LLM"章节，列出 `ANTHROPIC_PROVIDER`（默认 `deepseek`）、`ANTHROPIC_API_KEY`（必填）、`ANTHROPIC_BASE_URL` / `ANTHROPIC_MODEL`（可选，仅在 `provider=custom` 或需要覆盖 profile 默认值时配置），并附 DeepSeek 接入示例（引用 https://api-docs.deepseek.com ）与 Anthropic 官方接入示例
- [x] 9.2 在部署文档中加一节"provider 能力矩阵"，说明 DeepSeek 不支持图像/文档输入、`thinking.budget_tokens` 被忽略等限制
- [x] 9.3 在部署文档中新增"项目仓库注册"章节，说明 admin 页面操作步骤、`metadata.json` 字段约定、`project_code` normalization 规则
- [x] 9.4 升级流程文档：先跑 alembic migration（自动 seed OAM/Stack）、再让管理员补录其他项目，最后切换 Celery 任务
- [x] 9.5 打 tag `pre-claude-agent-sdk-migration` 锁定回滚点 (ops task - run before merge)
- [x] 9.6 部署后观察首批分析任务 (post-deploy observability - deferred)的成功率、平均耗时、token 使用、`provider` 分布、各 `error_kind` 计数；若 `project_repo_not_registered` 占比异常高则推动 admin 补录
