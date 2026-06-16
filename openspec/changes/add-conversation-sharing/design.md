## Context

对话历史已持久化为 `chat_sessions` + `chat_messages`（`app/models/user.py`），消息 `role ∈ {user, ai}`、`content` 为 Markdown，AI 回合的 agent 步骤另存于 `chat_agent_runs.trace_events_json`。会话读取走 `/users/chat-sessions/*`（`app/api/users.py`），全部要求 `get_current_user` 鉴权且按 `user_id` 隔离。前端 `AIChat.vue` 三点菜单已有「重命名 / 置顶 / 导出 Markdown / 删除」等动作，并已实现 `exportCurrentConversationMarkdown` 可作为快照取数参考；「分享对话」项 [AIChat.vue:1586](frontend/src/views/AIChat.vue:1586) 当前为空占位。所有业务路由都嵌套在需登录的 `WorkbenchLayout` 之下。

本设计要新增的核心是系统第一个**公开未鉴权读取面**，因此安全边界是首要约束。

## Goals / Non-Goals

**Goals:**

- 用户可对任一非空会话生成一个公开、只读、可撤销的分享链接。
- 任何持链接者无需登录即可在独立页面查看对话历史，渲染效果对齐主对话（Markdown / Mermaid / 代码块）。
- 分享采用快照语义：分享后会话的增删改不影响已分享内容，owner 可显式「更新分享」刷新快照。
- 公开面不泄露 owner 身份（用户名 / 邮箱）与内部 agent trace。
- owner 可随时撤销分享，撤销后链接立即失效。

**Non-Goals:**

- 不做密码保护链接、有效期 / 过期时间、访问次数限制（留作后续增强）。
- 不做「继续对话 / fork 到自己账号」（ChatGPT 的 Continue 能力）。
- 不做分享给指定用户的细粒度 ACL；只有「公开链接」与「未分享」两态。
- 不导出 / 呈现 agent trace 步骤、设备清单等内部数据。
- 匿名（未登录）会话不支持分享（无 owner 归属）。

## Decisions

### 决策 1：快照存储而非实时引用

分享记录持久化一份**消息快照 JSON**（`snapshot_json`），而不是在公开读取时实时 join `chat_messages`。

- **理由**：(a) 与 ChatGPT 行为一致，分享内容稳定可预期；(b) 解耦会话生命周期——owner 之后删除会话 / 消息或继续追问都不会改变或破坏已分享链接；(c) 公开读取路径不触碰用户私有表，缩小泄露面，便于在快照阶段一次性做脱敏。
- **代价**：数据冗余；快照需要 owner 主动「更新分享」才会刷新。可接受。
- **Alternatives considered**：实时引用 `session_id` + `shared_at`，按 `created_at <= shared_at` 过滤消息。否决：owner 删消息会令分享内容凭空消失，且公开路径需读私有表、脱敏逻辑分散。

### 决策 2：分享标识用不可猜测 token，与 session_id 解耦

公开 URL 形如 `/share/{token}`，`token = secrets.token_urlsafe(16)`（约 22 字符，~128bit 熵），表内唯一索引。绝不把 `session_id` / `user_id` 暴露到公开 URL 或公开响应里。

- **理由**：避免枚举；撤销 = 删除 / 置 `is_active=false` 该 token 记录，不影响会话本身；同一会话可先撤销再重新分享得到新 token。
- **Alternatives considered**：直接用 `session_id` 当公开标识。否决：可枚举、且撤销语义与会话耦合。

### 决策 3：数据模型 `conversation_shares`

新增表（`app/models/`，建议 `conversation_share.py` 或并入 `user.py` 同模块），字段：

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `id` | String(36) PK | uuid |
| `token` | String(32) unique index | 公开标识，`token_urlsafe(16)` |
| `session_id` | String(36) FK→chat_sessions.id, index | 来源会话（用于 owner 侧反查 / 去重） |
| `user_id` | String(36) FK→users.id, index | owner，用于权限校验 |
| `title` | String(255) | 快照时的会话标题 |
| `snapshot_json` | Text | 脱敏后的消息数组 JSON：`[{role, content, created_at}]` |
| `message_count` | Integer | 快照消息数（列表 / 展示用） |
| `is_active` | Boolean default true | 撤销置 false（软撤销，便于审计 / 复用 token 可选） |
| `shared_at` | DateTime | 最近一次生成 / 更新快照时间 |
| + `TimestampMixin` | | `created_at` / `updated_at` |

一个 session 同时最多保留一条 `is_active=true` 记录（创建时 upsert：已存在活跃分享则刷新快照与 `shared_at`，返回同一 token）。

### 决策 4：API 形态

owner 侧（鉴权，挂 `app/api/users.py`，复用 `get_current_user` + `user_id` 隔离）：

- `POST /users/chat-sessions/{session_id}/share` → 创建或刷新分享，返回 `{ token, share_url, shared_at, message_count, is_active }`。空会话返回 422 / 400。
- `GET /users/chat-sessions/{session_id}/share` → 查询当前分享状态（无则 `is_active=false` / 空）。
- `DELETE /users/chat-sessions/{session_id}/share` → 撤销（置 `is_active=false`）。

公开侧（**不鉴权**，新建 `app/api/share.py`，独立 router，避免误挂鉴权依赖）：

- `GET /api/v1/share/{token}` → 返回 `{ title, shared_at, messages: [{role, content, created_at}], message_count }`。`token` 不存在或 `is_active=false` → 404。响应**绝不含** `user_id` / `username` / `email` / `session_id` / trace。
- **路径前缀说明（实现期修订）**：JSON 公开端点采用 `/api/v1/share/{token}`（沿用项目既有公开 API 约定，如 `/api/v1/releases`），而非裸 `/share/{token}`。原因：前端 `API_BASE_URL` 默认取 `window.location.origin`，同源部署下裸 `/share/{token}` 会与 SPA 公开**页面**路由 `/share/:token` 冲突。面向用户的公开页 URL 仍为 `/share/:token`（由 `share_url` 指向），SPA 页面再调用 `/api/v1/share/{token}` 拉取 JSON。

`share_url` 由后端基于配置的站点 base URL（`app/config.py` 现有配置项 / 新增 `PUBLIC_BASE_URL`）拼成完整链接，前端直接复制。

### 决策 5：快照脱敏在写入时完成

生成快照时只取 `chat_messages` 的 `role` / `content` / `created_at`，**显式丢弃** trace、run 关联、owner 身份。公开读取直接回吐 `snapshot_json`，不二次组装，保证脱敏单点收口。

### 决策 6：前端——分享弹窗 + 独立公开页

- **分享入口**：`AIChat.vue` 三点菜单「分享对话」改为打开 `ShareConversationModal`（新组件，置于 `components/`）。空会话时该菜单项禁用 / 隐藏。
- **分享弹窗**：未分享态展示「生成公开链接」按钮；已分享态展示只读链接框 + 复制按钮、「打开预览」「更新分享」「取消分享」。复制成功走现有 notification store。
- **公开页**：新增 `views/SharedConversation.vue`，路由 `/share/:token` **挂在 `WorkbenchLayout` 之外**（顶层路由，无侧边栏 / 无导航 / 无输入框）。挂载时按 `:token` 拉公开接口，复用主对话的 Markdown / Mermaid 渲染逻辑只读呈现；含轻量品牌头（标题 + RavenAI 标识）与「失效 / 不存在」空态；提供回首页 CTA。
- 复用现有渲染：将 `AIChat.vue` 中消息 Markdown / Mermaid 渲染抽出为可复用 util / 组件，供公开页与主对话共用，避免分叉。

## Risks / Trade-offs

- **公开未鉴权面泄露风险** → 公开接口独立 router、绝不依赖也绝不返回任何身份 / 内部字段；token 高熵不可枚举；快照写入时单点脱敏；为公开端点加基础限流（按 IP）防扫描。
- **快照陈旧（owner 以为分享是实时的）** → 弹窗明确标注「分享的是 {shared_at} 时刻的快照」并提供「更新分享」；已分享态显式展示快照时间。
- **撤销后链接仍被缓存 / 已打开页面仍可见** → 撤销即 `is_active=false`，公开接口立即 404；前端公开页对已加载内容不做额外保护（与 ChatGPT 一致，撤销只断新访问）。
- **敏感内容仍可能在 message content 内**（用户把私密信息写进对话正文）→ 分享是 owner 显式动作并二次确认；弹窗提示「链接持有者均可查看」；超出本期范围的更强管控（密码 / 过期）列入 Non-Goals。
- **站点 base URL 配置缺失导致 share_url 错误** → `PUBLIC_BASE_URL` 缺省时回退请求 `Origin` / 配置默认值，并在文档与 `.env.example` 注明。
- **数据冗余增长** → 每会话至多一条活跃快照；撤销可硬删历史记录（实现可选软删 + 定期清理）。

## Migration Plan

1. Alembic 新增 `conversation_shares` 表迁移（含 `token` unique、`session_id` / `user_id` index）。向前兼容，无数据回填。
2. 后端上线 owner 侧 + 公开侧接口与服务；为公开端点接入限流。
3. 前端上线分享弹窗、公开路由与页面、i18n。
4. 回滚：前端隐藏分享入口即停用功能；后端表与接口可保留（无破坏性）。彻底回滚则 drop 表 + 移除路由。

## Open Questions

- `share_url` 的站点根地址来源：复用现有配置项还是新增 `PUBLIC_BASE_URL`？（倾向新增，缺省回退 Origin。）
- 撤销采用软撤销（`is_active=false`，保留审计）还是硬删？（倾向软撤销。）
- 是否需要「谁查看过 / 浏览计数」？本期默认不做，预留 `snapshot_json` 之外的扩展位。
