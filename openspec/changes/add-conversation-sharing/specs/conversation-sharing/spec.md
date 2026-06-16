## ADDED Requirements

### Requirement: 会话 owner 创建分享生成不可猜测公开 token

系统 SHALL 允许会话 owner 对自己的非空会话创建公开分享。创建时 MUST 生成一个高熵、不可猜测的 token（`secrets.token_urlsafe(16)` 量级，约 128bit 熵）作为公开标识，并持久化为 `conversation_shares` 记录（含 `token`、`session_id`、`user_id`、`title`、`snapshot_json`、`message_count`、`is_active`、`shared_at`）。公开标识 MUST 与 `session_id` / `user_id` 解耦，绝不把后者暴露到公开 URL 或公开响应。

#### Scenario: 对非空会话创建分享

- **WHEN** owner 对一个含 ≥1 条消息的会话调用 `POST /users/chat-sessions/{session_id}/share`
- **THEN** 系统 MUST 创建一条 `is_active=true` 的分享记录并生成唯一 token
- **AND** 响应 MUST 返回 `token`、可直接打开的完整 `share_url`、`shared_at` 与 `message_count`

#### Scenario: 拒绝分享空会话

- **WHEN** owner 对一个 0 条消息的会话请求创建分享
- **THEN** 系统 MUST 拒绝并返回 4xx 错误
- **AND** MUST NOT 创建分享记录

#### Scenario: token 不可枚举

- **WHEN** 生成多个分享
- **THEN** 每个 token MUST 唯一且不可由 `session_id` / 自增序号 / 时间戳推导

### Requirement: 分享采用快照语义且可刷新

分享内容 SHALL 为创建 / 更新时刻捕获的消息**快照**，持久化于 `snapshot_json`。会话在分享后新增、删除或修改消息 MUST NOT 改变已分享快照。同一会话同时至多保留一条 `is_active=true` 分享；owner 重复调用创建接口 MUST 刷新该会话现有活跃分享的快照与 `shared_at`，并复用同一 token（不产生第二条活跃记录）。

#### Scenario: 分享后新增消息不影响快照

- **WHEN** 会话在 t0 被分享（含 3 条消息）
- **AND** owner 之后在该会话继续发送消息
- **THEN** 通过该分享链接读取到的内容 MUST 仍为 t0 的 3 条消息

#### Scenario: 更新分享刷新快照

- **WHEN** 已存在活跃分享的会话再次调用创建 / 更新分享接口
- **THEN** 系统 MUST 用最新消息覆盖 `snapshot_json` 并更新 `shared_at`
- **AND** MUST 复用同一 token，MUST NOT 新增第二条活跃分享记录

### Requirement: 公开只读读取接口无需鉴权

系统 SHALL 提供公开端点 `GET /share/{token}`，无需登录即可读取对应快照。该端点 MUST 由独立 router 提供，MUST NOT 挂载任何用户鉴权依赖。响应 MUST 仅包含 `title`、`shared_at`、`message_count` 与消息数组（每条仅 `role`、`content`、`created_at`）。

#### Scenario: 持链接者读取快照

- **WHEN** 未登录访问者请求一个有效 token 的 `GET /share/{token}`
- **THEN** 系统 MUST 返回该快照的标题与消息列表
- **AND** MUST NOT 要求任何认证头

#### Scenario: 无效或已撤销 token 返回不存在

- **WHEN** 请求的 token 不存在，或对应分享 `is_active=false`
- **THEN** 系统 MUST 返回 404
- **AND** MUST NOT 透露该 token 是否曾经存在过

### Requirement: 公开响应不泄露身份与内部数据

公开读取面 SHALL 不暴露任何 owner 身份信息或系统内部数据。`snapshot_json` MUST 在写入时完成脱敏：仅保留消息的 `role` / `content` / `created_at`，MUST 丢弃 owner 的 `user_id` / `username` / `email`、`session_id`，以及 agent trace 步骤（`trace_events_json`）、run 关联、设备 / 日志内部明细。公开响应 MUST NOT 包含上述被丢弃字段。

#### Scenario: 公开响应不含身份字段

- **WHEN** 任意访问者读取 `GET /share/{token}`
- **THEN** 响应 MUST NOT 包含 `user_id`、`username`、`email`、`session_id`
- **AND** 响应 MUST NOT 包含 agent trace 事件或设备 / 日志内部数据

#### Scenario: 快照写入即脱敏

- **WHEN** 创建 / 更新分享生成 `snapshot_json`
- **THEN** 系统 MUST 仅从消息中提取 `role` / `content` / `created_at`
- **AND** MUST NOT 写入 trace、run 或 owner 身份字段

### Requirement: 仅 owner 可管理分享且撤销即时生效

系统 SHALL 仅允许会话 owner 创建、查询、撤销其会话的分享，按 `user_id` 严格隔离。owner 调用 `DELETE /users/chat-sessions/{session_id}/share` 撤销后，对应分享 MUST 立即不可经公开端点访问（`is_active=false` → `GET /share/{token}` 返回 404）。

#### Scenario: 非 owner 无法管理他人分享

- **WHEN** 用户 B 对用户 A 的会话调用分享创建 / 查询 / 撤销接口
- **THEN** 系统 MUST 拒绝（404 / 403），MUST NOT 暴露会话存在性或内容

#### Scenario: 撤销后链接立即失效

- **WHEN** owner 撤销某会话的分享
- **THEN** 之后对该 token 的 `GET /share/{token}` MUST 返回 404

#### Scenario: 查询当前分享状态

- **WHEN** owner 调用 `GET /users/chat-sessions/{session_id}/share`
- **THEN** 系统 MUST 返回该会话是否存在活跃分享、token / share_url 与 `shared_at`（无活跃分享时返回未分享态）

### Requirement: 公开端点具备防扫描限流

系统 SHALL 对公开 `GET /share/{token}` 端点按来源（如 IP）施加基础限流，以抑制对 token 空间的扫描枚举。超过阈值的请求 MUST 被拒绝（如 429）。

#### Scenario: 高频请求被限流

- **WHEN** 同一来源在短时间内对 `/share/{token}` 发起超过阈值的请求
- **THEN** 系统 MUST 对超额请求返回限流响应（429）而非继续查询
