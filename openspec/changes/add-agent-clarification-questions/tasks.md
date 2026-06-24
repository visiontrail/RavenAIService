## 1. 后端：澄清事件与工具

- [x] 1.1 在 `app/agents/device_agent/trace.py` 新增事件常量 `CLARIFICATION_REQUEST = "clarification_request"`、`CLARIFICATION_RESOLVED = "clarification_resolved"` 并导出
- [x] 1.2 新增 `app/agents/device_agent/clarification.py`：定义 `AskUserQuestion` 工具的 `inputSchema`（`questions:[{header, question, options:[{label, description}], multiSelect?}]`）与 `create_sdk_mcp_server`（server 名 `ask`，工具名 `AskUserQuestion`）
- [x] 1.3 在该模块实现工具 proxy：生成 `request_id` → 发 `clarification_request`（携带 `questions/run_id/session_id`）→ `broker.open(request_id, tool_name="AskUserQuestion", risk="clarify")` → `await` Future
- [x] 1.4 实现答案格式化：把 `{"answers":[...]}` 渲染为结构化、人类可读的 `text`，按 SDK 约定包成 `{"content":[{"type":"text","text":...}]}` 返回（spec：工具阻塞与答案回喂）

## 2. 后端：broker、超时与取消

- [x] 2.1 在 `app/agents/device_agent/permissions.py` 放宽 `PermissionBroker.open` 接受 `risk="clarify"`（或新增等价 `open_clarification` 包装，复用同一 `_pending` 表）
- [x] 2.2 实现澄清超时分支：读取超时时长（代码常量 `device_agent_clarification_timeout_seconds=300`）与用户偏好 `clarification_on_timeout`
- [x] 2.3 `continue` 模式：超时发 `clarification_resolved{outcome:"timeout"}`，工具返回"用户未作答、请基于已知信息继续/最佳猜测"的结果
- [x] 2.4 `cancel` 模式（默认）：超时发 `clarification_resolved{outcome:"cancelled", reason:"timeout"}`，并调用注入的 `cancel_run` 回调终止本轮 run（无注入时降级为 continue 语义）
- [x] 2.5 确认 `resolve`/`cancel` 对 `future.done()` 的幂等保护覆盖"用户回答 vs 超时"竞态

## 3. 后端：resolve 端点

- [x] 3.1 在 `app/api/ai_chat.py` 新增 `POST /chat/clarifications/{request_id}/resolve`，请求/响应 Pydantic 模型（`answers:[{question_index, selected_labels[], custom_text?}]`、`run_id?`、`session_id?`）
- [x] 3.2 复用 permission 端点的查找与归属逻辑（`run_id → session_id active run → owner_scope 过滤后扫描`），并返回 403/404 规则一致
- [x] 3.3 实现必答校验（每问需 `selected_labels` 非空或 `custom_text` 非空），失败返回 400；成功 `broker.resolve(request_id, {"answers":[...]})`
- [x] 3.4 新增对应 i18n 错误文案键（无效答案/未找到等），与 permission 端点文案风格一致

## 4. 后端：用户设置（DB + profile）

- [x] 4.1 `app/models/user.py`：`User` 新增列 `clarification_enabled: bool=True`、`clarification_max_rounds: int=5`、`clarification_on_timeout: str="cancel"`（均带 `server_default`，与 `language`/`profile_role` 同构）
- [x] 4.2 新增 Alembic 迁移给 `users` 加这 3 列（向后兼容旧行）
- [x] 4.3 `app/api/users.py` + `user_service.update_profile`：profile 读写支持这 3 个字段（含取值校验：`on_timeout∈{cancel,continue}`、`max_rounds` 合理上下界）；`UserProfile` 返回它们
- [x] 4.4 `app/config.py` 新增常量 `device_agent_clarification_timeout_seconds = 300`（5 分钟，非用户可改）

## 5. 后端：snapshot 回放与 context 透传

- [x] 5.1 `app/services/chat_run_service.py`：`ChatRunJob` 增加 `pending_clarifications: Dict[str, dict]`
- [x] 5.2 在事件回放循环对 `clarification_request` 入栈、`clarification_resolved` 出栈；snapshot 输出新增 `pending_clarifications` 列表
- [x] 5.3 在 `ChatRunService` 构造 `DeviceAgentContext` 处（约 L566）注入 `cancel_run` 回调（内部 `self.cancel(run_id, owner_scope)`）
- [x] 5.4 调用方（`ChatRunService` / `AIChatService`）从已认证用户解析 3 项偏好填入 `DeviceAgentContext`；匿名用户用默认值
- [x] 5.5 `DeviceAgentContext` 增加字段：`cancel_run`、`clarification_enabled`、`clarification_max_rounds`、`clarification_on_timeout`

## 6. DeviceAgent 组装接入

- [x] 6.1 `app/agents/device_agent/agent.py`：仅当 `ctx.clarification_enabled` 为真时构建并把 `ask` MCP server 合并进 `mcp_servers`、把 `mcp__ask__AskUserQuestion` 加入 `allowed_tools`
- [x] 6.2 维护 per-run 计数器，达到 `ctx.clarification_max_rounds` 后工具返回"已达本轮提问上限，请自行决断"，不发 `clarification_request`、不阻塞
- [x] 6.3 把 `emit`/`seq_counter`/`task_id`/`run_id`/`session_id`/`broker`/`cancel_run`/超时常量/`on_timeout`/计数器透传给澄清工具构造器

## 7. 前端：类型与 store

- [x] 7.1 `frontend/src/types/agentTrace.ts`：新增 `ClarificationQuestion`、`ClarificationRequestEvent`、`PendingClarification`、`ClarificationAnswer` 类型与两个事件类型
- [x] 7.2 `frontend/src/stores/conversationRuns.ts`：在 per-session state 增加 `pendingClarifications`；在事件分发处对 `clarification_request` 入栈、`clarification_resolved` 出栈（并在 run 终态清空）
- [x] 7.3 `mergeSnapshot` 中从 `snapshot.pending_clarifications` 恢复未答问题（镜像 `pending_permissions` 逻辑）
- [x] 7.4 新增 action `submitClarification(sessionId, requestId, answers)`：调用 API、成功后本地移除、404 视为已结、失败保留并提示

## 8. 前端：组件与 API

- [x] 8.1 `frontend/src/api/chat.ts`：新增 `resolveChatClarification(requestId, payload, authToken)`
- [x] 8.2 新增 `frontend/src/components/ClarificationCard.vue`：逐问渲染 `header/question`、`options`（单/多选）、自定义输入框，底部单一提交按钮，提交前必答校验
- [x] 8.3 在 `AIChat.vue` 中按当前 run 的 `pendingClarifications` 以模态卡片渲染 `ClarificationCard`（与 pendingPermissions 模态同位置；AgentTraceStream 为复用组件不持有 store 状态，故沿用 permission 的 AIChat 落点）

## 9. 前端：用户设置与 i18n

- [x] 9.1 在用户设置面板（`WorkbenchLayout.vue`）新增 3 项：「全局禁用澄清」开关、「每轮最多提问次数」输入（默认 5）、「澄清超时后行为」(`取消本轮`/`基于已知信息继续`)；后者文案提示"等待 5 分钟后生效"
- [x] 9.2 接入 profile 读写（`api/user.ts` / `types`）：加载并保存这 3 项偏好
- [x] 9.3 新增 i18n 文案：3 项设置标签与说明、提交按钮、自定义输入占位符、必答校验提示（中/英）

## 10. 提示词

- [x] 10.1 在 `app/agents/device_agent/prompts.py`（按 `locale`）补充 `AskUserQuestion` 使用指引：仅在缺关键参数/多解/目标不明时提问，能推断则不打断，并给正/反例
- [x] 10.2 提示中点明"每轮提问有上限"，鼓励一次性问全所需澄清

## 11. 测试

- [x] 11.1 单测：澄清工具 happy path（请求事件 → resolve → 返回答案文本）、多问题、自定义输入（`tests/agents/device_agent/test_clarification.py`）
- [x] 11.2 单测：超时 `cancel`（调用 cancel_run + resolved 事件）与 `continue`（工具返回继续结果）两分支，及无回调降级
- [x] 11.3 单测：`max_rounds` 达上限后工具返回兜底、不发请求（含 max_rounds=0 与第二次提问越限）；`clarification_enabled=false` 不注册工具属 agent 组装期行为，由代码 gating 保证
- [x] 11.4 单测：resolve 端点 200/400（空答/缺答）/404（未知/非归属）（`tests/api/test_chat_clarification_resolve.py`）
- [x] 11.5 单测：profile 读写 3 项偏好 + 取值校验（默认值/持久化/非法 on_timeout 归一/越界 max_rounds 422）（`tests/api/test_user_profile_clarification.py`）
- [x] 11.6 单测：snapshot 含/默认空 `pending_clarifications`；`conversationRuns` store 入栈/出栈/快照恢复/会话隔离/提交/必答阻断/终态清空（后端 + 前端 spec）
- [~] 11.7 组件测：`ClarificationCard` 渲染/交互——项目无 `@vue/test-utils`、vitest 为 node 环境，未引入 DOM 挂载依赖；交互逻辑（答案映射、必答校验、提交载荷）已由 store spec 覆盖

## 12. 收尾

- [x] 12.1 `openspec validate add-agent-clarification-questions --strict` 通过
- [x] 12.2 README / README_EN 增补澄清机制与 3 项用户设置说明
- [x] 12.3 回归确认：不调用 `AskUserQuestion` / 禁用澄清时 run 行为与现状一致（非破坏性）—— 工具按 `clarification_enabled` gating，未调用即无新事件；新测试全绿，5 个后端 + 2 个前端失败经 stash 验证为既有环境性失败，与本改动无关
