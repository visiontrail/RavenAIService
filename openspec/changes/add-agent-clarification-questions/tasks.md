## 1. 后端：澄清事件与工具

- [ ] 1.1 在 `app/agents/device_agent/trace.py` 新增事件常量 `CLARIFICATION_REQUEST = "clarification_request"`、`CLARIFICATION_RESOLVED = "clarification_resolved"` 并导出
- [ ] 1.2 新增 `app/agents/device_agent/clarification.py`：定义 `AskUserQuestion` 工具的 `inputSchema`（`questions:[{header, question, options:[{label, description}], multiSelect?}]`）与 `create_sdk_mcp_server`（server 名 `ask`，工具名 `AskUserQuestion`）
- [ ] 1.3 在该模块实现工具 proxy：生成 `request_id` → 发 `clarification_request`（携带 `questions/run_id/session_id`）→ `broker.open(request_id, tool_name="AskUserQuestion", risk="clarify")` → `await` Future
- [ ] 1.4 实现答案格式化：把 `{"answers":[...]}` 渲染为结构化、人类可读的 `text`，按 SDK 约定包成 `{"content":[{"type":"text","text":...}]}` 返回（spec：工具阻塞与答案回喂）

## 2. 后端：broker、超时与取消

- [ ] 2.1 在 `app/agents/device_agent/permissions.py` 放宽 `PermissionBroker.open` 接受 `risk="clarify"`（或新增等价 `open_clarification` 包装，复用同一 `_pending` 表）
- [ ] 2.2 实现澄清超时分支：读取超时时长（`device_agent_clarification_timeout_seconds`，缺省回退 `device_agent_permission_timeout_seconds`）与 `device_agent_clarification_on_timeout`
- [ ] 2.3 `continue` 模式：超时发 `clarification_resolved{outcome:"timeout"}`，工具返回"用户未作答、请基于已知信息继续/最佳猜测"的结果
- [ ] 2.4 `cancel` 模式（默认）：超时发 `clarification_resolved{outcome:"cancelled", reason:"timeout"}`，并调用注入的 `cancel_run` 回调终止本轮 run（无注入时降级为 continue 语义）
- [ ] 2.5 确认 `resolve`/`cancel` 对 `future.done()` 的幂等保护覆盖"用户回答 vs 超时"竞态

## 3. 后端：resolve 端点

- [ ] 3.1 在 `app/api/ai_chat.py` 新增 `POST /chat/clarifications/{request_id}/resolve`，请求/响应 Pydantic 模型（`answers:[{question_index, selected_labels[], custom_text?}]`、`run_id?`、`session_id?`）
- [ ] 3.2 复用 permission 端点的查找与归属逻辑（`run_id → session_id active run → owner_scope 过滤后扫描`），并返回 403/404 规则一致
- [ ] 3.3 实现必答校验（每问需 `selected_labels` 非空或 `custom_text` 非空），失败返回 400；成功 `broker.resolve(request_id, {"answers":[...]})`
- [ ] 3.4 新增对应 i18n 错误文案键（无效答案/未找到等），与 permission 端点文案风格一致

## 4. 后端：snapshot 回放与设置

- [ ] 4.1 `app/services/chat_run_service.py`：`ChatRunJob` 增加 `pending_clarifications: Dict[str, dict]`
- [ ] 4.2 在事件回放循环对 `clarification_request` 入栈、`clarification_resolved` 出栈；snapshot 输出新增 `pending_clarifications` 列表
- [ ] 4.3 在 `ChatRunService` 构造 `DeviceAgentContext` 处（约 L566）注入 `cancel_run` 回调（内部调用 `self.cancel(run_id, owner_scope)`）
- [ ] 4.4 `app/config.py` 新增 `device_agent_clarification_timeout_seconds` 与 `device_agent_clarification_on_timeout`（默认 `"cancel"`）；接入 runtime settings 使其可运行期修改

## 5. DeviceAgent 组装接入

- [ ] 5.1 `app/agents/device_agent/agent.py`：构建并把 `ask` MCP server 合并进 `mcp_servers`、把 `mcp__ask__AskUserQuestion` 加入 `allowed_tools`
- [ ] 5.2 把 `emit`/`seq_counter`/`task_id`/`run_id`/`session_id`/`broker`/`cancel_run`/超时配置透传给澄清工具构造器
- [ ] 5.3 `DeviceAgentContext` 增加 `cancel_run: Optional[Callable]` 字段并贯通

## 6. 前端：类型与 store

- [ ] 6.1 `frontend/src/types/agentTrace.ts`：新增 `ClarificationQuestion`、`ClarificationRequest`、`PendingClarification`、`ClarificationAnswer` 类型与两个事件类型
- [ ] 6.2 `frontend/src/stores/conversationRuns.ts`：在 per-session state 增加 `pendingClarifications`；在事件分发处对 `clarification_request` 入栈、`clarification_resolved` 出栈
- [ ] 6.3 `mergeSnapshot` 中从 `snapshot.pending_clarifications` 恢复未答问题（镜像 `pending_permissions` 逻辑）
- [ ] 6.4 新增 action `submitClarification(sessionId, requestId, answers)`：调用 API、成功后本地移除、404 视为已结、失败保留并提示

## 7. 前端：组件与 API

- [ ] 7.1 `frontend/src/api/chat.ts`：新增 `resolveChatClarification(requestId, payload, authToken)`
- [ ] 7.2 新增 `frontend/src/components/ClarificationCard.vue`：逐问渲染 `header/question`、`options`（单/多选）、自定义输入框，底部单一提交按钮，提交前必答校验
- [ ] 7.3 在 `AgentTraceStream.vue` 中按当前 run 的 `pendingClarifications` 渲染 `ClarificationCard`（与 pendingPermissions 渲染位置一致）

## 8. 前端：设置与 i18n

- [ ] 8.1 在设置面板新增「澄清超时行为」开关（`cancel` / `continue`），绑定到用户/运行期设置
- [ ] 8.2 新增 i18n 文案：提交按钮、自定义输入占位符、必答校验提示、超时行为说明（中/英）

## 9. 提示词

- [ ] 9.1 在 `app/agents/device_agent/prompts.py`（按 `locale`）补充 `AskUserQuestion` 使用指引：仅在缺关键参数/多解/目标不明时提问，能推断则不打断，并给正/反例
- [ ] 9.2 （可选）加入"每轮最多澄清次数"软上限的提示与工具侧兜底返回

## 10. 测试

- [ ] 10.1 单测：澄清工具 happy path（请求事件 → resolve → 返回答案文本）、多问题、自定义输入
- [ ] 10.2 单测：超时 `cancel`（run 被取消 + resolved 事件）与 `continue`（工具返回继续结果）两分支
- [ ] 10.3 单测：resolve 端点 200/400（缺答）/403（非归属）/404（未知）
- [ ] 10.4 单测：snapshot 回放含/不含未决澄清；`conversationRuns` store 入栈/出栈/快照恢复/会话隔离
- [ ] 10.5 组件测：`ClarificationCard` 渲染、单/多选切换、必答校验、提交移除

## 11. 收尾

- [ ] 11.1 `openspec validate add-agent-clarification-questions --strict` 通过
- [ ] 11.2 README/相关 docs 增补澄清机制与超时设置说明
- [ ] 11.3 回归确认：不调用 `AskUserQuestion` 时 run 行为与现状一致（非破坏性）
