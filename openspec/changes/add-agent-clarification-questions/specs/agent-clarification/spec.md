## ADDED Requirements

### Requirement: Agent 自主澄清触发（AskUserQuestion 工具）

系统 SHALL 向 DeviceAgent 暴露一个 in-process MCP 工具 `AskUserQuestion`（SDK 全名 `mcp__ask__AskUserQuestion`），并将其加入 `allowed_tools`。**是否调用该工具完全由模型自行决定**：当且仅当用户指令缺少关键参数、存在多种合理解读或目标对象/范围不明确时，模型 SHOULD 调用它来澄清；能够合理推断时 MUST NOT 无谓打断用户。系统 MUST NOT 强制在 agent loop 之前插入"是否需要澄清"的前置分类步骤。

工具 `inputSchema` MUST 支持**一个或多个**问题：`questions` 为非空数组，每个元素 MUST 含 `header`（短标签）、`question`（完整问题文本）、`options`（2–4 个，每个含 `label` 与 `description`）；`multiSelect`（布尔，缺省 `false`）可选。系统 MUST 为每个问题隐式提供「自定义输入」入口（用户可不选任何预设、自行输入文本作答），无需模型在 `options` 中显式声明。

#### Scenario: 指令不清晰时模型主动提问

- **WHEN** 用户消息为"帮我重启那个服务"，但当前设备存在多个可重启服务且未指明目标
- **THEN** 模型 MAY 调用 `AskUserQuestion`，传入一个 `question`（"要重启哪个服务？"）与 2–4 个候选服务作为 `options`
- **AND** agent loop MUST 在工具返回前阻塞，等待用户作答

#### Scenario: 指令清晰时不打断

- **WHEN** 用户消息已包含执行所需的全部关键参数
- **THEN** 模型 MUST NOT 调用 `AskUserQuestion`
- **AND** run 行为与未引入该能力时完全一致

#### Scenario: 单次调用包含多个问题

- **WHEN** 模型一次调用 `AskUserQuestion` 传入 `questions` 含 2 个元素
- **THEN** 系统 MUST 在同一次澄清请求中承载全部 2 个问题
- **AND** 前端 MUST 在一个卡片内渲染全部问题并一次性收集答案

### Requirement: 澄清事件协议

系统 SHALL 定义两类 `AgentTraceEvent`：`clarification_request` 与 `clarification_resolved`，经现有 `agent_trace` SSE 通道下发。两事件 MUST 携带 `AgentTraceEvent` 基座字段 `type`、`task_id`、`seq`（单调递增）、`timestamp`，并 MUST 携带 `request_id`、`run_id`、`session_id`。新增事件 MUST NOT 替代或修改任何现有事件类型；不识别它们的旧客户端 MUST 仍能正常解析其余事件并收到终态。

`clarification_request` MUST 携带 `questions`（含每问的 `header`/`question`/`options`/`multiSelect`）。`clarification_resolved` MUST 携带 `outcome ∈ {answered, timeout, cancelled}`，并 MAY 携带 `reason` 与答案摘要。同一 `request_id` 的 `clarification_resolved.seq` MUST 大于其 `clarification_request.seq`。

#### Scenario: 请求事件随工具调用发出

- **WHEN** 模型调用 `AskUserQuestion`
- **THEN** 系统 MUST 发出一条 `clarification_request`，其 `questions` 与工具入参等价
- **AND** 该事件 MUST 携带唯一 `request_id`

#### Scenario: 作答后发出 resolved 事件

- **WHEN** 用户提交某 `request_id` 的答案
- **THEN** 系统 MUST 发出 `clarification_resolved{request_id, outcome:"answered"}`
- **AND** 其 `seq` MUST 大于对应 `clarification_request.seq`

### Requirement: 澄清答案回写端点

系统 SHALL 提供 `POST /api/v1/ai-chat/chat/clarifications/{request_id}/resolve`，请求体含 `answers` 数组（每元素 `question_index`、`selected_labels`（数组）、可选 `custom_text`），以及可选 `run_id` / `session_id`。端点 MUST 复用工具审批同款查找与归属逻辑：优先 `run_id`，回退到 `session_id` 的 active run，最后按 `owner_scope` 过滤后扫描；MUST 仅允许 run 的归属者（同 `owner_scope`）resolve。

端点 MUST 做必答校验：对每个被模型标记为必答（或全部问题，按本期约定全部必答）的问题，其答案 MUST 至少含一个 `selected_labels` 项或非空 `custom_text`，否则返回 400。成功 resolve MUST 把 `{"answers": [...]}` 写回对应 broker 的 Future；`request_id` 未知/已 resolve/已超时 MUST 返回 404；非归属者 MUST 返回 403。

#### Scenario: 归属者成功提交答案

- **WHEN** run 归属者对存在的未决 `request_id` 提交合法 `answers`
- **THEN** 端点 MUST 返回 200
- **AND** 对应 broker Future MUST 收到 `{"answers": [...]}`，agent loop 随之继续

#### Scenario: 必答问题缺答

- **WHEN** 某问题既无 `selected_labels` 也无非空 `custom_text`
- **THEN** 端点 MUST 返回 400，且 MUST NOT resolve 该请求

#### Scenario: 非归属者被拒

- **WHEN** 与 run 归属者不同 `owner_scope` 的调用方尝试 resolve 该 `request_id`
- **THEN** 端点 MUST 返回 403 或 404，且 MUST NOT 暴露问题内容

#### Scenario: 未知或已结请求

- **WHEN** 提交的 `request_id` 不存在、已被回答或已超时取消
- **THEN** 端点 MUST 返回 404

### Requirement: 工具阻塞与答案回喂

`AskUserQuestion` 工具 MUST 阻塞当前 agent loop 直到 Future 被 resolve / cancel / 超时。收到用户答案后，工具 MUST 按 SDK 约定返回 `{"content":[{"type":"text","text": <answers_block>}]}`，其中 `text` MUST 为结构化且人类可读的答案块（逐问列出问题、用户所选 `label`、以及自定义文本），使模型可直接消费并继续后续工作。

#### Scenario: 答案回喂模型后继续

- **WHEN** 用户对"要重启哪个服务？"选择 `options` 中的"nginx"
- **THEN** 工具返回的 `text` MUST 含该问题与选定的"nginx"
- **AND** 模型 MUST 能据此继续执行（如发起对 nginx 的重启工具调用）

#### Scenario: 自定义输入回喂

- **WHEN** 用户不选任何预设、在自定义输入框填写"先看日志再决定"
- **THEN** 工具返回的 `text` MUST 含该自定义文本

### Requirement: 澄清超时时长固定与超时行为偏好

系统 SHALL 以代码常量明确澄清等待时长 `device_agent_clarification_timeout_seconds = 300`（5 分钟），该时长 MUST NOT 暴露为用户可改项。超时**行为**由用户偏好 `clarification_on_timeout ∈ {cancel, continue}` 决定，**默认值 MUST 为 `cancel`**。

- `continue`：超时后系统 MUST 发 `clarification_resolved{outcome:"timeout"}`，并使工具返回一个"用户未作答、请基于已知信息给出最合理处理或最佳猜测"的结果，让模型继续。
- `cancel`：超时后系统 MUST 发 `clarification_resolved{outcome:"cancelled", reason:"timeout"}`，并通过运行级取消（复用既有 run cancel 路径）将本轮 run 终止为 `cancelled`。

#### Scenario: 默认超时取消本轮

- **WHEN** 用户 `clarification_on_timeout == "cancel"`（默认）且用户在 5 分钟内未作答
- **THEN** 系统 MUST 终止本轮 run 为 `cancelled`
- **AND** MUST 发出 `clarification_resolved{outcome:"cancelled", reason:"timeout"}`

#### Scenario: 用户启用超时继续

- **WHEN** 用户将偏好改为 `continue` 且在 5 分钟内未作答
- **THEN** 系统 MUST 发 `clarification_resolved{outcome:"timeout"}`
- **AND** 工具 MUST 返回提示模型基于已知信息继续的结果，run MUST NOT 因超时被取消

### Requirement: 全局禁用澄清（用户设置）

系统 SHALL 提供用户级偏好 `clarification_enabled`（持久化于用户 profile，默认 `true`），用户 MUST 能在自己的设置中修改。当某用户 `clarification_enabled == false` 时，其发起的 run MUST NOT 向 Agent 暴露 `AskUserQuestion` 工具（不加入 `mcp_servers` / `allowed_tools`），等同从未引入该能力；模型无从发起澄清。匿名用户（无 profile）MUST 使用默认值 `true`。

#### Scenario: 用户关闭澄清后不再提问

- **WHEN** 用户将 `clarification_enabled` 设为 `false` 并发起一轮 run
- **THEN** 该 run MUST NOT 注册 `AskUserQuestion` 工具
- **AND** 即使指令不清晰，run 也 MUST NOT 发出 `clarification_request`

#### Scenario: 默认启用

- **WHEN** 新用户未修改任何澄清设置
- **THEN** `clarification_enabled` MUST 为 `true`，澄清能力可用

### Requirement: 每轮 run 最多提问次数（用户设置）

系统 SHALL 提供用户级偏好 `clarification_max_rounds`（持久化于用户 profile，默认 `5`），用户 MUST 能在自己的设置中修改。系统 MUST 为每个 run 统计 `AskUserQuestion` 的成功发起次数；当已达上限时，再次调用工具 MUST NOT 发出 `clarification_request`、MUST NOT 阻塞用户，而是直接返回一个"已达本轮提问上限，请基于已知信息自行决断"的工具结果让模型继续。匿名用户 MUST 使用默认值 `5`。

#### Scenario: 达到上限后不再阻塞

- **WHEN** 某 run 已成功发起 `clarification_max_rounds` 次 `AskUserQuestion`，模型再次调用该工具
- **THEN** 系统 MUST NOT 发出新的 `clarification_request`
- **AND** 工具 MUST 返回提示模型自行决断的结果，run 继续推进

#### Scenario: 上限内正常提问

- **WHEN** 某 run 第 `k` 次（`k <= clarification_max_rounds`）调用 `AskUserQuestion`
- **THEN** 系统 MUST 正常发出 `clarification_request` 并阻塞等待用户作答

### Requirement: 未决澄清的快照回放与会话隔离

系统 SHALL 在 run snapshot 中携带 `pending_clarifications`（未被回答/取消的 `clarification_request` 列表）。后端 MUST 在事件回放中对 `clarification_request` 入栈、`clarification_resolved` 出栈。前端 SHALL 按 `session_id` 隔离存储未决澄清，断线重连、切换会话或刷新页面后 MUST 能从 snapshot 恢复待回答的问题卡片；一个会话的澄清卡片 MUST NOT 出现在另一会话面板。

#### Scenario: 刷新后恢复未答问题

- **WHEN** 某 run 已发出 `clarification_request` 但用户尚未作答，用户刷新页面并重新订阅该 run
- **THEN** snapshot MUST 含该 `request_id` 于 `pending_clarifications`
- **AND** 前端 MUST 重新渲染该问题卡片供作答

#### Scenario: 作答后不再回放

- **WHEN** 用户已回答某 `request_id` 后重新订阅该 run
- **THEN** snapshot 的 `pending_clarifications` MUST NOT 再含该 `request_id`

#### Scenario: 跨会话隔离

- **WHEN** session A 存在未决澄清且用户切换到 session B
- **THEN** session B 面板 MUST NOT 显示 session A 的澄清卡片

### Requirement: 前端澄清问题卡片渲染

前端 SHALL 在 `AgentTraceStream` 中渲染澄清问题卡片：逐问展示 `header` 与 `question`，将 `options` 渲染为可点选按钮（`multiSelect == true` 时多选，否则单选），并在每问末尾恒提供「自定义输入」文本框。多个问题 MUST 聚合在同一卡片内，底部 MUST 提供单一「提交」按钮。提交前 MUST 做必答校验（每问需至少选中一项或填写自定义文本），未通过 MUST 阻止提交并提示。提交 MUST 调用澄清 resolve 端点，成功后 MUST 本地移除该卡片。按钮/占位符/校验提示 MUST 走 i18n；问题与选项文本来自模型（已按 `locale` 生成）直接展示。

#### Scenario: 渲染选项与自定义输入

- **WHEN** 前端收到含 2 个问题、每问 3 个 `options` 的 `clarification_request`
- **THEN** 卡片 MUST 渲染 2 个问题、各自 3 个选项按钮与 1 个自定义输入框
- **AND** 单选问题中再次点击 MUST 可切换选择，多选问题 MUST 可同时选中多个

#### Scenario: 必答校验阻止空提交

- **WHEN** 用户未对某必答问题作答即点击「提交」
- **THEN** 前端 MUST 阻止提交并提示该问题待回答

#### Scenario: 提交成功移除卡片

- **WHEN** 用户完成全部必答并提交，端点返回 200
- **THEN** 前端 MUST 移除该澄清卡片
- **AND** 后续 trace（如 `clarification_resolved` 与继续的步骤）MUST 正常渲染
