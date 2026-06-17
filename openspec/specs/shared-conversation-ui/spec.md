## ADDED Requirements

### Requirement: 三点菜单分享入口打开分享弹窗

`AIChat.vue` 三点菜单中的「分享对话」项 SHALL 打开分享弹窗（替换当前空占位行为）。当前会话无消息时，该入口 MUST 被禁用或隐藏，以避免分享空会话。

#### Scenario: 点击分享对话打开弹窗

- **WHEN** 用户在含 ≥1 条消息的会话点击三点菜单「分享对话」
- **THEN** 系统 MUST 关闭菜单并打开分享弹窗
- **AND** 弹窗 MUST 呈现当前会话的分享状态

#### Scenario: 空会话禁用分享

- **WHEN** 当前会话为欢迎态 / 0 条消息
- **THEN** 「分享对话」入口 MUST 禁用或隐藏，点击 MUST NOT 打开分享弹窗

### Requirement: 分享弹窗管理链接生命周期

分享弹窗 SHALL 支持创建、复制、预览、更新与撤销分享。未分享态 MUST 提供「生成公开链接」操作；已分享态 MUST 展示只读链接框、复制按钮、打开预览、更新分享与取消分享操作，并 MUST 显式展示快照时间，告知用户分享内容为该时刻的快照。

#### Scenario: 生成链接

- **WHEN** 用户在未分享态点击「生成公开链接」
- **THEN** 系统 MUST 调用创建分享接口并在弹窗内展示返回的完整链接
- **AND** MUST 提供一键复制

#### Scenario: 复制链接

- **WHEN** 用户点击复制
- **THEN** 完整公开链接 MUST 写入剪贴板
- **AND** MUST 给出复制成功反馈（notification）

#### Scenario: 撤销分享

- **WHEN** 用户在已分享态点击「取消分享」
- **THEN** 系统 MUST 调用撤销接口
- **AND** 成功后弹窗 MUST 回到未分享态，原链接 MUST 不再可用

#### Scenario: 更新分享快照

- **WHEN** 用户在已分享态点击「更新分享」
- **THEN** 系统 MUST 刷新快照并保持同一链接
- **AND** 弹窗展示的快照时间 MUST 更新为最新时刻

### Requirement: 独立公开页只读呈现对话历史

系统 SHALL 提供独立公开页路由 `/share/:token`，该路由 MUST 位于 `WorkbenchLayout` 之外（无侧边栏、无主导航、无输入框），且 MUST NOT 要求登录。页面挂载时 MUST 依据 `:token` 拉取公开快照并只读渲染对话历史，消息渲染（Markdown / Mermaid / 代码块）效果 MUST 与主对话一致。页面 MUST NOT 提供任何发送 / 编辑 / 菜单等可写交互。

#### Scenario: 未登录访问者查看分享页

- **WHEN** 未登录用户打开 `/share/:token`（有效 token）
- **THEN** 页面 MUST 渲染会话标题与历史消息
- **AND** MUST NOT 出现输入框、三点菜单或侧边栏
- **AND** MUST NOT 跳转登录

#### Scenario: 渲染效果对齐主对话

- **WHEN** 快照消息含 Markdown / Mermaid / 代码块
- **THEN** 公开页 MUST 复用与主对话一致的渲染，正确呈现这些内容

#### Scenario: 失效或不存在链接的空态

- **WHEN** 打开的 `:token` 对应分享不存在或已撤销（公开接口返回 404）
- **THEN** 页面 MUST 展示「链接已失效或不存在」空态
- **AND** MUST 提供前往首页 / 了解产品的 CTA，MUST NOT 暴露任何会话内容

### Requirement: 公开页不暴露 owner 身份

公开页 SHALL 仅呈现快照接口返回的内容，MUST NOT 展示 owner 用户名、邮箱或其它身份信息。用户消息 MUST 以中性方式呈现（如不显示具体用户名）。

#### Scenario: 公开页不显示 owner 身份

- **WHEN** 任意访问者查看 `/share/:token`
- **THEN** 页面 MUST NOT 显示 owner 的用户名 / 邮箱
- **AND** 仅呈现对话标题与消息内容

### Requirement: 分享相关文案支持中英双语

分享弹窗、公开页、错误与空态的所有可见文案 SHALL 通过 i18n 提供，MUST 覆盖中文与英文，遵循现有 `aiChat.*` 文案组织（含已存在的 `aiChat.menu.share`）。

#### Scenario: 切换语言文案随之变化

- **WHEN** 应用语言为英文
- **THEN** 分享弹窗与公开页文案 MUST 显示英文
- **WHEN** 应用语言为中文
- **THEN** 同样的界面 MUST 显示中文
