## 1. 数据模型与迁移

- [x] 1.1 在 `app/models/`（新建 `conversation_share.py` 或并入现有模块）新增 `ConversationShare` 模型：`id`、`token`(unique index)、`session_id`(FK→chat_sessions, index)、`user_id`(FK→users, index)、`title`、`snapshot_json`(Text)、`message_count`、`is_active`(default true)、`shared_at`，并混入 `TimestampMixin`
- [x] 1.2 在 `app/models/__init__.py` 导出新模型，确保被 metadata 注册
- [x] 1.3 新增 Alembic 迁移创建 `conversation_shares` 表（含 `token` unique、`session_id` / `user_id` 索引）
- [x] 1.4 在 `app/config.py` / `.env.example` 增加站点公开根地址配置（如 `PUBLIC_BASE_URL`，缺省回退请求 Origin）

## 2. 分享服务层（脱敏与生命周期）

- [x] 2.1 新增 `conversation_share_service`（或扩展 `chat_history_service`）：`create_or_refresh_share(session_id, user_id)` 校验 owner 与非空，捕获消息并构建仅含 `role`/`content`/`created_at` 的脱敏快照 JSON，生成 `secrets.token_urlsafe(16)` token，对已存在活跃分享执行 upsert（复用 token、刷新快照与 `shared_at`）
- [x] 2.2 实现 `get_share_for_session(session_id, user_id)` 返回当前活跃分享状态
- [x] 2.3 实现 `revoke_share(session_id, user_id)` 置 `is_active=false`
- [x] 2.4 实现 `get_public_snapshot(token)` 仅返回 `is_active=true` 记录的 `title`/`shared_at`/`message_count`/messages，找不到或已撤销返回 None
- [x] 2.5 单元测试覆盖：脱敏只保留三字段、快照不含 trace/owner 身份、空会话被拒、upsert 复用 token、撤销后 `get_public_snapshot` 返回 None

## 3. Owner 侧 API（鉴权）

- [x] 3.1 在 `app/api/users.py` 新增 `POST /users/chat-sessions/{session_id}/share`（`get_current_user`，按 `user_id` 隔离），返回 `{ token, share_url, shared_at, message_count, is_active }`；空会话返回 4xx
- [x] 3.2 新增 `GET /users/chat-sessions/{session_id}/share` 查询分享状态（未分享返回未分享态）
- [x] 3.3 新增 `DELETE /users/chat-sessions/{session_id}/share` 撤销分享
- [x] 3.4 定义对应 Pydantic 响应模型（`ShareInfoResponse` 等），`share_url` 由 base URL 拼接
- [x] 3.5 API 测试：非 owner 访问返回 404/403、空会话被拒、创建后查询/撤销闭环

## 4. 公开侧 API（不鉴权 + 限流）

- [x] 4.1 新增 `app/api/share.py` 独立 router，`GET /api/v1/share/{token}` 不挂任何用户鉴权依赖，返回 `{ title, shared_at, message_count, messages:[{role,content,created_at}] }`，无效/撤销 token 返回 404（API 路径加 `/api/v1` 前缀以与同源 SPA 页面路由 `/share/:token` 共存；公开页 URL 仍为 `/share/:token`）
- [x] 4.2 在 `app/main.py` 注册公开 router（确认未被全局鉴权中间件拦截）
- [x] 4.3 为公开端点接入按 IP 的基础限流（复用现有中间件/依赖或新增），超额返回 429
- [x] 4.4 API 测试：无 Authorization 头可读取、响应不含 `user_id`/`username`/`email`/`session_id`/trace、404 不泄露存在性、限流生效

## 5. 前端 API 客户端与类型

- [x] 5.1 在 `frontend/src/api/`（`chat.ts` 或新增 `share.ts`）新增 owner 侧分享接口：create/refresh、get、revoke
- [x] 5.2 新增公开快照获取接口（不带鉴权头），供公开页调用
- [x] 5.3 在 `frontend/src/types/` 补充分享相关类型定义

## 6. 前端分享弹窗与菜单入口

- [x] 6.1 新增 `components/ShareConversationModal.vue`：未分享态「生成公开链接」；已分享态展示只读链接框、复制、打开预览、更新分享、取消分享，并显式展示快照时间与「持链接者均可查看」提示（生命周期逻辑抽到 `composables/useConversationShare.ts` 以便测试）
- [x] 6.2 接线 `AIChat.vue` 三点菜单「分享对话」项 [AIChat.vue:1586](frontend/src/views/AIChat.vue:1586) 打开弹窗；当前会话 0 消息时禁用/隐藏该入口（`canShareConversation` 计算属性 + `v-if` 隐藏入口）
- [x] 6.3 复制成功 / 撤销 / 更新走现有 notification store 反馈
- [x] 6.4 组件测试：状态切换（未分享↔已分享）、复制写入剪贴板（`useConversationShare.spec.ts`）；空会话入口由 `canShareConversation` 结构性保证（SSR-only 测试环境下不直接挂载 AIChat）

## 7. 前端公开只读页

- [x] 7.1 抽出主对话消息的 Markdown/Mermaid/代码块渲染为可复用 util 或组件，供主对话与公开页共用（既有 `@/utils/markdownRenderer` 的 `renderMarkdown` + `processMermaidBlocks` 已是可复用单点，公开页与主对话共用之）
- [x] 7.2 新增 `views/SharedConversation.vue`：按 `:token` 拉公开快照，只读渲染对话历史，含品牌头与回首页 CTA，无输入框/菜单/侧边栏，不显示 owner 身份
- [x] 7.3 在 `frontend/src/router/index.ts` 新增顶层路由 `/share/:token`（置于 `WorkbenchLayout` 之外，无需登录守卫）
- [x] 7.4 实现失效/不存在 token 的空态（公开接口 404 → 友好提示 + CTA，不暴露内容）
- [x] 7.5 页面测试：加载状态机（有效 token→渲染数据、404→空态、缺 token→空态）+ Markdown/Mermaid 渲染产物对齐（`useSharedConversation.spec.ts`）

## 8. 国际化

- [x] 8.1 在 `frontend/src/i18n/` 中英文件补齐分享弹窗（`aiChat.share.*`）、公开页（`sharedConversation.*`）、错误/空态文案，并新增 `router.sharedConversation`
- [x] 8.2 校验中英两套 key 完整对齐，无缺失（`catalog-parity.spec.ts` 通过）

## 9. 验证与文档

- [x] 9.1 端到端闭环已由自动化 API 测试覆盖（创建→查询→公开读取→撤销→404，见 `tests/api/test_conversation_share.py`）；浏览器手测步骤已写入 `DEPLOY_USAGE.md`，留待人工在真实环境走查
- [x] 9.2 安全核对：公开响应无身份/内部字段、token 不可枚举、限流生效、撤销即时失效（均有对应自动化断言：`test_public_read_without_auth_and_no_identity_leak` / `test_public_endpoint_rate_limited` / `test_public_revoked_token_returns_404` + 服务层脱敏测试）
- [x] 9.3 更新文档（`DEPLOY_USAGE.md` 新增「对话分享」章节）与 `.env.example` 的 `PUBLIC_BASE_URL` / 限流变量说明
