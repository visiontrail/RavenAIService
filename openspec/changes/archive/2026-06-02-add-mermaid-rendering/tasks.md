## 1. 依赖安装与基础模块

- [x] 1.1 安装 mermaid npm 依赖：`npm install mermaid`，在 `frontend/package.json` 中添加 mermaid 包
- [x] 1.2 创建 `frontend/src/utils/mermaidLoader.ts` 模块：实现 Mermaid 库的动态 import 懒加载，包含模块级 Promise 缓存（确保只加载一次）、`loadMermaid()` 函数返回 Mermaid 实例、Mermaid 初始化配置（`securityLevel: 'strict'`、`theme: 'dark'`、自定义 themeVariables 匹配 github-dark 风格）

## 2. Markdown 渲染器扩展

- [x] 2.1 修改 `frontend/src/utils/markdownRenderer.ts` 的 `highlight` 回调：当 `lang === 'mermaid'` 时，生成带唯一 ID 的占位容器 `<div class="mermaid-container" data-mermaid-id="mermaid-{counter}" data-mermaid-source="...">`，容器内包含隐藏的 `<pre>` 源码块（带 highlight.js 高亮）和 loading 指示器
- [x] 2.2 添加模块级自增计数器用于生成唯一 Mermaid 容器 ID
- [x] 2.3 导出 `processMermaidBlocks(containerEl: HTMLElement)` 异步函数：查找容器内所有 `.mermaid-container` 占位元素，调用 `mermaidLoader` 获取 Mermaid 实例，对每个容器调用 `mermaid.render()` 替换为 SVG，渲染失败时显示原始代码块并附加错误提示

## 3. AIChat 组件集成

- [x] 3.1 在 `frontend/src/views/AIChat.vue` 中添加 Mermaid 后处理逻辑：在消息内容更新后（watch chatHistory 或消息 content 变化），通过 `nextTick` 调用 `processMermaidBlocks()` 处理消息容器内的 Mermaid 占位元素
- [x] 3.2 处理流式渲染兼容：仅当 Mermaid 代码块完整（检测到闭合 ` ``` `）时触发渲染，未完成时保持 loading/源码预览状态
- [x] 3.3 添加图表点击放大交互：使用事件委托监听消息容器内 `.mermaid-container` 的点击事件，点击后打开 `ElDialog` 弹窗展示大尺寸图表（在弹窗内重新渲染 Mermaid 以适配更大容器）

## 4. 复制源码功能

- [x] 4.1 在 Mermaid 图表容器中添加"复制源码"按钮（悬浮在图表右上角），点击使用 `navigator.clipboard.writeText()` 复制 Mermaid 源码文本，并显示复制成功反馈（ElMessage 提示）

## 5. 样式

- [x] 5.1 在 `frontend/src/styles/markdown.css` 中添加 Mermaid 图表容器样式：`.mermaid-container` 的背景（`#0d1117`）、圆角（`0.5rem`）、内边距、阴影与 `.hljs` 代码块一致；SVG 图表居中显示、最大宽度 100%
- [x] 5.2 添加 Mermaid loading 指示器样式、错误提示样式
- [x] 5.3 添加"复制源码"按钮的悬浮样式（默认半透明，hover 显现）
- [x] 5.4 添加放大弹窗中图表的样式（居中、自适应宽高）
- [x] 5.5 添加响应式适配：移动端图表容器支持横向滚动

## 6. 验证与测试

- [x] 6.1 验证基本渲染：flowchart、sequence、class、state、ER、gantt、pie 等图表类型在聊天中正确渲染为 SVG
- [ ] 6.2 验证错误降级：发送含语法错误的 Mermaid 代码块，确认显示高亮源码和错误提示
- [x] 6.3 验证流式渲染：观察 AI 流式回复过程中 Mermaid 代码块的行为（未完成时不闪烁，完成后自动渲染）
- [x] 6.4 验证交互功能：点击图表放大查看、复制源码功能正常
- [x] 6.5 验证性能：首次加载页面时 Mermaid 库未被加载（查看 Network），仅在遇到 Mermaid 代码块后才动态加载
