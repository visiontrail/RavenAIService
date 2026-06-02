## Why

AI 助手在回答架构、流程、关系等问题时，经常使用 Mermaid 语法生成流程图、序列图、类图等。当前聊天界面的 markdown 渲染器（markdown-it）不支持 Mermaid 代码块的图形化渲染，这些内容只能以纯文本形式展示，用户无法直观理解图表内容，降低了 AI 回答的表现力和可读性。

## What Changes

- 集成 Mermaid.js 库到前端项目，支持将 AI 回复中的 Mermaid 代码块渲染为 SVG 图表
- 扩展现有的 `markdownRenderer.ts`，添加 markdown-it 插件识别 ` ```mermaid ` 代码块并触发 Mermaid 渲染
- 在 `markdown.css` 中添加 Mermaid 图表的样式，确保与现有深色主题一致
- 支持的图表类型：flowchart、sequence、class、state、ER、gantt、pie、mindmap 等 Mermaid 支持的全部类型
- 渲染失败时优雅降级，显示原始代码块并附带错误提示
- 支持图表的缩放查看（点击放大）和复制源码功能

## Capabilities

### New Capabilities
- `mermaid-diagram-rendering`: Mermaid 代码块的识别、渲染、样式、交互（放大查看、复制源码）及错误降级处理

### Modified Capabilities

（无需修改现有能力的规格要求）

## Impact

- **前端依赖**: 新增 `mermaid` npm 包
- **受影响文件**:
  - `frontend/src/utils/markdownRenderer.ts` — 添加 Mermaid 代码块处理逻辑
  - `frontend/src/styles/markdown.css` — 添加 Mermaid 图表容器样式
  - `frontend/src/views/AIChat.vue` — 可能需要处理 Mermaid 的异步渲染生命周期
  - `frontend/package.json` — 新增 mermaid 依赖
- **性能考量**: Mermaid.js 库体积较大（~2MB），需考虑懒加载策略
- **安全考量**: Mermaid 渲染涉及 SVG 生成，需确保 XSS 防护
