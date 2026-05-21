## Why

`app/agents/chat_agent.py`（1900+ 行）以 **LangChain + LangGraph** 实现 ChatAgent：自研 Plan→Act→Observe→Decide 状态机，仅暴露一个 `device_prompt` 工具把"DEVICE_TASK"协议化文本下发到上位机由其再决定调用哪个 MCP 工具。这一层"模型再让模型选工具"的双层间接导致：(1) 模型实际调用的 MCP 工具名从 `device_capabilities_prompt` 文本里临时猜出来，无法在 SDK 层做白名单/参数校验；(2) 工具调用循环与 LangGraph 子图深度耦合，提示词协议（`【DEVICE_TASK】`...`【/DEVICE_TASK】`）只在我们与上位机之间约定，模型并不真正"使用工具"；(3) 还在用 OpenAI 兼容网关（`OPENAI_API_KEY` / `glm-4.6` 等），与 Log Analysis Agent 已经迁移到的 **Claude Agent SDK + Anthropic 标准配置层** 形成双栈，模型/计费/上游切换要改两套；(4) Log Analysis Agent 已支持的 Skill 包装载机制（`setting_sources=["project"]` + `data/agent_skills/<agent_key>/`）在 ChatAgent 上缺位，运营无法为对话场景下发自定义工作流。

我们要把 ChatAgent 整段重写并改名为 **DeviceAgent**：模型自己驱动 agent loop；远端上报的每个 MCP 工具在 Python 层映射成一个 Claude Agent SDK 自定义工具（in-process MCP server），由模型直接选择工具与参数；高风险/破坏性操作走 Claude Agent SDK 的 **Human-in-the-loop（`canUseTool` callback）** 拿到用户确认后再执行；客户端返回结果由 `PostToolUse` hook 做结构化审查与回写护栏；与 Log Analysis Agent 一样支持 Skill 装载；并彻底丢弃 `OPENAI_API_KEY` / `deepseek_*` / `llm_*` / `runtime_settings_service` 中的"主力模型"运行期覆盖，统一走 `ANTHROPIC_*` 与 `app/agents/anthropic_client.build_options`。

## What Changes

- **BREAKING** 删除 LangGraph 版 ChatAgent 与相关入口：`app/agents/chat_agent.py`、`app/agents/tools/device_prompt_tool.py`、`app/agents/tools/__init__.py`（仅服务于 ChatAgent 的 `device_prompt` 工具），以及 `app/services/ai_chat_service.py` 中对 `ChatAgent` / `agent.ainvoke` / `agent.ainvoke_with_progress` / `agent.astream` / `agent.planner_llm` 的全部引用。本次不复用旧 Plan→Act→Observe 状态机、不复用 `【DEVICE_TASK】...【/DEVICE_TASK】` 协议化文本提示词；提示词围绕 Claude Agent SDK 工作流重新编写。
- **BREAKING** 从 `requirements.txt` 移除仅服务于 ChatAgent 的 LangChain/LangGraph 依赖（`langgraph`、`langchain`、`langchain-community`、`langchain-openai`、`langchain-core` 中 ChatAgent 独占的部分；如已被 Log Analysis 变更删除则跳过）。
- **BREAKING** 删除"主力模型"运行期配置：`app/services/runtime_settings_service.py` 中 `get_effective_primary_config` / "primary model" 一切相关键、admin "Model Settings" 页对 `model` / `base_url` / `api_key` / `temperature` 的运行时覆盖、`app/api/admin.py` 对应路由、前端 `AdminModelSettings.vue` 与 `api/admin.ts` 中的相关方法。从 `app/config.py` 移除 `openai_api_key`、`openai_base_url`、`deepseek_*`、`llm_model_name` 等仅服务于 ChatAgent 的字段（若仍被其他模块用到则按"实际依赖" grep 后决定保留/删除，并在 design 中列出）。
- 新增基于 Claude Agent SDK 的 **`DeviceAgent`**（`app/agents/device_agent/`），与 Log Analysis Agent 同构：`agent.py` 驱动 `query()` agent loop、`mcp_tools.py` 把远端上报的设备 MCP 工具动态映射成 in-process SDK 工具、`prompts.py` 提供按场景/`log_type` 风格的 system/user prompt 模板、`workspace.py` 提供一次会话级别的临时工作目录（Skill 物化用）、`trace.py` 复用 Log Analysis 的 `AgentTraceEvent`/`_RunState` 设计向前端推送 `run_start` / `step_*` / `thinking_*` / `run_complete` 事件。
- 新增 **设备 MCP 工具桥**（`app/agents/device_agent/mcp_tools.py`）：每次请求开始时从 `device_link_manager.get_device(target_device_id)` 拉取 `device.capabilities.mcp.servers[].tools[]`，对每个工具按 `(server_name, tool_name)` 用 `@tool` + `create_sdk_mcp_server` 在 in-process 注册一个 SDK 工具。工具实现把模型选择的参数封装为 `PromptEnvelope`，复用 `device_link_manager.send_prompt` 投递到上位机执行（保留现有传输协议 / topic_id 追踪），等待 ack 后把结构化结果（含 `result` / `evidence` / `topic_id` / `error`）返回给模型。工具 schema 由能力上报的 `inputSchema`/`description` 生成（缺失时回退 `prompt: str`）。
- 新增 **Human-in-the-loop 审核机制**：使用 Claude Agent SDK 的 `can_use_tool` 回调把"破坏性 / 不可逆 / 写操作类"工具拦截到一个"待用户确认"事件：通过 SSE 向前端发 `event=tool_permission_request{tool_name, args, risk, rationale}`；前端接收后调起确认 UI；用户回包通过 HTTP 端点 `POST /chat/permissions/{request_id}/resolve` 写入服务端 `asyncio.Event`/`Future`；`can_use_tool` 在拿到结果后返回 `allow`/`deny`/`allow_with_args_override`。哪些工具需要审核由能力 `risk` 元数据（`"destructive"`/`"write"`/`"read-only"`/自定义）或全局白/黑名单决定，默认对未声明 risk 的工具采取"读类直放、写类必问"。
- 新增 **客户端返回结果审查**（`PostToolUse` hook + 结果模型校验）：每个设备 MCP 工具返回后，hook 校验结果与工具 schema 的输出契约（必填字段、错误码白名单、敏感字段脱敏 / 大字段裁剪到 `output_excerpt`）；不合契约的结果不会喂回模型，而是替换为带 `error_kind` 的精简响应，避免模型基于半结构化回执做出错误下一步。
- 新增 **Skill 装载（与 Log Analysis 同机制）**：在 `app/services/skills_service.SUPPORTED_AGENTS` 中注册 `device_agent` 条目；DeviceAgent 在每次请求开始前用 `skills_service.materialize_enabled_skills("device_agent", workspace_dir)` 把启用的 Skill 物化到 `<workspace>/.claude/skills/<name>/`，并以 `setting_sources=["project"]` 让 SDK 自动加载；admin 页（`AdminAgentSkills.vue`）下拉新增 `DeviceAgent`，CRUD/启停 API 复用现有 `/admin/agent-skills/*`。
- **重写** `app/services/ai_chat_service.py`：去掉 LangChain `BaseMessage` 转换、`_SessionMemory`、`agent.planner_llm` 标题生成等所有 LangChain 依赖；改为存原始 `role/content` dict 进 DB 与服务端缓存；调用 `DeviceAgent().run(...)` / `run_stream(...)` 并把 `AgentTraceEvent` 直接转 SSE。会话标题生成改为调用 Claude Agent SDK 的 `query()` 一次性请求（一个内嵌"标题"system prompt，不带工具），统一走 `anthropic_client.build_options`。
- **配置/提示词**：在 `app/prompts/prompts_config.yaml` 中删除所有仅服务于旧 ChatAgent 的 key（包括 `chat_title_prompt` 中对 `agent.planner_llm` 的隐式假设），新增 `claude_agent_device.*`（`default`、`firmware_upgrade`、`diagnose` 等场景变体）；`app/services/prompts_config_service.py` 提供新的 `get_device_agent_prompts(...)` 入口。
- **API/前端**：保留 `POST /chat` / `POST /chat/stream` 路径与基本响应形态；SSE 事件类型扩展为 Log Analysis 同款 `run_start` / `thinking_*` / `step_*` / `run_complete`，并新增 `tool_permission_request` / `tool_permission_resolved`；新增 `POST /chat/permissions/{request_id}/resolve`；`AdminModelSettings.vue` 删除"主力模型"区，保留 Anthropic 配置只读视图；`AdminAgentSkills.vue` 下拉新增 `device_agent`。

## Capabilities

### New Capabilities
- `device-agent`：基于 Claude Agent SDK 的设备联动对话智能体。把远端上报的 MCP 工具动态映射为 in-process SDK 工具，由模型直接选择工具与参数；通过 `can_use_tool` 实现 Human-in-the-loop；通过 `PostToolUse` hook 审查上位机返回结果；以 SSE 事件向前端流式推送 agent trace；支持 Skill 装载。

### Modified Capabilities
- `anthropic-llm-config`：调用方扩展到 `DeviceAgent`。新增要求：`build_options` 必须支持 `can_use_tool` callback 与 hooks 配置注入；新增"对话场景"的默认 `permission_mode` 推荐值（`"default"`，以便走 `can_use_tool` 审核）。

（`SUPPORTED_AGENTS` 注册表的扩展 / admin Agent 下拉新增 `device_agent` 记入 `device-agent` 自身 spec 的"Skill 装载"要求中，不单独建 `agent-skills` capability。）

## Impact

- **代码删除**：`app/agents/chat_agent.py`、`app/agents/tools/device_prompt_tool.py`、`app/agents/tools/__init__.py`；`app/services/ai_chat_service.py` 中 LangChain 相关分支；`app/services/runtime_settings_service.py` 中"主力模型"覆盖逻辑（保留其他 runtime settings）；`app/api/admin.py` 中"主力模型"端点；`app/prompts/prompts_config.yaml` 中旧 ChatAgent 提示词；前端 `frontend/src/views/AdminModelSettings.vue` 中主力模型表单与 `frontend/src/api/admin.ts` 中对应方法。
- **新增代码**：`app/agents/device_agent/{__init__.py,agent.py,mcp_tools.py,prompts.py,workspace.py,trace.py,permissions.py}`、`app/services/ai_chat_service.py` 重写、`app/api/chat.py` 中新增 `POST /chat/permissions/{request_id}/resolve` 与 SSE 事件扩展、前端 `frontend/src/views/AIChat.vue` 接收新 SSE 事件 + 渲染权限确认对话框 / agent trace 步骤、`AdminAgentSkills.vue` 下拉新增条目、`tests/agents/test_device_agent.py` 等。
- **配置**：删除 `openai_api_key`、`openai_base_url`、`deepseek_*`、`llm_model_name` 与 admin 页"主力模型"运行时覆盖；`ANTHROPIC_*` 字段成为对话 / 日志分析两条路径共用配置；`.env.example` 同步更新。
- **依赖**：`requirements.txt` 移除 ChatAgent 独占的 LangChain/LangGraph 包；`claude-agent-sdk` 在 Log Analysis 变更里已添加，本变更不再新增依赖。
- **API/契约**：`POST /chat` / `POST /chat/stream` 路径与基础字段（`session_id` / `message` / `target_device_id`）不变；新增 SSE 事件类型与 `POST /chat/permissions/{request_id}/resolve`；admin "Model Settings" 移除"主力模型"区域，保留 Anthropic provider 只读视图。
- **数据库**：`chat_message` / `chat_session` 表保持不变（仍写 `role` / `content`）；不引入新表。
- **运维**：FastAPI worker 需要可访问 `api.anthropic.com`（或 DeepSeek 兼容端点）；Skill 包存储路径与 Log Analysis 共用 `data/agent_skills/`；DeviceLinkManager 维持现有 WS/HTTP 通道，本变更不改设备通信协议。
- **未迁移项**：上位机侧 AI Helper（实际执行 MCP 调用的客户端）不在本变更范围；上位机仍按 device_link 投递的 `PromptEnvelope` 进行解析，只是 `prompt` 字段从"协议化文本"改成"调用 `<server>.<tool>` 的结构化指令"，详见 design.md 的 envelope schema。
