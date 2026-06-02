## Context

当前聊天界面使用 Vue 3 + markdown-it + highlight.js 渲染 AI 回复消息。`markdownRenderer.ts` 是核心渲染模块，为单例实例。AI 回复中的 ` ```mermaid ` 代码块目前被 highlight.js 当作普通代码块处理，以纯文本形式展示。用户无法直观查看流程图、序列图等图表。

关键现有架构：
- `renderMarkdown()` 返回 HTML 字符串，通过 `v-html` 插入 DOM
- markdown-it 的 `highlight` 回调处理所有带语言标识的代码块
- AIChat.vue 中消息渲染发生在 Vue reactive 更新周期中

## Goals / Non-Goals

**Goals:**
- 将 AI 回复中的 Mermaid 代码块渲染为可视化 SVG 图表
- 渲染失败时优雅降级为带错误提示的代码块
- 提供图表放大查看和源码复制功能
- Mermaid 库按需懒加载，不影响首屏性能
- 图表样式与现有深色代码块主题协调

**Non-Goals:**
- 不支持用户编辑 Mermaid 源码（只读渲染）
- 不支持 Mermaid 之外的其他图表语法（如 PlantUML、GraphViz）
- 不实现图表导出为图片/PDF 功能（可未来扩展）
- 不修改后端 API 或消息结构

## Decisions

### 1. 渲染时机：DOM 后处理 vs. markdown-it 插件

**选择：在 markdown-it 的 highlight 回调中拦截 mermaid 代码块，输出占位容器，然后在 Vue 的 `nextTick` 后通过 Mermaid API 对占位容器进行异步渲染。**

- **方案 A（markdown-it highlight 拦截 + 异步后渲染）**：在 highlight 回调中检测 `lang === 'mermaid'`，返回带唯一 ID 的占位 `<div class="mermaid-container" data-mermaid-id="xxx">` 和隐藏的 `<pre>` 源码块。渲染完成 `v-html` 插入 DOM 后，在 Vue 组件的 `watch` + `nextTick` 中查找所有占位容器，调用 `mermaid.render()` 替换为 SVG。
- **方案 B（纯 markdown-it 插件同步渲染）**：需要在 markdown-it 解析阶段同步调用 mermaid，但 Mermaid 的 `render()` 是异步 API，与 markdown-it 的同步管线不兼容。
- **方案 C（自定义 Vue 组件替代 v-html）**：将消息渲染改为 Vue 组件树，但重构量太大且影响流式渲染性能。

选择方案 A 的理由：与现有 `renderMarkdown()` 同步返回 HTML 的接口兼容，无需改变调用方式；占位容器保证了 DOM 结构可预测；异步渲染在 nextTick 后执行，不阻塞消息展示。

### 2. Mermaid 库加载策略

**选择：动态 `import()` 懒加载。**

- Mermaid.js 完整包约 2MB（gzip 后 ~500KB），不适合包含在首屏 bundle 中
- 创建 `mermaidLoader.ts` 工具模块，首次遇到 mermaid 代码块时触发 `import('mermaid')`
- 加载完成前显示 loading 指示器
- 使用模块级 Promise 缓存，确保只加载一次

### 3. 唯一 ID 生成策略

**选择：使用自增计数器 `mermaid-{counter}` 格式。**

- Mermaid 的 `render()` API 需要唯一的 DOM element ID
- 自增计数器简单可靠，避免 UUID 的冗余
- 计数器作用域在 `markdownRenderer.ts` 模块内，页面生命周期内唯一

### 4. 图表交互方案

**选择：点击图表弹出 Element Plus 的 `ElDialog` 全屏查看，附带复制源码按钮。**

- 使用事件委托在消息容器上监听 `.mermaid-container` 的点击
- 弹窗内重新渲染 Mermaid（更大容器尺寸）以获得更好的清晰度
- 复制源码使用 `navigator.clipboard.writeText()`
- 不依赖额外的图片查看器库

### 5. 错误处理策略

**选择：渲染失败时在占位容器中显示原始代码块 + 错误信息提示。**

- 占位容器中预置隐藏的 `<pre>` 块（含高亮后的源码）
- 渲染成功时移除 `<pre>` 块，显示 SVG
- 渲染失败时显示 `<pre>` 块，并在其上方添加一行错误提示
- 用户仍可阅读和复制 Mermaid 源码

### 6. Mermaid 主题配置

**选择：使用 `dark` 主题，自定义颜色以匹配现有 github-dark 代码块风格。**

- Mermaid 内置 `dark` 主题基调与 `github-dark` 接近
- 通过 `mermaid.initialize()` 的 `themeVariables` 微调主要颜色
- 图表背景设为透明，使用容器背景色

## Risks / Trade-offs

- **[包体积增加]** → Mermaid.js ~2MB。通过动态 import 懒加载缓解，仅在首次遇到 mermaid 代码块时加载。
- **[流式渲染中的闪烁]** → AI 回复流式输出时，Mermaid 源码不完整会导致渲染失败/闪烁。通过检测代码块是否完整（有闭合的 ` ``` `）来决定是否触发渲染，未完成时显示 loading 状态。
- **[XSS 安全风险]** → Mermaid 渲染生成 SVG，理论上可被注入恶意脚本。使用 Mermaid 内置的 `securityLevel: 'strict'` 配置禁用 HTML 标签和 click 事件。
- **[大量图表性能]** → 单条消息多个 Mermaid 图表可能导致渲染卡顿。初期不做特殊优化，如出现问题可后续添加 IntersectionObserver 懒渲染。
