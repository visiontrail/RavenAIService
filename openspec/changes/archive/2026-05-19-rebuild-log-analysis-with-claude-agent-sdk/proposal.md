## Why

当前日志列表中的"AI 分析"功能由 LangGraph 实现，代码集中在 `app/agents/log_agent.py`（2110 行）与 `app/agents/code_analysis_graph.py`（2747 行），随业务演进已变得难以维护：状态机/子图的人为编排掩盖了实际推理路径，工具调用是自研薄封装、与提示词强耦合，并依赖 OpenAI 兼容接口（DeepSeek / GLM 等中转网关）发送请求。我们希望把推理控制权完全交给模型，采用 Anthropic 官方的 **Claude Agent SDK** 提供的 agent loop 与内置工具，并为后续其他 AI 对话场景的迁移先行铺设 Anthropic 标准的配置与客户端适配层。

同时，业务实际仍主要使用国内开源模型（如 DeepSeek、智谱 GLM 等），其中 DeepSeek 提供 **Anthropic 兼容端点**（`https://api.deepseek.com/anthropic`，参考 https://api-docs.deepseek.com ），可以让 Claude Agent SDK 在不改代码的前提下直接对接。因此本次配置层需要从一开始就把"上游服务商"作为显式维度，支持在 Anthropic 官方与 Anthropic 兼容的第三方之间切换，并显式记录每个 provider 的能力差异（图像/文档输入、`thinking.budget_tokens`、`disable_parallel_tool_use` 等）。

## What Changes

- **BREAKING** 删除 LangGraph 版日志分析实现：`app/agents/log_agent.py`、`app/agents/code_analysis_graph.py`、`app/agents/xml_utils.py`，以及 `app/tasks/ai_analysis.py` 中所有对它们的引用与降级分支。本次不参考、不复用其内部状态机/提示词结构，提示词重新基于 Claude Agent SDK 工作流设计。
- **BREAKING** 移除 `requirements.txt` 中仅服务于日志分析的 LangGraph 依赖（`langgraph`、`langchain`、`langchain-community`、`langchain-openai`），引入 `claude-agent-sdk`（及其传递依赖 `anthropic`）。
- 新增 **Anthropic 标准 LLM 配置层 + provider profile 机制**：在 `app/config.py` 增加 `anthropic_provider`（枚举：`anthropic`、`deepseek`、`custom`）、`anthropic_api_key`、`anthropic_base_url`、`anthropic_model`、`anthropic_max_tokens`、`anthropic_max_turns` 等设置；并新增统一访问入口 `app/agents/anthropic_client.py`，根据 provider 选择默认 base_url / model id、记录该 provider 的能力矩阵（图像/文档输入是否支持、`thinking.budget_tokens` 是否生效、`disable_parallel_tool_use` 是否生效等），并把这些标准值通过环境变量（`ANTHROPIC_BASE_URL` / `ANTHROPIC_API_KEY`）以及 `ClaudeAgentOptions` 传递给 SDK。**保留** 现有 OpenAI 兼容设置以兼容 `chat_agent` / `ai_chat_service`，后续迁移在独立变更中处理。
- 新增基于 Claude Agent SDK 的 **`LogAnalysisAgent`**（`app/agents/log_analysis/`）：
  - 工作区准备阶段由 Python 端解压日志归档（含 `metadata.json`）到临时目录，但 **不**预解析仓库地址；
  - 系统提示词指导 Agent 自主完成：(1) 用 `Read` 读取 `logs/.../metadata.json` 获取 **项目名称**与**项目代号**；(2) 调用我们暴露的自定义工具 `lookup_project_repo(project_code, project_name?)` 解析出 git URL / 默认分支；(3) 用 `Bash` 在临时目录内 `git clone` 并 checkout；(4) 用 `Bash`/`Read`/`Grep`/`Glob` 在仓库中按问题描述检索关键字、定位调用链，并在解压后的日志中比对上下文；
  - 输出结构化分析结果（摘要、根因假设、证据片段、建议修复）写回 `LogRecord.ai_analysis_result` 字段，并在任务结束后清理临时目录。
- 新增 **项目→仓库注册表（project-repo-registry）**：DB 表存储 `project_code`（业务唯一键）、`project_name`、`repo_url`、`default_branch`、可选 `git_token`（覆盖全局 token）；admin API 提供 CRUD + 连通性测试；admin 前端页面提供管理界面（替代当前仅支持 OAM/Stack 两个固定槽位的 `code_repo_oam_url`/`code_repo_stack_url` 设计）。
- 新增 **Claude Agent SDK 内嵌 MCP 工具** `lookup_project_repo`（in-process MCP server，通过 `@tool` + `create_sdk_mcp_server` 注册），输入 `{project_code, project_name?}`，返回 `{repo_url, default_branch, auth_required}` 或 `{error: "not_found"}`；该工具是日志分析 Agent 的 `allowed_tools` 之一。
- **重写** Celery 入口 `app/tasks/ai_analysis.run_ai_analysis_task`：去掉对仓库元数据是否完整的双路分支，统一交由新 Agent 处理；当日志归档中缺 `metadata.json`、`metadata.json` 中缺项目名/代号、或注册表中无对应条目时，分别返回明确的 `error_kind` 而非降级到旧实现。
- **配置/提示词**：在 `app/prompts/prompts_config.yaml` 中新增 Claude Agent SDK 版日志分析提示词条目，并在 `app/services/prompts_config_service.py` 中移除对 `log_agent._PROMPTS_CACHE` 的内部清理钩子（改用新 Agent 提供的刷新接口）。

## Capabilities

### New Capabilities
- `log-analysis-agent`：基于 Claude Agent SDK 的日志智能分析能力——由 Agent loop 自主驱动 metadata.json 解析、项目→仓库地址查询、仓库克隆、关键字检索、日志比对并生成结构化结论。
- `anthropic-llm-config`：Anthropic 标准协议的配置与客户端访问层——为日志分析 Agent 与未来迁移的其他 Agent 提供统一的 provider profile / API key / base_url / 模型 / 工具权限配置；显式支持 Anthropic 官方与 Anthropic 兼容的第三方 provider（首发支持 DeepSeek），并记录各 provider 的能力矩阵。
- `project-repo-registry`：管理员可在 admin 页面维护"项目代号 → git 仓库地址"映射；后端提供 CRUD API、连通性测试、按项目代号查询接口，并以 Claude Agent SDK in-process MCP 工具 `lookup_project_repo` 暴露给日志分析 Agent。

### Modified Capabilities
<!-- openspec/specs/ 当前为空，本次变更不修改已有 capability。 -->

## Impact

- **代码删除**：`app/agents/log_agent.py`、`app/agents/code_analysis_graph.py`、`app/agents/xml_utils.py`、`app/agents/tools/` 中仅服务于 LangGraph 的工具，以及 `app/tasks/ai_analysis.py` 中所有从 LogRecord 反推仓库 URL 的兼容分支（仓库 URL 不再从 LogRecord 读取）。
- **新增代码**：`app/agents/anthropic_client.py`、`app/agents/log_analysis/{__init__.py,agent.py,workspace.py,prompts.py,mcp_tools.py}`、`app/models/project_repo.py`、`app/services/project_repo_service.py`、`alembic/versions/<timestamp>_add_project_repo_registry.py`、`tests/...`。
- **配置**：`app/config.py` 新增 Anthropic 字段（默认 `None`，缺失时启动失败而非静默回退）；`.env.example`（若存在）同步新增 `ANTHROPIC_*` 等。**弃用**（保留兼容读取一个 release 周期）：`code_repo_oam_url`、`code_repo_stack_url`——首次迁移时把它们的非空值作为初始 seed 写入 `project_repo` 表（`project_code` 由 admin 录入或按 `oam_antenna`/`stack` 默认填充）。
- **依赖**：`requirements.txt` 移除 LangGraph/LangChain，新增 `claude-agent-sdk>=0.1`；Docker 镜像需重新构建。
- **API/契约**：
  - `POST /logs/{id}/ai-analysis` 等触发接口对外形态不变，但缺 `metadata.json`、缺项目代号、注册表无对应条目时分别返回 `400` 与不同 `error_kind`。
  - 新增 `GET/POST/PUT/DELETE /admin/project-repos` 与 `POST /admin/project-repos/{id}/test-connection`；旧 `GET/PUT /admin/repo-settings` 在本变更里改为只读视图（向后兼容前端老版本），下个 release 删除。
- **数据库**：新增 `project_repo` 表（schema 见 design.md），含 alembic migration。
- **前端**：`frontend/src/views/AdminRelease.vue` 等管理页面新增"项目仓库管理"子页（CRUD + 连通性测试），替换原"OAM/Stack 仓库设置"双输入框。
- **运维**：临时克隆目录沿用 `code_repo_clone_base_dir`，新 Agent 在每次任务结束/异常时清理；Celery worker 需有可访问 Git 与 Anthropic（或 DeepSeek 兼容端点）的网络权限。
- **未迁移项**：`app/agents/chat_agent.py` 与 `app/services/ai_chat_service.py` 仍走 OpenAI 兼容路径，在后续变更中迁移。
