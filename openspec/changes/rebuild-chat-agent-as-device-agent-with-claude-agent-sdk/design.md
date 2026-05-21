## Context

`app/agents/chat_agent.py`（`ChatAgent`，1900+ 行）以 LangGraph 实现 Plan→Act→Observe→Decide 状态机，通过 `langchain_openai.ChatOpenAI`（指向 `OPENAI_API_KEY` / `OPENAI_BASE_URL` / `llm_model_name`，由 admin "Model Settings" 页面运行期覆盖）调用模型。它对外只暴露一个 LangChain `@tool` —— `device_prompt`：把"`【DEVICE_TASK】... 工具选择: <name>\n 参数(JSON): {...}\n... 【/DEVICE_TASK】`"协议化文本通过 `device_link_manager.send_prompt` 投递到上位机，由上位机 AI Helper 二次解析后再去调用真正的设备 MCP 工具。模型并不真正"使用工具"，只是写一段约定文本；MCP 能力以 `device_capabilities_prompt`（自由文本）出现在 system prompt 里。

Log Analysis Agent（`app/agents/log_analysis/`）在前一次变更里已经全量迁移到 Claude Agent SDK：用 `app/agents/anthropic_client.build_options(...)` 构造 `ClaudeAgentOptions`、`async for message in query(...)` 驱动 agent loop、用 `@tool` + `create_sdk_mcp_server` 暴露 `lookup_project_repo` in-process MCP 工具、通过 `app/services/skills_service.materialize_enabled_skills("log_analysis", cwd)` + `setting_sources=["project"]` 装载 Skill、通过 `app/agents/log_analysis/trace.py` 的 `_RunState` 把 SDK 消息翻译成 `AgentTraceEvent` 流（`run_start` / `step_*` / `thinking_*` / `run_complete` / `system_notice` / `cancelled` / `error`）。

本变更要把 ChatAgent 整段重写为 **DeviceAgent**，沿用 Log Analysis 的目录布局与运行时骨架，并补齐三个对话场景独有的能力：(1) 远端设备 MCP 工具→in-process SDK 工具的动态映射；(2) Human-in-the-loop 工具审核（via `can_use_tool`）；(3) 客户端结果审查（via `PostToolUse` hook + 输出 schema）。同时彻底拆除"主力模型"运行期覆盖与 `OPENAI_API_KEY` 路径。

约束：
- 设备 MCP 工具集是**逐请求动态**的（不同设备 / 不同时间能力可能不同）；不能在进程启动时一次性建一个全局 SDK MCP server。
- `device_link_manager.send_prompt` 与上位机的传输协议（topic_id 追踪、HTTP/WS、ack 超时）不动；只换"prompt 内容"的形态——从协议化文本换成结构化 JSON。
- 必须保留 `POST /chat` / `POST /chat/stream` 与现有前端 `AIChat.vue` 的会话级语义（`session_id`、历史记录、`remember`、标题生成、`target_device_id` 切换）。
- Skill 包存储路径 / Admin API 与 Log Analysis 共用 `data/agent_skills/`；本变更只在 `SUPPORTED_AGENTS` 注册新 key，不改 admin API。
- 不修改 `chat_session` / `chat_message` 表 schema。
- DeepSeek（`anthropic-llm-config` 默认 provider）`supports_mcp_server_tools=False`：DeviceAgent 在 deepseek 下必须能降级为"只暴露一个聚合 fallback 工具 `device_prompt_legacy`"或拒绝（见 Decision 8）。

## Goals / Non-Goals

**Goals:**
- 用 Claude Agent SDK agent loop 完全替换 LangGraph 版 ChatAgent，整段移除旧实现而非渐进重构。
- 让模型直接选择"设备 MCP 工具+参数"（一次工具调用 = 一次远端 MCP 调用），删除 `device_prompt` 这一层"模型再让模型选工具"的间接。
- 接入 Claude Agent SDK 的 **`can_use_tool`** 实现 Human-in-the-loop：高风险工具弹用户确认后再执行，支持 `allow_with_args_override`。
- 接入 **`PostToolUse` hook** 做客户端结果审查：上位机回包必须满足工具 schema 的 output 契约，不合格者替换为带 `error_kind` 的精简响应再喂回模型。
- 与 Log Analysis Agent 同机制支持 **Skill 装载**（admin 上传 zip → enable → DeviceAgent 自动加载）。
- 复用 Log Analysis 的 trace.py 把 SDK 消息流转换为 `AgentTraceEvent`，前端 SSE 渲染 thinking / step / tool / final answer。
- 删除所有"主力模型"运行期配置；DeviceAgent 与 Log Analysis Agent 共用 `ANTHROPIC_*` 配置族。

**Non-Goals:**
- 不改设备链路传输协议（`PromptEnvelope` 的字段，topic_id 追踪机制，DeviceLinkManager 实现）。
- 不实现上位机侧 AI Helper 的对应变更；本变更只规定 envelope.prompt 的新格式（design.md 后段），上位机一侧由独立 PR 跟进。
- 不引入对话级别的并发工具执行；本期仍保持每轮一个工具调用（沿用 Claude Agent SDK 默认 `disable_parallel_tool_use=True` 的等价语义）。
- 不引入新 DB 表（Skill 存储复用 `data/agent_skills/`，权限请求保存在内存 Future map）。
- 不为 DeviceAgent 单独实现 SSE 取消端点；沿用现有连接断开 = 取消的语义（与 Log Analysis Celery 任务的两阶段 cancel 不同，本期不强制）。

## Decisions

### Decision 1：复用 Claude Agent SDK `query()` 流式 agent loop，不切换到 `ClaudeSDKClient`

**选择**：DeviceAgent 仍走 `async for message in query(prompt=..., options=...)`，每轮请求独立构建一次 options（含本轮的动态 MCP server 与本轮的 hooks/callback）。

**理由**：对话历史在我们这边已经持久化（`chat_message` 表），每次 `chat_stream` 都构造一个新的 `query()` 调用，把历史拼成单个长 user prompt + 当前一条 user 消息。这样：
- 与 Log Analysis Agent 完全对称，复用 `_RunState` / `_emit_for_message` 不改一行（实际只引用，不改 `log_analysis/trace.py`）。
- `can_use_tool` callback 与本次会话强绑定（生命周期自然结束），不会泄漏到下一轮。
- 动态 MCP server 的生命周期也是单 query()，省去多轮会话间的工具注册一致性问题。

**备选**：`ClaudeSDKClient` 多轮会话。被否：SDK 内部历史与我方持久化历史会双轨，对话标题生成 / 重连 / 多端共享会话状态都需要重新设计。

### Decision 2：远端 MCP 工具 → in-process SDK 工具的动态映射

**结构**：每次进入 `DeviceAgent.run` 时：
1. `device = await device_link_manager.get_device(target_device_id)` 拿到 `device.capabilities.mcp.servers[]`。
2. 把所有 `(server_name, tool_name)` 展开成一组 SDK 工具：

```python
@tool(
    name=f"{server_name}__{tool_name}",
    description=remote_tool["description"],
    input_schema=remote_tool["inputSchema"],  # 上位机已按 JSON Schema 上报；缺失时回退 {"type":"object"}
)
async def proxy(args: dict) -> dict:
    return await _dispatch_to_device(
        server_name=server_name,
        tool_name=tool_name,
        args=args,
        session_id=session_id,
        target_device_id=target_device_id,
        request_id=str(uuid.uuid4()),
    )
```

3. 用 `create_sdk_mcp_server(name="device", version="1.0", tools=[...])` 把所有 proxy 装到一个 server 里。
4. `allowed_tools` = `["mcp__device__<server>__<tool>" for ...] + ["Skill"]`（Skill 工具用于让 SDK 自动加载用户上传的 Skill 包；不暴露 Bash/Read/Edit 等内置工具）。

**`_dispatch_to_device` 实现**：构造 `PromptEnvelope`，其中 `prompt` 字段改为结构化 JSON（详见 Decision 9 envelope schema）：
```json
{"action": "mcp_call", "server": "<server>", "tool": "<tool>", "args": {...}, "request_id": "..."}
```
通过 `device_link_manager.send_prompt` 投递，等待上位机回包。回包格式（详见 Decision 10）落到工具返回值。

**理由**：让模型在 SDK 层就看到真实的工具名/参数 schema，能做参数校验、自动重试缺失参数、UI 渲染高亮工具调用。

**备选 A**：保留单一 `device_prompt` 工具，参数 schema 用 `{server, tool, args}`。被否：失去 SDK 的工具自动校验、`can_use_tool` 没法按工具粒度审核、前端 UI 拿不到具体工具名。

**备选 B**：在上位机注册一个真正的 MCP server，让 Claude Agent SDK 直连。被否：上位机网络拓扑（嵌入式设备、内网穿透）使得"SDK 直连设备"不可行；保持服务端反向投递最现实。

### Decision 3：Human-in-the-loop —— `can_use_tool` callback 接入 SSE 双工

**SDK 接口**：Claude Agent SDK 的 `ClaudeAgentOptions.can_use_tool` 接收异步回调 `(tool_name, tool_input, context) -> {"behavior": "allow"|"deny", "updatedInput"?: dict, "message"?: str}`。

**接入点**：
- 每次 `DeviceAgent.run_stream` 创建一个 per-run `PermissionBroker`，里面持有 `asyncio.Queue` 输出（向前端发 `tool_permission_request` SSE 事件）+ `Dict[request_id, asyncio.Future]` 等待端。
- `can_use_tool` 调用时：
  1. 评估风险等级：从工具元数据 `risk`（`"read"` / `"write"` / `"destructive"`）+ 全局规则推断；`read` 默认 allow 直返；其余生成 `request_id`，向 SSE 推 `event=tool_permission_request{request_id, tool_name, args, risk, rationale}`。
  2. `await broker.wait_for_decision(request_id, timeout=settings.device_agent_permission_timeout_seconds)`。
  3. 超时默认 `deny`，原因 `"timeout"`，向 SSE 推 `tool_permission_resolved{request_id, decision: "deny"}`。
- 前端 `AIChat.vue` 收到 `tool_permission_request` 时弹"是否执行 `<tool>(<args>)`？允许 / 拒绝 / 修改参数后允许"对话框；提交时调 `POST /chat/permissions/{request_id}/resolve` 带 `{decision, updated_args?, message?}`；端点把决定塞进 broker 的 Future。

**风险等级来源**（优先级降序）：
1. 工具能力上报里的 `x-risk` / `risk` 字段（如 `"destructive"`）。
2. `prompts_config.yaml` 中 `claude_agent_device.risk_rules`：按 `(server_glob, tool_glob)` 匹配，例如 `*upgrade* / *delete* / *reboot* → destructive`，`*list* / *get* / *status* → read`。
3. 兜底：未匹配的工具按 `"write"` 处理（需要审核）。

**`allow_with_args_override`**：前端允许用户在确认弹窗里编辑 JSON args；提交时 `decision=allow` + `updated_args`；callback 返回 `{"behavior":"allow","updatedInput": updated_args}`。

**理由**：`can_use_tool` 是 Claude Agent SDK 官方推荐的 HITL 接入点，与工具调用完全同步，不会污染对话历史；SSE 单向推 + REST 单向回的组合避免在 FastAPI 里维护 WebSocket。

### Decision 4：客户端结果审查 —— `PostToolUse` hook + 工具 output schema

**SDK 接口**：`ClaudeAgentOptions.hooks={"PostToolUse": [HookMatcher(matcher="mcp__device__*", hooks=[validator])]}`，validator 返回 `{"hookSpecificOutput":{"hookEventName":"PostToolUse","permissionDecision":"allow"|"deny", "permissionDecisionReason"?:str, "modifiedContent"?:str|list}}`。

**Validator 职责**：
1. 解析上位机回包（`result`、`evidence`、`error`、`topic_id`）。
2. 用工具上报的 `outputSchema`（如果有）做 JSON Schema 校验；不合格 → 把 content 替换为 `{"error_kind":"schema_mismatch","raw_excerpt":<截断>}`，并把 `permissionDecision="allow"` + `modifiedContent` 喂回模型；同时向 SSE 推 `system_notice{kind="result_schema_mismatch"}`。
3. 大字段裁剪：单条 `evidence` 超过 `device_agent_result_excerpt_bytes`（默认 16 KiB）截断 + 加 `truncated: true`；`raw` 全文超过 `device_agent_result_max_bytes`（默认 256 KiB）替换为 `error_kind="result_too_large"`。
4. 敏感字段脱敏：复用 `log_analysis/trace.mask_tokens` 与 `mask_input` 对 URL/token 形式做正则脱敏。
5. 上位机 `error` 非空且属于已知 `error_kind`（`device_offline` / `tool_not_found` / `tool_timeout` / `permission_denied` / `internal_error`）→ 不算 schema_mismatch，原样喂回；未知 error_kind 归并为 `internal_error`。

**理由**：把"结果是否能让模型继续推理"的判定从模型本身（容易胡说）下沉到 SDK hook 层（确定性、可测试）。

### Decision 5：Skill 装载与 Log Analysis Agent 同机制

**接入点**：在 `app/services/skills_service.SUPPORTED_AGENTS` 注册：
```python
"device_agent": {
    "key": "device_agent",
    "name": "DeviceAgent",
    "framework": "Claude Agent SDK",
    "description": "面向设备联动对话的 Claude Agent SDK 智能体",
}
```

DeviceAgent 在 `run` 入口先 `workspace.prepare_session(session_id)` 拿到 `<base>/<session_id>-<uuid>` 临时目录，调 `skills_service.materialize_enabled_skills("device_agent", workspace_dir)`，把启用的 Skill 复制到 `<workspace>/.claude/skills/<name>/`；`build_options` 传 `setting_sources=["project"]`，`cwd=workspace_dir`。`allowed_tools` 始终包含 `"Skill"`。

**工作区清理**：`run` 在 `finally` 块里 `shutil.rmtree(workspace_dir, ignore_errors=True)`。本变更**不**复用 Log Analysis 的 `workspace.py`（它假设有 `logs/` / `repo/` / `task.json`），而是写一份精简的 `device_agent/workspace.py`，只保留 Skill 物化与清理。

**Admin 前端**：`AdminAgentSkills.vue` 的 Agent 下拉新增 `DeviceAgent`；API 路径 `/admin/agent-skills/*` 沿用现有实现，仅需通过 `SUPPORTED_AGENTS` 自动展示。

### Decision 6：删除"主力模型"与"轻量级模型"OpenAI 兼容配置，统一走 `ANTHROPIC_*`

**删除（主力模型链路）**：
- `app/services/runtime_settings_service.py`：移除 `get_effective_primary_config` / `update_primary_model` / `_PRIMARY_CONFIG_KEYS` 等"主力模型"相关入口；保留 prompts/其他运行期键。
- `app/api/admin.py`：移除 `GET/PUT /admin/model-settings/primary`（或同名路径）相关路由与 `PrimaryModelSettings*` 请求模型。
- `app/config.py`：移除 `openai_api_key`、`openai_base_url`、`deepseek_api_key`、`deepseek_base_url`、`llm_model_name`、`llm_reasoning_model`、`llm_temperature`、`llm_provider` 字段；用 grep 在全仓库验证无其他引用。
- 前端 `AdminModelSettings.vue` 中"主力模型"表单块、`api/admin.ts` 中 `getPrimaryModelConfig` / `updatePrimaryModelConfig` / 相关 TS 类型。
- `chat_agent.py::_make_llm` 整体随 ChatAgent 删除。

**删除（轻量级模型 OpenAI 兼容链路）**：
- `app/services/light_llm_service.py` 整个文件删除（LangChain `ChatOpenAI` → oneapi 路径退场）。
- `app/config.py`：移除 `llm_light_model_name`、`llm_light_base_url`、`llm_light_api_key`、`llm_light_temperature` 四个字段。
- `app/services/runtime_settings_service.py`：移除 `_LIGHT_CONFIG_KEYS`（`llm_light_*` 四键）、`get_effective_light_config`、`update_light_model`、以及 `update_light_model` 调用的 `light_llm_service.reset_cached_client()` 钩子。
- `app/api/admin.py`：移除 `PUT /admin/model-settings/light` 端点、`LightModelSettings*` 请求/响应模型、`light_llm_*` 状态字段。
- 前端 `AdminModelSettings.vue` 中"轻量级模型"表单块（与主力模型同时移除）；`api/admin.ts` 中 `updateLightModelConfig` 等方法与 TS 类型移除。
- `app/api/ai_chat.py:18` 的 `from app.services.light_llm_service import summarize_user_message` 替换为 `from app.services.title_generator_service import summarize_user_message`；保持原 `ai_chat.py:113` 调用点签名不变。

**保留 / 沿用**：`anthropic_provider` / `anthropic_api_key` / `anthropic_base_url` / `anthropic_model` / `anthropic_small_fast_model` / `anthropic_max_turns` / `anthropic_permission_mode` / `anthropic_request_timeout_seconds` 已经存在。本变更只新增三个对话场景独有的 setting：
- `device_agent_permission_timeout_seconds: int = 120`（HITL 等待用户决定的超时）
- `device_agent_result_excerpt_bytes: int = 16 * 1024`
- `device_agent_result_max_bytes: int = 256 * 1024`

并新增轻量级路径自身的两个 setting（可选）：
- `anthropic_small_fast_max_tokens: int = 1024`（标题/摘要单次响应上限，避免小模型也消耗 8K 上下文）
- `anthropic_small_fast_request_timeout_seconds: int = 30`（短任务超时，独立于 `anthropic_request_timeout_seconds = 3600`）

### Decision 7：对话历史与会话标题生成

**对话历史**：`AIChatService._prepare_history_messages` 改为返回 `List[Dict[str,str]]`（`{"role": "user"|"assistant", "content": str}`），不再用 LangChain `BaseMessage`。DB 持久化已经按 `role/content` 存储，只需要去掉中间的 LangChain 转换层。组装 `query()` 输入时按以下规则拼接（SDK 当前 `query()` 单 prompt 入参）：
```
{system_prompt} 由 ClaudeAgentOptions.system_prompt 注入。
prompt = "\n\n".join(f"[{role}] {content}" for role, content in recent_history) + f"\n\n[user] {current_message}"
```
保留最近 N 轮（`anthropic_max_history_turns: int = 10`）。

**会话标题生成 / 用户输入摘要（统一为"轻量级 Anthropic 任务"）**：不再依赖 `agent.planner_llm`，也不再走 LangChain `ChatOpenAI`；改为新增 `app/services/title_generator_service.py`，对外保留与旧 `light_llm_service` 兼容的 `async def summarize_user_message(content: str, max_length: int = 16) -> str` 入口（这样 `app/api/ai_chat.py:113` 调用点不动）。内部实现：

```python
opts = anthropic_client.build_options(
    system_prompt=<title_prompt>,
    allowed_tools=[],                  # 不挂任何工具
    cwd=<ephemeral_tempdir>,
    max_turns=1,
    permission_mode="bypassPermissions",
    model=settings.anthropic_small_fast_model
          or PROVIDER_PROFILES[settings.anthropic_provider].default_small_fast_model,
    max_tokens=settings.anthropic_small_fast_max_tokens,
    request_timeout_seconds=settings.anthropic_small_fast_request_timeout_seconds,
)
async for message in query(prompt=cleaned_input[:1200], options=opts):
    ...
```

- 用结果中 final assistant text 的首行（≤ `max_length` 字符）作为标题；失败 / 超时回退到截断输入。
- **路由保证**：`anthropic_small_fast_model` 与 `anthropic_model` 共享同一份 `ANTHROPIC_API_KEY` / `ANTHROPIC_BASE_URL`，仅 `model` 字段不同——DeepSeek provider 下，重活走 `deepseek-v4-pro`、轻活走 `deepseek-v4-flash`，二者都是 deepseek 的 Anthropic 兼容端点。
- 该 service **不**依赖运行期 admin 覆盖；模型选择完全由 env (`ANTHROPIC_SMALL_FAST_MODEL`) 或 provider profile 的 `default_small_fast_model` 决定。如果运营确实需要单独切换 small_fast_model，靠环境变量重启即可，避免再造一套 runtime override。

### Decision 8：DeepSeek（`supports_mcp_server_tools=False`）降级策略

**选择**：在 DeepSeek provider 下，DeviceAgent **拒绝**启动并返回 HTTP 400 `error_kind="provider_no_mcp_support"`，提示运营切换到支持 MCP 的 provider。

**理由**：DeviceAgent 的核心交互依赖动态 MCP 工具映射；让模型在 system prompt 里"伪 MCP"会回到我们正在删除的旧路径，不值得保留。日志分析 Agent 因为只用内置工具能在 DeepSeek 下工作，DeviceAgent 不一样。

**备选**：保留"单一 `device_prompt` 工具 + 协议化文本"路径作为 fallback。被否：等于把 ChatAgent 改个壳留下来，违背"完全摒弃"的目标。

### Decision 9：上位机 `PromptEnvelope.prompt` 新格式

**结构化 JSON 字符串**：
```json
{
  "protocol_version": 2,
  "action": "mcp_call",
  "server": "<server_name>",
  "tool": "<tool_name>",
  "args": {...},
  "request_id": "<uuid>",
  "permission_decision": "allow",   // 上位机不再自行决定执行权限
  "ts": "<ISO8601>"
}
```
上位机侧 AI Helper 收到后只做：(a) 校验 `protocol_version == 2`；(b) 在本机 MCP server 上 `call_tool(tool, args)`；(c) 回包。**上位机不再做自然语言解析、不再选择工具**。

**兼容旧上位机**：本变更不强制上位机同步升级。`build_options` 接收一个 per-request `legacy_envelope: bool` 开关（默认 `False`）；如果设备上报的 `device.capabilities.protocol_version < 2`，DeviceAgent 退化为：把所有动态工具的 `_dispatch_to_device` 实现统一发送旧格式协议化文本（沿用 ChatAgent 现有"`【DEVICE_TASK】`..."模板），但**模型层仍然看到的是真实工具名/schema**——只是 wire format 兼容。该兼容路径在 Decision 8 之后仍可用（同样需要 Anthropic provider）。

### Decision 10：上位机回包 schema

```json
{
  "request_id": "<uuid>",
  "topic_id": "<uuid|null>",
  "status": "ok" | "error",
  "result": <any, 工具 outputSchema 决定>,
  "evidence": [{"label": "...", "text": "..."}],   // 可选关键字段，每条 ≤ excerpt_bytes
  "error_kind": "device_offline|tool_not_found|tool_timeout|permission_denied|internal_error",
  "error_message": "..."
}
```
上位机回包后由 `PostToolUse` hook 二次审查（Decision 4）。

### Decision 11：trace 事件复用与扩展

复用 `app/agents/log_analysis/trace.py` 的所有事件类型与 `_RunState`、`_emit_for_message`、`mask_*`、`coerce_chunk`、`summarize` 等工具函数（直接 `from app.agents.log_analysis.trace import ...`）。

新增 DeviceAgent 专属事件（在 `app/agents/device_agent/trace.py` 里以独立常量声明，复用 `build_event`）：
- `tool_permission_request{request_id, tool_name, args, risk, rationale}`
- `tool_permission_resolved{request_id, decision, updated_args?, reason?}`
- `result_validation{step_id, status: "ok"|"schema_mismatch"|"truncated", reason?}`

SSE 仍走 `ai_chat_service._sse_event`；前端在 `AIChat.vue` 接收时按事件 `type` 分发。

### Decision 13：`build_options` 接受 `model` 覆盖（驱动轻量级路由）

**问题**：`anthropic_client.build_options` 当前没有 `model` 形参，effective_model 只来自 `settings.anthropic_model or profile.default_model`，导致同一进程内"重活/轻活"无法在同一 provider 下选择不同 model id。

**选择**：在 `build_options(...)` 签名中**新增 `model: Optional[str] = None`** 关键字参数：
- 优先级：caller `model=` 覆盖 > `settings.anthropic_model` > `profile.default_model`。
- 当 `model` 显式传入并与 `settings.anthropic_model` 不一致时，日志加一条 INFO 记录"effective_model overridden by caller"，便于排查轻量级路径走错模型的事故。
- 同样新增 `max_tokens: Optional[int]` 与 `request_timeout_seconds: Optional[int]`，给短任务收敛输出长度与超时。

**理由**：避免再造一个 `build_lightweight_options(...)` 工厂；调用方只多传一个关键字参数，profile/Settings 解析逻辑完全复用。

**备选**：单独写 `build_lightweight_options(...)`。被否：profile 解析、能力校验、env 注入全部要重复一份，维护成本翻倍。

### Decision 14：`title_generator_service` 目录与依赖

新增 `app/services/title_generator_service.py`（位于 services/ 目录下，不归到 `app/agents/device_agent/`，因为它服务于多个调用点而非 DeviceAgent 专属），对外接口：

```python
async def summarize_user_message(content: str, max_length: int = 16) -> str
```

签名与旧 `light_llm_service.summarize_user_message` 完全对齐，使 `app/api/ai_chat.py` 调用点零改动。

内部依赖：
- `app.agents.anthropic_client.build_options`（用 Decision 13 新增的 `model` 形参）
- `claude_agent_sdk.query`
- `app.prompts.prompts_config_service.get_title_prompt`（沿用现有 `chat_title_prompt` key，prompt 文案不变；如该 key 不存在则在本变更中新增一份默认模板）

`light_llm_service.py` 在本变更内删除；`runtime_settings_service.py` 中 `light_llm_service.reset_cached_client()` 钩子同步移除。

### Decision 12：目录布局与文件清单

```
app/agents/device_agent/
├── __init__.py
├── agent.py          # DeviceAgent.run / run_stream，类似 LogAnalysisAgent
├── mcp_tools.py      # build_device_mcp_server(device, session_id) -> (server, allowed_tool_names)
├── permissions.py    # PermissionBroker, can_use_tool callback factory
├── post_tool_hook.py # build_post_tool_use_hook(tools_by_name, opts) -> HookMatcher
├── prompts.py        # get_prompts(scene_hint) -> (system, user_prompt_renderer)
├── trace.py          # device-agent-specific event constants + helpers
└── workspace.py      # prepare_session / cleanup（仅 Skill 物化与临时目录）

app/services/
├── title_generator_service.py   # 新增；替代 light_llm_service，走 build_options(model=small_fast)
└── (light_llm_service.py)       # 删除
```

## Risks / Trade-offs

- [上位机协议升级未对齐] → Decision 9 提供 `legacy_envelope` 兼容路径；首批灰度只在能上报 `protocol_version=2` 的设备上启用结构化路径，其余继续走旧文本协议。
- [DeepSeek 不支持 MCP，运营 surprise] → 在 admin "Anthropic Settings" 页与 chat 接口报错里加显式说明；`error_kind="provider_no_mcp_support"`；docs/DEPLOY 中突出 DeviceAgent 必须用 Anthropic 官方 provider 或其他支持 MCP 的兼容端点。
- [模型在 HITL 弹窗等待时占用 SDK 在途请求] → `device_agent_permission_timeout_seconds` 默认 120s；超时 `deny`，hook 返回友好 message；不会无限阻塞。
- [动态 MCP server 注册开销] → 每次 `query()` 重新创建一组 `@tool` proxy；当工具数量很大时（>50）有内存与 schema 解析开销。设上限 `device_agent_max_remote_tools: int = 64`，超出时截断并 `system_notice{kind="too_many_tools", dropped: [...]}`。
- [`PostToolUse` hook 修改 content 让模型困惑] → 替换响应里始终保留 `error_kind` 与原始 size 提示；hook 同时向 SSE 推 `result_validation` 让前端可见性强。
- [删除"主力模型"配置导致其他功能断裂] → 在实施前 grep 全部 `openai_api_key` / `OPENAI_API_KEY` / `deepseek_*` / `llm_model_name` 引用，列出后逐项决定保留/迁移/删除；标题生成、prompt 引用等明确替换为 `anthropic_client` 路径。
- [Skill 物化在每轮请求都拷贝磁盘] → workspace 在请求结束清理；Skill 数量可控（admin 上传场景为主，<10 个）；与 Log Analysis 表现一致。

## Migration Plan

1. **代码先行（Phase 1，本变更）**：
   - 落地 `app/agents/device_agent/` 与新 `ai_chat_service.py`、API 端点、前端 SSE 处理；CI 通过。
   - 上线时上位机仍只支持旧协议，DeviceAgent 默认走 `legacy_envelope=True`（与设备上报的 `protocol_version` 联动），模型行为肉眼可对照旧 ChatAgent。
2. **上位机协议升级（Phase 2，独立 PR）**：上位机支持 `protocol_version=2` 后，能力上报里把 `protocol_version` 字段加上，DeviceAgent 自动切到结构化路径。
3. **清理**（Phase 3，独立 PR）：旧上位机退服后删除 `legacy_envelope` 分支与旧协议文本模板。

**回滚**：在 git 中 revert 本变更即可恢复 ChatAgent；DB 数据结构未变，会话历史可继续被旧实现读取。

## Open Questions

- 是否需要在 admin 增加"per-tool risk 规则编辑器"，让 SRE 不改代码就能给某些工具升级风险？本期先用 YAML 规则；如果调研发现规则改动频繁再加 UI。
- 单次 chat 请求最多保留几轮历史（`anthropic_max_history_turns`）对模型表现影响？需要在 staging 抓 5-10 个真实会话样本调参；默认 10 先发。
- DeepSeek 端的"伪 MCP"是否值得在 Phase 4 单独立项？决策延后到运营给出明确诉求。
