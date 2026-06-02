## ADDED Requirements

### Requirement: Agent run 生命周期独立于 SSE 连接

系统 SHALL 将每一轮会话 Agent 执行建模为 `ChatAgentRun`，并由后端后台 task 驱动。`POST /api/v1/ai-chat/chat/stream` 或 run stream 端点建立的 SSE 连接 SHALL 只是该 run 的订阅者；客户端断开、切换会话或关闭当前页面 MUST NOT 自动取消后台 run。

每个 run MUST 至少具有 `run_id`、`session_id`、`owner_scope`、`agent_kind`、`status`、`started_at`、`updated_at`，且所有 SSE payload MUST 携带 `run_id` 与 `session_id`。`owner_scope` MUST NOT 下发给普通前端，但后端所有 run lookup MUST 使用它做归属隔离。

#### Scenario: SSE 断开后 run 继续完成

- **WHEN** 用户在 session A 中发送消息并收到 `run_start`
- **AND** 浏览器在 run 尚未完成时断开该 SSE 连接
- **THEN** 后端 MUST 继续执行该 Agent loop
- **AND** run 完成后 MUST 持久化终态 answer/status
- **AND** 重新订阅该 `run_id` MUST 能收到从 `run_start` 到 terminal event 的完整事件序列

#### Scenario: 切换会话不取消 run

- **WHEN** 用户从正在运行的 session A 切换到 session B
- **THEN** session A 的 run MUST 保持 `running`
- **AND** session B MUST 能独立发送新消息并创建自己的 run

### Requirement: 多 session 并发与单 session 互斥

系统 SHALL 允许同一用户的多个不同 `session_id` 同时拥有 active run。系统 SHALL 禁止同一 `owner_scope + session_id` 同时拥有多个 active run；当同一用户的同一 session 已有 `queued` 或 `running` run 时，新的用户消息 MUST 被拒绝或在前端禁用。

#### Scenario: 两个会话同时运行

- **WHEN** session A 与 session B 分别发送一条 DeviceAgent 消息
- **THEN** 后端 MUST 创建两个不同的 `run_id`
- **AND** 两个 run MUST 能并发推进，各自发出 `run_start`、trace events 与 terminal event
- **AND** session A 的事件 MUST NOT 出现在 session B 的订阅流中，反之亦然

#### Scenario: 同一会话 active 时拒绝第二条消息

- **WHEN** session A 已有 `status == "running"` 的 run
- **AND** 前端或其它客户端再次向 session A 发送新消息
- **THEN** 后端 MUST 返回 HTTP 409
- **AND** 响应 MUST 包含当前 `active_run_id`

### Requirement: 多用户 run 归属隔离

系统 SHALL 将所有 active run registry、DB 查询、snapshot、stream、cancel、permission resolve 和 session summary overlay 按 `owner_scope` 隔离。登录用户的 `owner_scope` MUST 从认证用户 ID 派生；匿名用户的 `owner_scope` MUST 由服务端生成的匿名 scope 派生。后端 MUST NOT 仅凭裸 `session_id` 查找或操作 active run。

不同用户即使提交相同 `session_id`，也 SHALL 被视为不同会话作用域。任一用户 MUST NOT 能读取、订阅、取消、裁决或在侧边栏看到其它用户的 run。

#### Scenario: 两个用户使用相同 session_id 同时运行

- **WHEN** user A 与 user B 都使用 `session_id == "same-session"` 发送 DeviceAgent 消息
- **THEN** 后端 MUST 创建两个不同的 `run_id`
- **AND** active run lookup MUST 分别以 `(owner_scope(user A), "same-session")` 与 `(owner_scope(user B), "same-session")` 命中各自 run
- **AND** user A 的第二条同 session 消息 MUST 只与 user A 的 active run 冲突，不得影响 user B

#### Scenario: 用户不能订阅其它用户 run

- **WHEN** user A 拥有 `run_id == run-a`
- **AND** user B 请求 `GET /api/v1/ai-chat/chat/runs/run-a/stream`
- **THEN** 后端 MUST 返回 HTTP 404 或 403
- **AND** MUST NOT 发送任何 run-a 的事件、answer、pending permission 或错误细节

#### Scenario: 会话列表只显示当前用户运行态

- **WHEN** user A 与 user B 都有 running run
- **AND** user A 请求 `GET /api/v1/users/chat-sessions`
- **THEN** 响应中的 `active_run_id/run_status` MUST 只包含 user A 自己 session 的 run
- **AND** user B 的 running run MUST NOT 影响 user A 侧边栏 spinner

### Requirement: Run 事件缓冲与重放

系统 SHALL 为每个 active run 维护有序事件缓冲。订阅者连接时，服务端 MUST 从缓冲开头按产生顺序重放全部事件，然后继续推送新事件，直到 run 进入终态。事件去重键 SHALL 为 `(run_id, seq)`。

缓冲中 MUST 包含 DeviceAgent 标准 `AgentTraceEvent`、device-agent-specific events（`tool_permission_request`、`tool_permission_resolved`、`result_validation`）以及 terminal `done/error/cancelled` 语义所需 payload。

#### Scenario: 晚到订阅者收到完整历史

- **WHEN** run 已经产生 seq=1..30 的事件
- **AND** 用户此时点击对应历史会话
- **THEN** 新订阅流 MUST 先按序发送 seq=1..30
- **AND** 后续 seq=31..N MUST 实时接续推送

#### Scenario: 重放时 seq 保持不变

- **WHEN** 同一个 run 被两个浏览器窗口先后订阅
- **THEN** 两个订阅者看到的相同事件 MUST 拥有相同 `run_id` 与 `seq`

### Requirement: Run 快照支持恢复正在生成的消息

系统 SHALL 提供按 `session_id` 查询 active run 和按 `run_id` 查询 run snapshot 的 API。snapshot MUST 包含足够信息让前端恢复正在生成中的 assistant 消息：`status`、`agent_kind`、`answer_so_far`（如有）、`trace_events`、`pending_permissions`、`started_at`、`updated_at`。

#### Scenario: 点击运行中的历史会话恢复内容

- **WHEN** 用户离开 session A 后，session A 的 run 产生了若干 trace event
- **AND** 用户在侧边栏点击 session A
- **THEN** 前端 MUST 能通过 active-run/snapshot API 恢复本轮用户消息、assistant 占位、已有 trace events 与 pending permission 状态
- **AND** 随后打开 stream 订阅继续接收新事件

### Requirement: Run 结果持久化

系统 SHALL 在 run 开始时立即持久化本轮用户消息，并在 run 进入终态时持久化 assistant 终态消息。终态 run 的 `answer`、`model`、`error`、`trace_events` MUST 写入 `chat_agent_runs`，以支持刷新页面后的历史回放和排查。

#### Scenario: 运行中用户消息已可见

- **WHEN** 用户发送消息后立即离开当前会话
- **THEN** `GET /api/v1/users/chat-sessions/{session_id}/messages` MUST 至少返回刚发送的 user message
- **AND** active-run snapshot MUST 提供对应 assistant 虚拟消息

#### Scenario: 完成后历史只依赖 DB 消息

- **WHEN** run 成功完成并持久化
- **THEN** 再次加载该 session messages MUST 返回本轮 user 与 assistant 两条真实 DB 消息
- **AND** 前端 MUST NOT 继续显示该 run 的虚拟 assistant 占位

### Requirement: Run-scoped DeviceAgent 工作区

DeviceAgent SHALL 为每个 run 创建独立工作区，路径 MUST 包含安全化后的 `owner_scope`、`session_id` 与 `run_id` 或其它等价唯一标识。不同 run MUST NOT 共用 `.claude/skills` 目录、临时文件目录或 trace state。

#### Scenario: 并发 run 使用不同工作路径

- **WHEN** session A 与 session B 同时启动 DeviceAgent run
- **THEN** 两个 run 的 `workspace_path` MUST 不同
- **AND** 路径 MUST 能从各自 `chat_agent_runs.workspace_path` 查询到
- **AND** run 完成后工作区 MUST 按清理策略被删除或标记为待清理

#### Scenario: 不同用户相同 session_id 工作区不同

- **WHEN** user A 与 user B 都使用 `session_id == "same-session"` 启动 run
- **THEN** 两个 run 的 `workspace_path` MUST 位于不同 `owner_scope` 目录下或以其它等价方式隔离
- **AND** 任何 Skill 物化目录 MUST NOT 被两个用户共享

### Requirement: PermissionBroker 按 run 定位

系统 SHALL 按 `run_id` 注册 DeviceAgent HITL `PermissionBroker`。`tool_permission_request` 事件 MUST 包含 `run_id`、`session_id` 与 `request_id`。权限裁决端点 MUST 优先使用 `run_id` 定位 broker，并校验该 run 属于当前用户。任何按 `session_id` 或 legacy scan 的 fallback 都 MUST 限定在当前 `owner_scope` 内。

#### Scenario: 两个 run 同时等待权限

- **WHEN** session A 与 session B 同时产生 `tool_permission_request`
- **AND** 前端对 session A 的 `request_id` 提交 allow，body 携带 session A 的 `run_id`
- **THEN** 只有 session A 的 run 被解锁
- **AND** session B 的 pending request MUST 保持等待

#### Scenario: 用户不能裁决其它用户权限请求

- **WHEN** user A 的 run 产生 `request_id == req-a`
- **AND** user B 向 `/chat/permissions/req-a/resolve` 提交 allow，即使 body 携带 `run_id` 或 `session_id`
- **THEN** 后端 MUST 返回 HTTP 404 或 403
- **AND** user A 的 pending permission MUST 保持等待直到 user A 裁决或超时

### Requirement: Stale run 处理

服务进程启动时，系统 SHALL 将持久化表中仍为 `queued` 或 `running` 的 run 标记为 `stale`，并记录错误说明。前端 MUST 将 `stale` 视为终态，不显示无限 spinner。

#### Scenario: 服务重启后不会永久转圈

- **WHEN** 服务重启前存在 `status == "running"` 的 run
- **THEN** 服务启动后该 run MUST 被标记为 `stale`
- **AND** 对应 session summary MUST NOT 再显示 running spinner
