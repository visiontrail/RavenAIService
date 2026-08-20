## Why

后台 Agent Skill 与项目 Skill 的 Markdown 文件预览会生成 Mermaid 加载占位符，但没有启动异步 Mermaid 渲染流程，导致合法图表永久停留在“图表渲染中”。管理员需要在两个 Skill 管理入口中可靠地查看图表，并在无效图表或库加载失败时看到既有降级结果。

## What Changes

- 在 Agent Skill Markdown 文件内容插入 DOM 后触发共享 Mermaid 渲染器。
- 在项目 Skill Markdown 文件内容插入 DOM 后触发同一渲染流程。
- 在切换 Markdown 文件或重新加载文件内容时重新扫描新的待渲染 Mermaid 容器。
- 增加回归验证，证明合法图表离开 loading 状态，失败路径不会永久停留在 loading 状态。

## Capabilities

### New Capabilities

无。

### Modified Capabilities

- `mermaid-diagram-rendering`: 将既有 Mermaid 异步渲染与失败降级行为扩展到后台 Agent Skill 和项目 Skill 的 Markdown 文件预览。
- `project-skill-admin-ui`: 明确项目 Skill Markdown 文件预览中的 Mermaid 代码块必须完成渲染或进入可见错误降级状态。

## Impact

- 前端页面：`frontend/src/views/AdminAgentSkills.vue`、`frontend/src/views/AdminProjectSkills.vue`。
- 共享渲染流程：复用 `frontend/src/utils/markdownRenderer.ts`，不新增 Mermaid 依赖，不修改后台 API 或数据模型。
- 验证：前端类型检查、构建/测试，以及实际后台 Skill 文件预览页面。
