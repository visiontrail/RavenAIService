## 1. 配置与依赖清理

- [ ] 1.1 在 `app/config.py` 的 `Settings` 中新增三个 DeviceAgent 字段：`device_agent_permission_timeout_seconds: int = 120`、`device_agent_result_excerpt_bytes: int = 16 * 1024`、`device_agent_result_max_bytes: int = 256 * 1024`、`device_agent_max_remote_tools: int = 64`、`anthropic_max_history_turns: int = 10`
- [ ] 1.2 全仓库 grep 列出 `openai_api_key` / `OPENAI_API_KEY` / `OPENAI_BASE_URL` / `deepseek_api_key` / `deepseek_base_url` / `llm_model_name` / `llm_reasoning_model` / `llm_temperature` / `llm_provider` 的使用者；在每一处确认要"删除 / 迁移到 anthropic_client / 保留"，把决定写到本任务的 PR 描述里
- [ ] 1.3 删除 `Settings` 中确认不再被使用的 OpenAI-兼容字段；保留有外部依赖的（如有，记录在 design.md "Open Questions"）
- [ ] 1.4 从 `requirements.txt` 移除 ChatAgent 独占的 `langgraph` / `langchain` / `langchain-community` / `langchain-openai` / `langchain-core`（若 Log Analysis 已删则跳过对应行，并在 PR 中注明）
- [ ] 1.5 在 `.env.example`（如存在）同步移除 OpenAI/DeepSeek 旧字段并明确 `ANTHROPIC_API_KEY` 为 DeviceAgent 必需

## 2. 扩展 `anthropic_client.build_options`

- [ ] 2.1 修改 `app/agents/anthropic_client.build_options` 签名，新增 `can_use_tool: Optional[Callable]=None`、`hooks: Optional[Dict[str, List[Any]]]=None` 两个 keyword-only 参数；存在时写入 `ClaudeAgentOptions`
- [ ] 2.2 允许 `permission_mode="default"` 与 `can_use_tool` 同时传入；不做互斥校验，保留向下兼容
- [ ] 2.3 单元测试：`can_use_tool` 与 `hooks` 透传、未传时默认行为不变、`permission_mode="default"` 与 callback 共存

## 3. DeviceAgent 模块骨架

- [ ] 3.1 创建 `app/agents/device_agent/__init__.py`、`workspace.py`（实现 `prepare_session(session_id) -> Path` 与 `cleanup(path)`，仅负责 `<base>/<session_id>-<uuid>/.claude/skills/` 物化目录与幂等清理）
- [ ] 3.2 创建 `app/agents/device_agent/trace.py`：声明 `TOOL_PERMISSION_REQUEST` / `TOOL_PERMISSION_RESOLVED` / `RESULT_VALIDATION` 事件常量；复用 `app.agents.log_analysis.trace.build_event` 构造
- [ ] 3.3 创建 `app/agents/device_agent/prompts.py`：`get_prompts(scene_hint: Optional[str]) -> (system_prompt, user_prompt_renderer)`；从 `prompts_config.yaml.claude_agent_device.*` 读取
- [ ] 3.4 在 `app/prompts/prompts_config.yaml` 删除仅服务于旧 ChatAgent 的 key（`chat_*` 系列里只服务于 LangGraph 的部分）；新增 `claude_agent_device.default` 顶级 key，含 `system_prompt`、`user_prompt_template`、`risk_rules`（按 `(server_glob, tool_glob) -> risk` 列表）
- [ ] 3.5 在 `app/services/prompts_config_service.py` 暴露 `get_device_agent_prompts(scene_hint)` 与刷新钩子；删除 `get_chat_title_prompt_template` 中对 `agent.planner_llm` 的隐式依赖（替换为新标题生成器使用）

## 4. 远端 MCP → in-process SDK 工具映射

- [ ] 4.1 创建 `app/agents/device_agent/mcp_tools.py`，导出 `build_device_mcp_server(device: DeviceInfo, *, session_id: str, target_device_id: str, dispatcher: Callable) -> tuple[McpServer, list[str], dict[str, ToolMeta]]`
- [ ] 4.2 内部实现：遍历 `device.capabilities.mcp.servers[].tools[]`，按 `(server_name, tool_name)` 排序，截断到 `device_agent_max_remote_tools`；超出部分通过 `system_notice` 事件外发
- [ ] 4.3 每个工具用 `claude_agent_sdk.tool` 装饰生成 proxy；`name="mcp__device__<server>__<tool>"`；`description` 走能力上报的字段，缺失时回退 `f"Invoke {server}.{tool} on the linked device"`；`input_schema` 走能力上报的 `inputSchema`，缺失时回退 `{"type":"object","additionalProperties":True}`
- [ ] 4.4 proxy 内部调用 `dispatcher(server, tool, args, request_id)`，把上位机回包返回作为工具输出（结构化 dict）
- [ ] 4.5 用 `create_sdk_mcp_server(name="device", version="1.0", tools=[...])` 注册；返回工具名列表与 `tool_meta` 映射（含 risk、outputSchema）供 permissions/post-tool-hook 使用
- [ ] 4.6 单元测试：能力上报含 2/0/65 个工具的三种情况、`inputSchema` 缺失时回退、超出上限的 `system_notice`

## 5. 设备链路 dispatcher（结构化 envelope）

- [ ] 5.1 在 `app/agents/device_agent/mcp_tools.py` 实现 `default_dispatcher(...)`：构造 v2 envelope（`protocol_version=2`、`action="mcp_call"`、`server`、`tool`、`args`、`request_id`、`permission_decision="allow"`、`ts`），用 `device_link_manager.send_prompt` 投递；等待回包；返回 dict
- [ ] 5.2 实现兼容路径：当 `device.capabilities.protocol_version` 缺失或 `< 2` 时，dispatcher 切换为旧 `【DEVICE_TASK】... 工具选择: <name>\n 参数(JSON): {...}\n... 【/DEVICE_TASK】` 文本模板；首次走兼容路径时发送一次 `system_notice{kind="legacy_envelope"}`
- [ ] 5.3 dispatcher 失败处理：异常映射为 `{status:"error", error_kind:"internal_error", error_message:str(exc)}` 返回；不要让异常穿越 SDK loop
- [ ] 5.4 测试：v2 envelope 字段齐全、legacy envelope 文本格式与旧 ChatAgent 等价、`send_prompt` 抛异常时降级返回

## 6. Human-in-the-loop（`can_use_tool`）

- [ ] 6.1 创建 `app/agents/device_agent/permissions.py`，实现 `PermissionBroker`：内部持有 `Dict[request_id, asyncio.Future]` + `asyncio.Queue` 输出（向外部 SSE 推 `tool_permission_request` 事件）
- [ ] 6.2 实现 `classify_risk(tool_name, tool_meta, risk_rules) -> Literal["read","write","destructive"]`：优先看 `tool_meta.risk`，否则按 `prompts_config.yaml.claude_agent_device.risk_rules` 匹配，兜底 `write`
- [ ] 6.3 实现 `make_can_use_tool(broker, tool_meta_map, risk_rules, timeout_s) -> async callable`，按 spec 描述的语义返回 `{"behavior":"allow"|"deny", "updatedInput"?:dict, "message"?:str}`；read 级别短路 allow；超时返回 deny 并发出 `tool_permission_resolved{reason:"timeout"}`
- [ ] 6.4 在 `app/api/chat.py` 新增 `POST /chat/permissions/{request_id}/resolve`，body `{decision, updated_args?, message?}`；调用 `broker.resolve(request_id, decision)`；返回 200/404/400 三种状态码
- [ ] 6.5 单元测试：read 短路、destructive 走完整 request/resolve 流程、`updated_args` 透传、超时 deny、未知 request_id 404

## 7. 客户端结果审查（`PostToolUse` hook）

- [ ] 7.1 创建 `app/agents/device_agent/post_tool_hook.py`，导出 `build_post_tool_use_hook(tool_meta_map, emit, *, excerpt_bytes, max_bytes) -> HookMatcher`，matcher 串为 `"mcp__device__*"`
- [ ] 7.2 实现 validator：解析 `Decision 10` schema、可选 `outputSchema` 校验（`jsonschema` 第三方库或简单字段检查；评估两者后选一并在 design.md 加注释）
- [ ] 7.3 实现裁剪：单条 evidence > `excerpt_bytes` 截断并加 `truncated=True`；总长 > `max_bytes` 替换为 `{"error_kind":"result_too_large"}`
- [ ] 7.4 实现脱敏：复用 `app.agents.log_analysis.trace.mask_tokens` / `mask_input`
- [ ] 7.5 不合契约时返回 `{"hookSpecificOutput":{"hookEventName":"PostToolUse","permissionDecision":"allow","modifiedContent":{...}}}`；并 emit `result_validation{status:"schema_mismatch", reason}`
- [ ] 7.6 单元测试：ok / schema_mismatch / result_too_large / 敏感字段脱敏 / 已知 error_kind 直透

## 8. DeviceAgent.run / run_stream

- [ ] 8.1 创建 `app/agents/device_agent/agent.py`：`class DeviceAgent`，参考 `LogAnalysisAgent` 用 `_RunState` 缓冲 `AgentTraceEvent`、累计 token usage、提取 final_text
- [ ] 8.2 实现 `run_stream(ctx) -> AsyncIterator[AgentTraceEvent]`，内部：profile check（DeepSeek 拒绝并 yield error）→ `workspace.prepare_session` → `skills_service.materialize_enabled_skills("device_agent", workspace)` → 构建 device MCP server + dispatcher → 构建 broker + can_use_tool + post_tool_hook → `build_options(... can_use_tool=..., hooks={"PostToolUse":[...]}, setting_sources=["project"] if skills else None, permission_mode="default", cwd=workspace)` → `async for message in query(...)` 翻译为事件 → `finally: workspace.cleanup`
- [ ] 8.3 历史拼接：把 `recent_history`（最近 `anthropic_max_history_turns` 轮）拼成单 prompt（`[role] content` 行格式）+ 当前用户消息
- [ ] 8.4 实现 `run` 同步包装：聚合所有 trace 事件，返回 `(events, final_text, model)` 三元组，供非流式调用方使用
- [ ] 8.5 单元测试：mock `claude_agent_sdk.query` 返回固定消息序列，验证事件流顺序、HITL 集成、PostToolUse 集成、超时清理、DeepSeek 拒绝路径

## 9. 重写 `AIChatService`

- [ ] 9.1 删除 `from langchain_core.messages import ...` 与 `from app.agents.chat_agent import ChatAgent`；删除 `_SessionMemory`、`_to_langchain_messages`、`_to_chat_messages`
- [ ] 9.2 历史读取改为 `List[Dict[str,str]]`：从 `chat_history_service.fetch_messages` 直接取 `{"role","content"}`
- [ ] 9.3 `chat_stream` 整体改写为：先 yield `session`/`run_start`，然后 `async for ev in DeviceAgent().run_stream(...)`：把 `AgentTraceEvent` 转 SSE（事件类型直接用 `ev["type"]`）；结束时 yield `done`（含 `answer` / `model` / `messages`）
- [ ] 9.4 `chat`（非流式）调用 `DeviceAgent().run(...)`，组装 `ChatResponse`；`model` 字段取自 effective Anthropic model
- [ ] 9.5 标题生成迁移：新增 `app/services/title_generator_service.py`，用 `build_options(allowed_tools=[], cwd=<tmp>, system_prompt=<title prompt>)` 跑一次 `query()`；`AIChatService._generate_session_title` 改为调用该 service
- [ ] 9.6 删除 `rebuild_agent`（无运行期模型覆盖后无需重建）；删除 `runtime_settings_service` 调它的所有钩子
- [ ] 9.7 单元 / 集成测试：流式分支 SSE 顺序、非流式分支响应字段、新标题生成回退到空字符串时不报错、历史长度截断生效

## 10. 删除"主力模型"运行期配置

- [ ] 10.1 `app/services/runtime_settings_service.py`：移除 `get_effective_primary_config`、`update_primary_config`、`_PRIMARY_CONFIG_KEYS`、对 `ai_chat_service.rebuild_agent` 的所有调用；保留 prompts/其他 runtime 键
- [ ] 10.2 `app/api/admin.py`：移除 `GET/PUT /admin/model-settings/primary`（或对应路径）；保留其他 admin 端点
- [ ] 10.3 前端 `frontend/src/views/AdminModelSettings.vue`：删除主力模型表单块；保留 Anthropic 配置只读视图
- [ ] 10.4 前端 `frontend/src/api/admin.ts`：移除 `getPrimaryModelConfig` / `updatePrimaryModelConfig` 等方法
- [ ] 10.5 前端 `frontend/src/types/index.ts`：移除对应 TS 类型
- [ ] 10.6 grep 验证零残留；运行前后端构建确保无类型错误

## 11. 删除旧 ChatAgent 与依赖

- [ ] 11.1 删除文件 `app/agents/chat_agent.py`、`app/agents/tools/device_prompt_tool.py`、`app/agents/tools/__init__.py`（若 `tools/` 目录为空则保留 `__init__.py` 占位或一并删除）
- [ ] 11.2 grep 验证 `from app.agents.chat_agent`、`device_prompt`、`set_device_prompt_context`、`clear_device_prompt_context` 在 `app/` 中零引用
- [ ] 11.3 grep 验证 `langchain_core`、`langchain_openai`、`langgraph` 在 `app/agents/` 与 `app/services/` 中零引用（其他位置如有保留写入 PR 备注）

## 12. Skill 支持注册

- [ ] 12.1 在 `app/services/skills_service.SUPPORTED_AGENTS` 新增 `"device_agent": {...}` 条目
- [ ] 12.2 前端 `frontend/src/views/AdminAgentSkills.vue` 的 Agent 下拉确保读取 `SUPPORTED_AGENTS`（已实现）；目视确认新 Agent 出现
- [ ] 12.3 端到端测试：上传一个最小 Skill 包给 `device_agent`、启用、跑一次 `POST /chat` 确认 `<workspace>/.claude/skills/<name>/SKILL.md` 被物化

## 13. API 与前端 SSE 适配

- [ ] 13.1 `app/api/chat.py`：注册 `POST /chat/permissions/{request_id}/resolve`；接入 `AIChatService.permission_broker_registry`（每 session 一个 broker）
- [ ] 13.2 前端 `frontend/src/views/AIChat.vue`：扩展 SSE 事件 switch，新增 `tool_permission_request`（弹模态框）/`tool_permission_resolved` / `result_validation` / `step_*` / `thinking_*` / `run_start` / `run_complete`
- [ ] 13.3 前端调用 `POST /chat/permissions/{request_id}/resolve`：新增 `frontend/src/api/chat.ts` 方法 + 类型
- [ ] 13.4 兼容旧前端：保留 `chunk` / `done` / `session` / `error` 事件不变；新事件未被识别时静默忽略，不阻断主流程
- [ ] 13.5 手测：在 staging 跑一条"列出后台任务 + 启动升级流程"两步对话，第二步触发 HITL 弹窗，覆盖允许/拒绝/编辑参数三条路径

## 14. 测试与发布

- [ ] 14.1 集成测试：mock `claude_agent_sdk.query` + mock `device_link_manager.send_prompt`，跑通"读类工具自动允许 / 写类工具走 HITL / 结果 schema_mismatch 替换"完整路径
- [ ] 14.2 集成测试：DeepSeek provider 下 `POST /chat` 返回 `error_kind="provider_no_mcp_support"`
- [ ] 14.3 部署文档 `DEPLOY_USAGE.md` 增加 "DeviceAgent" 章节：说明 Anthropic provider 必需、HITL 流程、Skill 装载方法，链接到 Log Analysis 对应章节
- [ ] 14.4 在 staging 配置 `ANTHROPIC_PROVIDER=anthropic` + 真实设备，做至少一条 end-to-end 对话验证：能看到 thinking / step / tool_permission_request / result_validation 事件按预期出现
- [ ] 14.5 打 tag `pre-device-agent-migration` 锁定回滚点（在合并前）
- [ ] 14.6 部署后观察首批对话的成功率、平均 HITL 等待时长、超时占比、`provider_no_mcp_support` 计数；若 HITL 超时占比 > 20% 则把 `device_agent_permission_timeout_seconds` 默认值调大并发补丁
