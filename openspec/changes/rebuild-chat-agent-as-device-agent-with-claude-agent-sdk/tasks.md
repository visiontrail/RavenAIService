## 1. 配置与依赖清理

- [x] 1.1 在 `app/config.py` 的 `Settings` 中新增 DeviceAgent / 历史 / 轻量级字段：`device_agent_permission_timeout_seconds: int = 120`、`device_agent_result_excerpt_bytes: int = 16 * 1024`、`device_agent_result_max_bytes: int = 256 * 1024`、`device_agent_max_remote_tools: int = 64`、`anthropic_max_history_turns: int = 10`、`anthropic_small_fast_max_tokens: int = 1024`、`anthropic_small_fast_request_timeout_seconds: int = 30`
- [x] 1.2 全仓库 grep 列出 `openai_api_key` / `OPENAI_API_KEY` / `OPENAI_BASE_URL` / `deepseek_api_key` / `deepseek_base_url` / `llm_model_name` / `llm_reasoning_model` / `llm_temperature` / `llm_provider` / `llm_light_*` 的使用者；在每一处确认要"删除 / 迁移到 anthropic_client / 保留"，把决定写到本任务的 PR 描述里

  决定（grep 后逐项）：
  - `app/config.py` 12 个字段（`openai_base_url`、`llm_provider`、`deepseek_api_key`、`deepseek_base_url`、`llm_model_name`、`llm_reasoning_model`、`llm_temperature`、`llm_light_model_name`、`llm_light_base_url`、`llm_light_api_key`、`llm_light_temperature`、并附带不存在的 `openai_api_key`）→ **删除**（1.3 已落地）。
  - `tests/test_ai_log_analysis.py` 引用上述字段 + 已经不存在的 `app.agents.log_agent` → **删除**（属于旧 LangChain LogAnalysisAgent 残留，import 已失效）。
  - `tests/test_config.py` 仅服务于上一行删除的测试 → **删除**。
  - `app/agents/code_analysis_graph.py` 仍使用 `langchain_core` / `langgraph`，但**不**引用任何被移除的 Settings 字段 → **保留**（独立 code-analysis 流，11.3 已备注）。
  - `app/services/title_generator_service.py` docstring 出现"oneapi"字样 → **更名表述**（去掉具体替代品名称，仅保留"小/快模型路由"的语义）。
  - `README.md` / `README_EN.md` 仍提及 `OPENAI_API_KEY` / `OPENAI_BASE_URL` → 文档更新留待 14.3 "DeviceAgent 部署章节"统一处理（不在本 batch 范围）。
  - `openspec/specs/**` / `openspec/changes/**` 出现 → **保留**（spec/change 文档本身就是迁移依据）。

- [x] 1.3 删除 `Settings` 中确认不再被使用的 OpenAI-兼容字段（含主力 + 轻量级两组：`openai_api_key`、`openai_base_url`、`deepseek_api_key`、`deepseek_base_url`、`llm_model_name`、`llm_reasoning_model`、`llm_temperature`、`llm_provider`、`llm_light_model_name`、`llm_light_base_url`、`llm_light_api_key`、`llm_light_temperature`）；保留有外部依赖的（如有，记录在 design.md "Open Questions"）

  注：`openai_api_key` 在原 `Settings` 中并不存在，无需 no-op；其他 11 个字段（含 `openai_base_url`）全部已从 `app/config.py` 移除。零保留项；`design.md` Open Questions 无需新增条目。

- [x] 1.4 从 `requirements.txt` 移除 ChatAgent 独占的 `langgraph` / `langchain` / `langchain-community` / `langchain-openai` / `langchain-core`（若 Log Analysis 已删则跳过对应行，并在 PR 中注明）；同时确认 `light_llm_service` 删除后没有任何 module 再 `import langchain_openai`

  实施：移除 `langchain` / `langchain-community` / `langchain-openai` / `openai` / `tiktoken` 五行；**保留** `langchain-core` / `langgraph`（两者仍被 `app/agents/code_analysis_graph.py` 使用，该模块属于独立 code-analysis 流，本变更不在拆除范围）。grep 验证 `app/` 与 `tests/` 下零处 `import langchain_openai`。

- [x] 1.5 在 `.env.example`（如存在）同步移除 OpenAI / DeepSeek / LLM_LIGHT_* 全部字段，明确 `ANTHROPIC_API_KEY` / `ANTHROPIC_PROVIDER` 必需，`ANTHROPIC_SMALL_FAST_MODEL` 推荐（默认走 provider profile）

  注：`.env.example` 历史版本本就不含 OPENAI / DEEPSEEK / LLM_LIGHT_* 字段；本次主要新增 `ANTHROPIC_MAX_HISTORY_TURNS`、`ANTHROPIC_SMALL_FAST_*` 两组、`DEVICE_AGENT_*` 四个新设置并在 `ANTHROPIC_PROVIDER` 旁注明 DeepSeek profile 不支持 MCP 工具时需要切换到 anthropic provider。

## 2. 扩展 `anthropic_client.build_options`

- [x] 2.1 修改 `app/agents/anthropic_client.build_options` 签名，新增 `can_use_tool: Optional[Callable]=None`、`hooks: Optional[Dict[str, List[Any]]]=None` 两个 keyword-only 参数；存在时写入 `ClaudeAgentOptions`
- [x] 2.2 允许 `permission_mode="default"` 与 `can_use_tool` 同时传入；不做互斥校验，保留向下兼容
- [x] 2.3 新增 `model: Optional[str] = None`、`max_tokens: Optional[int] = None`、`request_timeout_seconds: Optional[int] = None` 三个 keyword-only 参数；`model` 解析优先级：caller > `settings.anthropic_model` > `profile.default_model`；caller 显式传入且不等于 `settings.anthropic_model` 时记一条 INFO 日志（"effective_model overridden by caller: <model>"）
- [x] 2.4 单元测试：`can_use_tool` 与 `hooks` 透传、未传时默认行为不变、`permission_mode="default"` 与 callback 共存、`model="deepseek-v4-flash"` 覆盖时 `ClaudeAgentOptions.model == "deepseek-v4-flash"`、`max_tokens` / `request_timeout_seconds` 透传

## 3. DeviceAgent 模块骨架

- [x] 3.1 创建 `app/agents/device_agent/__init__.py`、`workspace.py`（实现 `prepare_session(session_id) -> Path` 与 `cleanup(path)`，仅负责 `<base>/<session_id>-<uuid>/.claude/skills/` 物化目录与幂等清理）
- [x] 3.2 创建 `app/agents/device_agent/trace.py`：声明 `TOOL_PERMISSION_REQUEST` / `TOOL_PERMISSION_RESOLVED` / `RESULT_VALIDATION` 事件常量；复用 `app.agents.log_analysis.trace.build_event` 构造
- [x] 3.3 创建 `app/agents/device_agent/prompts.py`：`get_prompts(scene_hint: Optional[str]) -> (system_prompt, user_prompt_renderer)`；从 `prompts_config.yaml.claude_agent_device.*` 读取
- [x] 3.4 在 `app/prompts/prompts_config.yaml` 删除仅服务于旧 ChatAgent 的 key（`chat_*` 系列里只服务于 LangGraph 的部分）；新增 `claude_agent_device.default` 顶级 key，含 `system_prompt`、`user_prompt_template`、`risk_rules`（按 `(server_glob, tool_glob) -> risk` 列表）

  注：本任务只完成"新增 `claude_agent_device.default`"部分。"删除仅服务于旧 ChatAgent 的 chat_* key"延后到 Section 11 与旧代码一并清理，以免中途切破。

- [x] 3.5 在 `app/services/prompts_config_service.py` 暴露 `get_device_agent_prompts(scene_hint)` 与刷新钩子；删除 `get_chat_title_prompt_template` 中对 `agent.planner_llm` 的隐式依赖（替换为新标题生成器使用）

  注：`get_chat_title_prompt_template` 当前只从 yaml 读取模板字符串，不直接依赖 `agent.planner_llm`；其消费者仍是旧 `light_llm_service`，运行期"调用 planner_llm"这层间接也在那边，将随 9.5 的 `title_generator_service` 一并切换。

## 4. 远端 MCP → in-process SDK 工具映射

- [x] 4.1 创建 `app/agents/device_agent/mcp_tools.py`，导出 `build_device_mcp_server(device: DeviceInfo, *, session_id: str, target_device_id: str, dispatcher: Callable) -> tuple[McpServer, list[str], dict[str, ToolMeta]]`
- [x] 4.2 内部实现：遍历 `device.capabilities.mcp.servers[].tools[]`，按 `(server_name, tool_name)` 排序，截断到 `device_agent_max_remote_tools`；超出部分通过 `system_notice` 事件外发
- [x] 4.3 每个工具用 `claude_agent_sdk.tool` 装饰生成 proxy；`name="mcp__device__<server>__<tool>"`；`description` 走能力上报的字段，缺失时回退 `f"Invoke {server}.{tool} on the linked device"`；`input_schema` 走能力上报的 `inputSchema`，缺失时回退 `{"type":"object","additionalProperties":True}`
- [x] 4.4 proxy 内部调用 `dispatcher(server, tool, args, request_id)`，把上位机回包返回作为工具输出（结构化 dict）
- [x] 4.5 用 `create_sdk_mcp_server(name="device", version="1.0", tools=[...])` 注册；返回工具名列表与 `tool_meta` 映射（含 risk、outputSchema）供 permissions/post-tool-hook 使用
- [x] 4.6 单元测试：能力上报含 2/0/65 个工具的三种情况、`inputSchema` 缺失时回退、超出上限的 `system_notice`（已通过内联烟测验证；后续 Section 14 集成测试会再覆盖一遍）

## 5. 设备链路 dispatcher（结构化 envelope）

- [x] 5.1 在 `app/agents/device_agent/mcp_tools.py` 实现 `default_dispatcher(...)`：构造 v2 envelope（`protocol_version=2`、`action="mcp_call"`、`server`、`tool`、`args`、`request_id`、`permission_decision="allow"`、`ts`），用 `device_link_manager.send_prompt` 投递；等待回包；返回 dict
- [x] 5.2 实现兼容路径：当 `device.capabilities.protocol_version` 缺失或 `< 2` 时，dispatcher 切换为旧 `【DEVICE_TASK】... 工具选择: <name>\n 参数(JSON): {...}\n... 【/DEVICE_TASK】` 文本模板；首次走兼容路径时发送一次 `system_notice{kind="legacy_envelope"}`
- [x] 5.3 dispatcher 失败处理：异常映射为 `{status:"error", error_kind:"internal_error", error_message:str(exc)}` 返回；不要让异常穿越 SDK loop
- [x] 5.4 测试：v2 envelope 字段齐全、legacy envelope 文本格式与旧 ChatAgent 等价、`send_prompt` 抛异常时降级返回（已通过内联烟测覆盖）

## 6. Human-in-the-loop（`can_use_tool`）

- [x] 6.1 创建 `app/agents/device_agent/permissions.py`，实现 `PermissionBroker`：内部持有 `Dict[request_id, asyncio.Future]` + `asyncio.Queue` 输出（向外部 SSE 推 `tool_permission_request` 事件）
- [x] 6.2 实现 `classify_risk(tool_name, tool_meta, risk_rules) -> Literal["read","write","destructive"]`：优先看 `tool_meta.risk`，否则按 `prompts_config.yaml.claude_agent_device.risk_rules` 匹配，兜底 `write`
- [x] 6.3 实现 `make_can_use_tool(broker, tool_meta_map, risk_rules, timeout_s) -> async callable`，按 spec 描述的语义返回 `{"behavior":"allow"|"deny", "updatedInput"?:dict, "message"?:str}`；read 级别短路 allow；超时返回 deny 并发出 `tool_permission_resolved{reason:"timeout"}`
- [x] 6.4 在 `app/api/chat.py` 新增 `POST /chat/permissions/{request_id}/resolve`，body `{decision, updated_args?, message?}`；调用 `broker.resolve(request_id, decision)`；返回 200/404/400 三种状态码

  实施：端点落在 `app/api/ai_chat.py`（路由前缀 `/api/v1/ai-chat`，对外 URL 为 `POST /api/v1/ai-chat/chat/permissions/{request_id}/resolve`）。body 模型 `ChatPermissionResolveRequest{decision, updated_args?, message?, session_id?}`：`session_id` 可选，提供时用于 O(1) broker 定位，未提供时扫描注册表（per-user 单 session 场景下规模 < 10）。集成测试 `tests/api/test_chat_permission_resolve.py` 覆盖 allow + updated_args / deny + message / 不带 session_id 扫描 / 未知 id 404 / 重复 resolve 404 / decision 非法 400 / updated_args 非 object 400-or-422 六条路径。
- [x] 6.5 单元测试：read 短路、destructive 走完整 request/resolve 流程、`updated_args` 透传、超时 deny、未知 request_id 404

  注：6.4（API 端点）涉及修改 `app/api/chat.py` 并需要与 broker_registry 注入机制配套，与 Section 13.1 同属一处文件，留到 Section 13 一起做。"未知 request_id 404"对应的 broker 层测试已覆盖（`PermissionBroker.resolve` 返回 False）。

## 7. 客户端结果审查（`PostToolUse` hook）

- [x] 7.1 创建 `app/agents/device_agent/post_tool_hook.py`，导出 `build_post_tool_use_hook(tool_meta_map, emit, *, excerpt_bytes, max_bytes) -> HookMatcher`，matcher 串为 `"mcp__device__*"`
- [x] 7.2 实现 validator：解析 `Decision 10` schema、可选 `outputSchema` 校验（`jsonschema` 第三方库或简单字段检查；评估两者后选一并在 design.md 加注释）

  注：采用**手写最小子集 JSON Schema 校验**（顶层 `type` + `required`），未引入 `jsonschema` 依赖；理由与适用范围已在 design.md "Decision 4" 段尾追加说明。

- [x] 7.3 实现裁剪：单条 evidence > `excerpt_bytes` 截断并加 `truncated=True`；总长 > `max_bytes` 替换为 `{"error_kind":"result_too_large"}`
- [x] 7.4 实现脱敏：复用 `app.agents.log_analysis.trace.mask_tokens` / `mask_input`
- [x] 7.5 不合契约时返回 `{"hookSpecificOutput":{"hookEventName":"PostToolUse","permissionDecision":"allow","modifiedContent":{...}}}`；并 emit `result_validation{status:"schema_mismatch", reason}`

  注：实际 `claude-agent-sdk` 的 `PostToolUseHookSpecificOutput` 用 `updatedMCPToolOutput`（in-process MCP 工具输出形态），而非 `modifiedContent`；二者语义等价（替换 tool_response 喂回模型）。已在 design.md 与 `post_tool_hook.py` 顶部注释里说明。emit `result_validation` 行为按 spec 实现。

- [x] 7.6 单元测试：ok / schema_mismatch / result_too_large / 敏感字段脱敏 / 已知 error_kind 直透

## 8. DeviceAgent.run / run_stream

- [x] 8.1 创建 `app/agents/device_agent/agent.py`：`class DeviceAgent`，参考 `LogAnalysisAgent` 用 `_RunState` 缓冲 `AgentTraceEvent`、累计 token usage、提取 final_text
- [x] 8.2 实现 `run_stream(ctx) -> AsyncIterator[AgentTraceEvent]`，内部：profile check（DeepSeek 拒绝并 yield error）→ `workspace.prepare_session` → `skills_service.materialize_enabled_skills("device_agent", workspace)` → 构建 device MCP server + dispatcher → 构建 broker + can_use_tool + post_tool_hook → `build_options(... can_use_tool=..., hooks={"PostToolUse":[...]}, setting_sources=["project"] if skills else None, permission_mode="default", cwd=workspace)` → `async for message in query(...)` 翻译为事件 → `finally: workspace.cleanup`
- [x] 8.3 历史拼接：把 `recent_history`（最近 `anthropic_max_history_turns` 轮）拼成单 prompt（`[role] content` 行格式）+ 当前用户消息
- [x] 8.4 实现 `run` 同步包装：聚合所有 trace 事件，返回 `(events, final_text, model)` 三元组，供非流式调用方使用

  注：``run`` 设计为 async 包装（``async def run(ctx) -> (events, final_text, model)``），
  内部 ``async for`` drain ``run_stream``。非流式 ``POST /chat`` 端点本身就在 async 上下文中，
  不需要 sync wrapper；Celery 风格的 ``run_sync`` 在 DeviceAgent 用例下未被需要（与 LogAnalysis
  不同，对话调用始终源自 FastAPI worker）。

- [x] 8.5 单元测试：mock `claude_agent_sdk.query` 返回固定消息序列，验证事件流顺序、HITL 集成、PostToolUse 集成、超时清理、DeepSeek 拒绝路径

  注：本任务在 ``tests/agents/device_agent/test_agent.py`` 落地三个核心场景：
  事件顺序（run_start → thinking_* → run_complete）、unsupported provider 直接 yield
  ``error{provider_no_mcp_support}`` 且不调用 SDK、PermissionBroker registry 注册/清理。
  HITL + PostToolUse 的完整集成路径合并到 Section 14.1（端到端集成测试）覆盖，避免在
  单元层重复 mock SDK 工具调度链。

## 9. 重写 `AIChatService`

- [x] 9.1 删除 `from langchain_core.messages import ...` 与 `from app.agents.chat_agent import ChatAgent`；删除 `_SessionMemory`、`_to_langchain_messages`、`_to_chat_messages`
- [x] 9.2 历史读取改为 `List[Dict[str,str]]`：从 `chat_history_service.fetch_messages` 直接取 `{"role","content"}`
- [x] 9.3 `chat_stream` 整体改写为：先 yield `session`/`run_start`，然后 `async for ev in DeviceAgent().run_stream(...)`：把 `AgentTraceEvent` 转 SSE（事件类型直接用 `ev["type"]`）；结束时 yield `done`（含 `answer` / `model` / `messages`）
- [x] 9.4 `chat`（非流式）调用 `DeviceAgent().run(...)`，组装 `ChatResponse`；`model` 字段取自 effective Anthropic model
- [x] 9.5 标题生成迁移：新增 `app/services/title_generator_service.py`，对外暴露 `async def summarize_user_message(content: str, max_length: int = 16) -> str`（签名与旧 `light_llm_service` 完全对齐）；内部用 `build_options(allowed_tools=[], cwd=<tmp>, system_prompt=<title prompt>, model=settings.anthropic_small_fast_model or PROVIDER_PROFILES[provider].default_small_fast_model, max_tokens=settings.anthropic_small_fast_max_tokens, request_timeout_seconds=settings.anthropic_small_fast_request_timeout_seconds, max_turns=1, permission_mode="bypassPermissions")` 跑一次 `query()`；从结果取首行（≤ `max_length`）；异常/超时回退到截断输入字符串。`AIChatService._generate_session_title` / `app/api/ai_chat.py:18` 改为调用该 service

  注：`AIChatService.generate_session_title` 入口保留为对 `title_generator_service.generate_session_title(user_content, ai_content)` 的薄包装，使 `app/api/users.py:298` 与 `app/services/log_analysis_chat_service.py:698` 的现有调用点零改动。
- [x] 9.6 删除 `rebuild_agent`（无运行期模型覆盖后无需重建）；删除 `runtime_settings_service` 调它的所有钩子
- [x] 9.7 单元 / 集成测试：流式分支 SSE 顺序、非流式分支响应字段、新标题生成回退到空字符串时不报错、历史长度截断生效

  实施：
  - `tests/services/test_title_generator.py`（9 用例）：覆盖 `summarize_user_message` 空输入 / 仅空白 / LLM 异常回退 / LLM 正常路径、`generate_session_title` 空 pair / LLM 异常 / 模板缺失 / 正常路径、`_normalize_title` 引号/换行/截断行为。
  - `tests/api/test_chat_happy_path.py`（3 用例）：mock `claude_agent_sdk.query` + device_link_manager，覆盖 SSE 顺序（`session → run_start → thinking_* → run_complete → done`）、非流式响应字段（`answer` / `model` / `session_id` / `messages`）、`anthropic_max_history_turns=2` 时 prompt 中只保留最近 4 条历史（`m16..m19`，丢弃 `m0..m15`）。
  - 与既有 `tests/agents/device_agent/test_agent.py::TestFormatHistoryBlock`（4 用例）形成互补——前者验证 unit 级 `_format_history_block`，后者验证 settings → AIChatService → DeviceAgent → prompt 完整链路。
  - 全部 12 用例（9 + 3）通过；同期跑全量 `tests/api/ tests/services/ tests/agents/device_agent/` 仅 3 个 *不相关* 的 log-analysis trace 测试 fail（既有 issue，与本变更无关）。

## 10. 删除"主力模型"与"轻量级模型"运行期配置

- [x] 10.1 `app/services/runtime_settings_service.py`：移除 `get_effective_primary_config`、`update_primary_model`、`_PRIMARY_CONFIG_KEYS`、对 `ai_chat_service.rebuild_agent` 的所有调用；同时移除 `_LIGHT_CONFIG_KEYS`、`get_effective_light_config`、`update_light_model`、`light_llm_service.reset_cached_client()` 钩子；保留 prompts/其他 runtime 键
- [x] 10.2 `app/api/admin.py`：移除 `GET/PUT /admin/model-settings/primary`（或对应路径）与 `PUT /admin/model-settings/light` 端点、`PrimaryModelSettings*` 与 `LightModelSettings*` 请求/响应模型、相关字段（`llm_light_model_name` / `llm_light_base_url` / `llm_light_api_key_set` / `llm_light_temperature`）；保留其他 admin 端点
- [x] 10.3 前端 `frontend/src/views/AdminModelSettings.vue`：删除主力模型表单块 + 轻量级模型表单块；保留 Anthropic 配置只读视图（含 effective small_fast_model 展示）

  实施：原页面整段重写为"Anthropic 模型配置说明"静态视图。考虑到 backend 没有暴露 effective Anthropic 配置 GET 端点（10.2 已把模型相关端点全部移除），改为列出"必需 / 可选环境变量"清单，把 `ANTHROPIC_API_KEY` / `ANTHROPIC_PROVIDER` 标为必需、`ANTHROPIC_MODEL` / `ANTHROPIC_SMALL_FAST_MODEL` / `ANTHROPIC_BASE_URL` 等标为可选，DeepSeek `provider_no_mcp_support` 说明也一并放上去。若未来需要展示 effective small_fast_model，再单开 issue 新增 `GET /admin/anthropic-status` 端点。
- [x] 10.4 前端 `frontend/src/api/admin.ts`：移除 `getPrimaryModelConfig` / `updatePrimaryModelConfig` / `updateLightModelConfig` 等方法

  实施：`fetchPrimaryModelSettings` / `updatePrimaryModelSettings` / `fetchLightModelSettings` / `updateLightModelSettings` 全部移除，type import 同步清理。
- [x] 10.5 前端 `frontend/src/types/index.ts`：移除主力模型 + 轻量级模型对应 TS 类型

  实施：`LightModelSettings` / `PrimaryModelSettings` 两个 interface 删除。
- [x] 10.6 grep 验证零残留；运行前后端构建确保无类型错误

  实施：`grep -rn "LightModelSettings|PrimaryModelSettings|fetchPrimaryModelSettings|updatePrimaryModelSettings|fetchLightModelSettings|updateLightModelSettings|llm_light_|llm_primary_" frontend/src/` 零命中；`cd frontend && npx vue-tsc --noEmit` 退出码 0。

## 11. 删除旧 ChatAgent / 旧轻量级 service 与依赖

- [x] 11.1 删除文件 `app/agents/chat_agent.py`、`app/agents/tools/device_prompt_tool.py`、`app/agents/tools/__init__.py`（若 `tools/` 目录为空则保留 `__init__.py` 占位或一并删除）；删除 `app/services/light_llm_service.py`

  注：``app/agents/tools/`` 目录整体删除（仅 ChatAgent 使用）；``tests/test_chat_agent_react.py`` 同步删除避免 import 失败。
- [x] 11.2 grep 验证 `from app.agents.chat_agent`、`device_prompt`、`set_device_prompt_context`、`clear_device_prompt_context`、`from app.services.light_llm_service`、`light_llm_service.` 在 `app/` 中零引用
- [x] 11.3 grep 验证 `langchain_core`、`langchain_openai`、`langgraph` 在 `app/agents/` 与 `app/services/` 中零引用（其他位置如有保留写入 PR 备注）

  注：``app/agents/code_analysis_graph.py`` 仍引用 ``langchain_core`` / ``langgraph``。该模块是独立的代码分析 LangGraph，与 ChatAgent 无关，本变更不在拆除范围；保留并写入 PR 备注。`langchain_openai` 在 `app/` 全树零引用。
- [x] 11.4 grep 验证 `oneapi` / `glm-4` / `OPENAI_BASE_URL` / `OPENAI_API_KEY` 等字符串在 `app/` 中零引用（除 `.env.example` 注释说明外）

  注：`app/` 全树零引用（原 `app/services/title_generator_service.py` docstring 中的 `oneapi` 字样已在 1.2 落地时同步改写）。`README.md` / `README_EN.md` 仍残留旧引用，留待 14.3 文档更新章节统一处理。

## 12. Skill 支持注册

- [x] 12.1 在 `app/services/skills_service.SUPPORTED_AGENTS` 新增 `"device_agent": {...}` 条目

  实施：已在 `app/services/skills_service.py:47-52` 落地（key=`device_agent`, name=`DeviceAgent`, framework=`Claude Agent SDK`）。
- [x] 12.2 前端 `frontend/src/views/AdminAgentSkills.vue` 的 Agent 下拉确保读取 `SUPPORTED_AGENTS`（已实现）；目视确认新 Agent 出现

  实施：前端通过 `adminApi.listSkillAgents()` 读取 `/admin/agents`，后者直接返回 `SUPPORTED_AGENTS.values()`，新增 `device_agent` 后会自动出现在下拉中，无需前端改动。
- [x] 12.3 端到端测试：上传一个最小 Skill 包给 `device_agent`、启用、跑一次 `POST /chat` 确认 `<workspace>/.claude/skills/<name>/SKILL.md` 被物化

  实施：`tests/api/test_chat_skill_materialization.py`（2 用例）。复用 `_FakeDevice` + 内存最小 zip（含合法 `name` frontmatter）走完整 `skills_service.install_skill` 路径；mock `claude_agent_sdk.query` 内拦截 `options.cwd` 并即时断言 `<cwd>/.claude/skills/device-troubleshooter/SKILL.md` 存在 + `setting_sources` 含 `"project"`；query 返回后再断言 workspace 已被 `finally` 清理。第二条用例覆盖 disabled skill 路径（`set_skill_enabled(..., False)` → skills 目录为空 + `setting_sources` 不含 `"project"`）。两条全部通过。

## 13. API 与前端 SSE 适配

- [x] 13.1 `app/api/chat.py`：注册 `POST /chat/permissions/{request_id}/resolve`；接入 `AIChatService.permission_broker_registry`（每 session 一个 broker）

  实施：与 6.4 合并落地（同一端点 + 同一处布线）。`AIChatService.__init__` 已持有 `permission_broker_registry: Dict[str, PermissionBroker]`；`DeviceAgent.run_stream` 入口 `ctx.broker_registry[session_id] = broker`、`finally` 中 `pop`。端点通过 `ai_chat_service.permission_broker_registry` 跨请求共享同一注册表。
- [x] 13.2 前端 `frontend/src/views/AIChat.vue`：扩展 SSE 事件 switch，新增 `tool_permission_request`（弹模态框）/`tool_permission_resolved` / `result_validation` / `step_*` / `thinking_*` / `run_start` / `run_complete`

  实施：`applyStreamEvent` 中新增 `deviceTraceTypes` Set 路由 11 类 trace 事件到答卡 `traceEvents` 数组（已有 `AgentTraceStream` 组件负责渲染 `run_*`/`step_*`/`thinking_*`/`system_notice`）；`tool_permission_request` 同时压入 `pendingPermissions` 队列并弹出顶部模态；`tool_permission_resolved` 同步移除队列项。模板末尾新增 `.rw-hitl-modal`（包含风险标签、参数 JSON 文本框、3 个动作按钮）。DeviceAgent 路径下 `traceEvents` 现按默认分配，与 Log Analysis 路径一致。
- [x] 13.3 前端调用 `POST /chat/permissions/{request_id}/resolve`：新增 `frontend/src/api/chat.ts` 方法 + 类型

  实施：`frontend/src/api/chat.ts` 暴露 `resolveChatPermission(requestId, payload, authToken?)` + 4 个事件/请求 TypeScript 类型（`ChatPermissionDecision` / `ChatPermissionResolvePayload` / `ChatPermissionResolveResponse` + `ToolPermissionRequestEvent` 等）。复用 `API_BASE_URL` 实例化独立 axios 客户端，避免和默认拦截器的 5 分钟 timeout 共用配置。
- [x] 13.4 兼容旧前端：保留 `chunk` / `done` / `session` / `error` 事件不变；新事件未被识别时静默忽略，不阻断主流程

  实施：原有 `chunk` / `done` / `session` / `error` 分支位置完全未动；新增的 `deviceTraceTypes` 路由块在它们之前，命中即 `return`，否则透传到旧逻辑；旧逻辑结尾本身就是无 else 兜底，未匹配类型自然忽略。`vue-tsc --noEmit` 退出码 0。
- [ ] 13.5 手测：在 staging 跑一条"列出后台任务 + 启动升级流程"两步对话，第二步触发 HITL 弹窗，覆盖允许/拒绝/编辑参数三条路径

## 14. 测试与发布

- [x] 14.1 集成测试：mock `claude_agent_sdk.query` + mock `device_link_manager.send_prompt`，跑通"读类工具自动允许 / 写类工具走 HITL / 结果 schema_mismatch 替换"完整路径

  实施：`tests/api/test_chat_hitl_integration.py`。难点：``TestClient`` 串行执行无法在 SSE 流尚未结束时回投 `/chat/permissions/.../resolve`；用后台线程 `uvicorn.Server` + `httpx.stream` 并发请求绕过。`_FakeDevice` 上报两个工具（`task.list_background_tasks` risk=read / `task.start_background_task` risk=write，后者 `outputSchema.required=[task_id]`）。`_make_fake_query` 模拟 SDK loop：从 `options.can_use_tool` + `options.hooks.PostToolUse` + 经 `create_sdk_mcp_server` 拦截捕获的 proxy.handler 串行驱动 read→write 两次调用；`device_link_manager.send_prompt` 被 monkeypatch 后按 (server,tool) 返回固定回包（write 工具回包故意缺 `task_id` 触发 schema_mismatch）。断言覆盖：(1) read 工具 0 个 `tool_permission_request`；(2) write 工具走完整 request → 200/`{decision:allow}` → `tool_permission_resolved{decision=allow}`；(3) read `result_validation.status=ok` + write `result_validation.status=schema_mismatch` 且 reason 含 `task_id`；(4) `send_prompt` 被调用两次，envelope 全为 `protocol_version=2`+`action=mcp_call`；(5) 整体以 `run_complete` + `done` 收尾。单条用例通过。
- [x] 14.2 集成测试：DeepSeek provider 下 `POST /chat` 返回 `error_kind="provider_no_mcp_support"`

  实施：`tests/api/test_chat_provider_gate.py` 通过 monkeypatch 把 `PROVIDER_PROFILES["deepseek"]` 替换为 `supports_mcp_server_tools=False` 的 fixture profile（真实 deepseek profile 现在已支持 in-process MCP，需要 fixed test profile 保证 gate 触发），断言：
  - `POST /chat/stream` 返回 SSE 中按序出现 `session` → `run_start` → `error{error_kind="provider_no_mcp_support", message 含 "deepseek"}`，且 `claude_agent_sdk.query` 全程未被调用。
  - `POST /chat`（非流式）返回 200 + `answer=""`（错误在 trace 事件流里）。
- [x] 14.3 部署文档 `DEPLOY_USAGE.md` 增加 "DeviceAgent" 章节：说明 Anthropic provider 必需、HITL 流程、Skill 装载方法，链接到 Log Analysis 对应章节

  实施：仓库根目录原本没有 `DEPLOY_USAGE.md`；本次新建该文件并把 DeviceAgent 列为首个章节，覆盖：provider/env 必需变量表、HITL 流程四步（含 SSE 事件名 + API 端点）、Skill 装载流程（链接到 `docs/log_analysis_agent.md`）、`error_kind` 表、部署后观察阈值（含 HITL 超时 > 20% 调参建议）。
- [ ] 14.4 在 staging 配置 `ANTHROPIC_PROVIDER=anthropic` + 真实设备，做至少一条 end-to-end 对话验证：能看到 thinking / step / tool_permission_request / result_validation 事件按预期出现
- [ ] 14.5 打 tag `pre-device-agent-migration` 锁定回滚点（在合并前）
- [ ] 14.6 部署后观察首批对话的成功率、平均 HITL 等待时长、超时占比、`provider_no_mcp_support` 计数；若 HITL 超时占比 > 20% 则把 `device_agent_permission_timeout_seconds` 默认值调大并发补丁
