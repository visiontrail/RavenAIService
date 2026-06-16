## Why

对话面板右上角三点菜单中的「分享对话」目前是一个空占位（[AIChat.vue:1586](frontend/src/views/AIChat.vue:1586) 仅关闭菜单，无任何行为）。用户无法把一段有价值的排障 / 项目分析对话分享给同事或外部协作者查看。对标 Claude / ChatGPT，缺少一个「生成公开只读链接 + 独立呈现页」的能力。

## What Changes

- 新增「分享对话」完整链路：在三点菜单点击「分享对话」后弹出分享弹窗，可一键生成**公开只读链接**、复制链接、打开预览、以及**取消分享**。
- 新增后端分享数据模型与 API：创建分享（生成不可猜测 token）、查询自己的分享状态、取消分享，以及**无需登录**即可访问的公开快照读取接口。
- 采用**快照（snapshot）语义**：分享时刻捕获当前对话内容存档，后续会话继续追加消息或被删除都不影响已分享内容（与 ChatGPT 行为一致），owner 可「更新分享」刷新快照。
- 新增独立公开页 `/share/:token`（脱离 `WorkbenchLayout`、无侧边栏、无输入框、无鉴权），只读渲染对话历史，复用现有 Markdown / Mermaid 渲染。
- 隐私保护：公开页不暴露 owner 用户名 / 邮箱等身份信息；默认不导出 agent trace 内部步骤（可能含设备 / 日志敏感数据）；仅 session owner 可创建 / 取消分享；取消后链接立即失效。
- i18n：补齐分享弹窗、公开页、错误态的中英文案（现有 `aiChat.menu.share` key 已存在）。

## Capabilities

### New Capabilities
- `conversation-sharing`: 对话分享的后端能力——分享记录数据模型、分享 token 生命周期（创建 / 更新 / 取消）、快照捕获、公开只读读取接口及隐私与权限规则。
- `shared-conversation-ui`: 对话分享的前端能力——三点菜单分享入口与分享弹窗，以及独立的公开只读对话呈现页。

### Modified Capabilities
<!-- 不修改现有能力的需求：分享入口是新增菜单行为，未改变 chat-conversation-ui 既有的会话隔离 / 流式 / 侧边栏需求。 -->

## Impact

- **后端**：新增 `app/models/` 分享表（如 `conversation_shares`）+ Alembic 迁移；新增分享 API（建议挂在 `app/api/users.py` 的 `/users/chat-sessions/{session_id}/share` 与新的公开路由 `app/api/`，如 `share.py` 下 `/share/{token}`）；新增 / 扩展 `chat_history_service` 或新建 `conversation_share_service`。
- **前端**：`AIChat.vue` 三点菜单分享项接线 + 新增分享弹窗组件；新增 `views/SharedConversation.vue` 公开页；`router/index.ts` 新增公开路由；`api/` 新增分享接口客户端；`i18n/` 文案。
- **数据 / 安全**：新增公开未鉴权读取面，需保证 token 不可猜测、取消即失效、不泄露身份信息与内部 trace。
