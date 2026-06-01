## Why

Log Analysis Agent 已经证明了 **Claude Agent SDK + 克隆项目源码 + 加载 Skill + 流式 agent trace** 这条链路的价值，但它的入口被"上传日志包"绑死：用户必须先有一份日志归档、归档里要有 `metadata.json`，Agent 才能解析项目身份并克隆代码。然而很多场景下用户手里**没有日志**，只是想就某个已登记的项目问代码层面的问题——"这个项目的鉴权是怎么做的"、"X 模块在哪几个文件里实现"、"帮我评估加一个 Y 特性要改哪些地方"。今天没有一个智能体能直接回答这类"对着项目源码答疑"的问题。

我们要在 Log Analysis Agent 的同构基础上新增一个 **"项目专家"（Project Expert）Agent**：同样基于 Claude Agent SDK，但**去掉附件日志分析这一环**——不上传归档、不解压 `logs/`、不依赖 `metadata.json`。改为由用户**显式选择一个已登记项目**并直接提问，Agent 克隆该项目代码、加载启用的 Skill、用 Read/Grep/Glob/Bash 分析源码后给出答案，并复用 Log Analysis 现有的会话级工作区与 SSE agent trace 机制支持多轮追问。

## What Changes

- 新增基于 Claude Agent SDK 的 **`ProjectExpertAgent`**（`app/agents/project_expert/`），与 Log Analysis Agent 同构：
  - `agent.py` 驱动 `query()` agent loop，复用 Log Analysis 的取消、超时、token 掩码、结果抽取等机制；
  - `prompts.py` 读取并渲染新的 `claude_agent_project_expert` 提示词；
  - `workspace.py` 为每个会话准备**只含 `repo/` 占位目录 + `task.json`** 的隔离工作区（**没有 `logs/`、不解压任何归档、不要求 `metadata.json`**）；
  - `trace.py`：**复用** `app/agents/log_analysis/trace.py`（`AgentTraceEvent`/`_RunState`/事件常量），不重复实现；
  - MCP 工具：**复用** `app/agents/log_analysis/mcp_tools.py` 的 `lookup_project_repo`（in-process MCP server），无需新建。
- **去掉附件日志分析**：`ProjectExpertAgent` 的请求入口不接受 `file` 上传；工作区不创建 `logs/`、不调用归档解压、不做 `metadata.json` 存在性校验；`ALLOWED_TOOLS` 保持 `Bash / Read / Grep / Glob / Skill / lookup_project_repo`，但提示词中删去一切"读取 logs/、定位 metadata.json"的步骤，改为"以用户问题为中心，克隆并分析项目源码"。
- 新增**项目身份强制来源**：因为没有 `metadata.json` 可回退，`project_repo_id` 从"可选"变为**必填**。服务层在准备工作区时把所选项目仓库信息（`project_code` / `repo_url` / `default_branch` / `source: "user_selected_project_repo"`）写入 `task.json` 的 `repo_info`，Agent 直接据此克隆。
- 新增 **`ProjectExpertChatService`**（`app/services/project_expert_chat_service.py`），以 Log Analysis 的 `LogAnalysisChatService` 为蓝本：保持**会话级持久工作区**（首轮克隆、后续轮复用 `repo/.git`）、in-process `AgentJob` 注册表、SSE 事件缓冲与断线重连、`/result` 轮询兜底、取消机制；但移除全部文件上传分支，并把 `project_repo_id` 作为新会话必填参数。
- 新增 **API 端点**：`POST /project-expert/stream`（流式）、`POST /project-expert/cancel`、`GET /project-expert/result`，与现有 `/log-analysis/*` 三件套对齐；`stream` 接受 `message` / `session_id` / `history` / `remember` / `project_repo_id`（必填），**不接受 `file`**。
- 新增 **提示词配置** `claude_agent_project_expert.generic`（`system_prompt` / `user_prompt_template`）到 `app/prompts/prompts_config.yaml`，描述只含 `repo/` 的工作区、克隆复用规则、以"回答用户问题"为目标的工作流；不复用 Log Analysis 中关于日志/metadata 的章节。
- 新增 **Skill 装载**：在 `app/services/skills_service.SUPPORTED_AGENTS` 注册 `project_expert` 条目；Agent 每次请求前用 `materialize_enabled_skills("project_expert", workspace_dir)` 物化启用的 Skill 到 `<workspace>/.claude/skills/<name>/`，以 `setting_sources=["project"]` 让 SDK 自动加载；admin `AdminAgentSkills.vue` 下拉据 `SUPPORTED_AGENTS` 自动新增 `ProjectExpertAgent`。
- 新增 **前端入口**：`frontend/src/views/AIChat.vue` 在现有 Agent 下拉中新增"项目专家"选项（与"日志分析"、"重构包配置管理员"并列），选中后**要求选择关联项目、禁用文件上传**，走新的 `/project-expert/stream` 路径并复用现有 `AgentTraceStream` 渲染。

## Capabilities

### New Capabilities
- `project-expert-agent`：基于 Claude Agent SDK 的项目源码答疑智能体。用户显式选择一个已登记项目并提问，Agent 克隆该项目代码到会话级隔离工作区、加载启用的 Skill、用 Read/Grep/Glob/Bash 分析源码后回答问题；保持会话工作区以支持多轮追问；以 SSE 事件向前端流式推送 agent trace。与 Log Analysis Agent 同构但**不含附件日志分析**（无归档上传 / 无 `logs/` / 无 `metadata.json` 依赖）。

### Modified Capabilities
<!-- 复用 agent-trace-stream / agent-trace-ui / anthropic-llm-config / project-repo-registry 的现有行为，不改变其 spec 级要求；故此处为空。Skill 注册表的扩展记入 project-expert-agent 自身 spec。 -->

## Impact

- **新增代码**：`app/agents/project_expert/{__init__.py,agent.py,prompts.py,workspace.py}`（`trace`/`mcp_tools` 复用 log_analysis）、`app/services/project_expert_chat_service.py`、`app/api/ai_chat.py` 新增 `/project-expert/{stream,cancel,result}` 三个端点、`tests/agents/test_project_expert.py` 等。
- **修改代码**：`app/services/skills_service.py`（`SUPPORTED_AGENTS` 新增 `project_expert`）、`app/prompts/prompts_config.yaml`（新增 `claude_agent_project_expert` 块）、前端 `frontend/src/views/AIChat.vue`（新增 Agent 选项 + 项目必选 + 禁用上传 + 调新端点）、`frontend/src/api/`（新增 project-expert 流式/取消/结果方法）。
- **复用**：`app/agents/log_analysis/trace.py`、`app/agents/log_analysis/mcp_tools.py`、`app/services/project_repo_service.py`、`AgentTraceStream.vue`、`conversationRuns` store 的 SSE 解析。
- **配置**：复用 `code_repo_clone_base_dir`、`code_repo_git_token`、`ANTHROPIC_*` 全部现有字段；**不新增** env 字段，**不新增**依赖（`claude-agent-sdk` 已存在）。
- **API/契约**：`POST /chat` / `/chat/stream` / `/log-analysis/*` 全部保持不变；仅新增 `/project-expert/*` 三个端点。
- **数据库**：复用 `chat_message` / `chat_session`（仍写 `role` / `content`）；不引入新表、不改 schema。
- **不在范围内**：不改 Log Analysis Agent 既有行为；不改 DeviceAgent / GeneralAgent / PackageSearch；不改设备通信协议。
