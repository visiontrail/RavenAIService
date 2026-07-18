## ADDED Requirements

### Requirement: 前端会话状态按 session 隔离

前端 SHALL 将对话消息、发送状态、active run、SSE subscription、pending permissions 按 `session_id` 存储。`AIChat.vue` MUST 渲染当前选中 session 的状态，而不是维护单例 `chatHistory/sessionId/isSending/pendingPermissions`。

#### Scenario: A 会话流式输出不写入 B 会话

- **WHEN** session A 的 run 正在流式输出
- **AND** 用户切换到 session B
- **AND** session A 后续又收到 `step_delta` 或 `run_complete`
- **THEN** 这些事件 MUST 更新 session A 的 state
- **AND** session B 当前面板 MUST NOT 出现 session A 的消息、trace 或最终答案

#### Scenario: B 会话可在 A 运行时发送

- **WHEN** session A `isSending == true`
- **AND** 用户切换到 session B，且 session B 没有 active run
- **THEN** session B 的输入框和发送按钮 MUST 可用
- **AND** session B 发送后 MUST 创建独立 run

### Requirement: 侧边栏显示运行中会话

会话历史侧边栏 SHALL 对每个 `run_status == "running"` 或本地 overlay 标记为 running 的 session 显示转圈等待图标。该图标 MUST 与更多菜单、标题截断和 active row 状态共存，不遮挡会话标题的可读区域。

#### Scenario: 发送后侧边栏立即转圈

- **WHEN** 用户在 session A 发送消息并创建 run
- **THEN** session A 的侧边栏行 MUST 在收到首个 `run_start` 前后立即显示 spinner
- **AND** 用户切换到其它会话后 spinner MUST 继续显示直到 session A run 终态

#### Scenario: run 终态后 spinner 消失

- **WHEN** session A 收到 `run_complete`、`cancelled`、`error` 或 `stale` 状态
- **THEN** session A 的侧边栏 spinner MUST 消失

### Requirement: 点击运行中会话恢复 run

用户点击运行中的会话历史项时，前端 SHALL 加载该 session 的 DB 历史消息，查询 active run snapshot，并订阅该 run 的 stream。页面 MUST 恢复本轮 user message、assistant 占位、已有 trace events、pending permission 弹窗和后续实时输出。

#### Scenario: 恢复 trace

- **WHEN** session A 离开期间产生了 10 条 trace event
- **AND** 用户点击 session A
- **THEN** `AgentTraceStream` MUST 渲染这 10 条事件
- **AND** 后续事件 MUST 继续追加到同一个 assistant 消息

#### Scenario: 恢复 pending permission

- **WHEN** session A 离开期间产生了 `tool_permission_request`
- **AND** 该 request 尚未超时或被裁决
- **THEN** 用户点击 session A 后 MUST 重新看到对应 HITL 确认弹窗
- **AND** allow/deny MUST POST 到带 `run_id` 的 resolve API

### Requirement: 切换会话只断开订阅，不取消 run

前端 SHALL 在切换当前 session 时 abort 旧 session 的 SSE reader，以释放浏览器连接；该 abort MUST NOT 调用后端 cancel API，也 MUST NOT 将旧 session run 标记为失败。

#### Scenario: 离开会话不中断后台任务

- **WHEN** 用户从 session A 切换到 session B
- **THEN** 前端 MAY 关闭 session A 的本地 SSE subscription
- **BUT** 后端 session A run MUST 继续运行
- **AND** session A 侧边栏 spinner MUST 保持

### Requirement: 当前 session 内 active run 禁止重复发送

当前选中 session 有 active run 时，输入框发送按钮 SHALL 禁用，或在点击发送时显示同 session 正在运行的提示。其它 session 的 active run MUST NOT 影响当前 session。

#### Scenario: 同一会话禁止第二条消息

- **WHEN** 当前 session A 已有 active run
- **THEN** session A 的发送按钮 MUST 禁用
- **AND** 前端 MUST NOT 再向 `/chat/stream` 创建第二条 run

### Requirement: Run event 按 run_id 去重与路由

前端 SHALL 使用 `(run_id, seq)` 作为 trace event 去重键，并将 payload 路由到匹配 `session_id/run_id` 的 conversation state。缺少或不匹配当前 state 的事件 MUST 被忽略或记录调试日志，MUST NOT 写入当前可见会话。

#### Scenario: 两个 run 的 seq 都从 1 开始

- **WHEN** session A run 与 session B run 都发出 `seq == 1`
- **THEN** 前端 MUST 保留两条事件
- **AND** 它们 MUST 分别进入各自 session 的 traceEvents

### Requirement: LogAnalysis 与 DeviceAgent 使用统一前端运行态

主对话中的 DeviceAgent run 与 LogAnalysisAgent run SHALL 使用同一套 session-scoped running state。日志分析的取消按钮、trace、侧边栏 spinner、切会话恢复行为 MUST 与 DeviceAgent 一致。

#### Scenario: 日志分析运行时另开设备对话

- **WHEN** session A 正在进行日志分析
- **AND** 用户切换到 session B 并发送设备对话
- **THEN** session B MUST 能创建 DeviceAgent run
- **AND** session A 的日志分析 run MUST 继续在后台运行

#### Scenario: 回到日志分析会话可取消

- **WHEN** session A 的日志分析 run 仍在运行
- **AND** 用户重新点击 session A
- **THEN** 页面 MUST 恢复日志分析 trace
- **AND** 取消按钮 MUST 可用并只取消 session A 的 run


### Requirement: Project selection surfaces project-card guidance
The chat project's selector SHALL expose a bounded project-card summary together with each project name/code, and SHALL make the complete card available as accessible/title guidance. The admin project create/edit UI SHALL label the field “Project Card”, mark it required, explain that Agents use it for matching, and prevent submission while it is blank.

#### Scenario: User compares project cards before selection
- **WHEN** the project selector is open for a project-bound Agent
- **THEN** each option shows the project name/code and a project-card summary
- **AND** the full project card is available as option guidance

#### Scenario: Admin cannot save a blank card
- **WHEN** an administrator leaves Project Card blank in the create/edit dialog
- **THEN** the Save action reports that the project card is required
- **AND** no create/update request is sent
