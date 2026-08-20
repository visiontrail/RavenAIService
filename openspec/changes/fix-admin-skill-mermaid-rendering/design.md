## Context

`renderMarkdown()` 同步把 fenced Mermaid 代码转换为带 `data-mermaid-state="pending"` 的占位容器；真正的 SVG 由 `processMermaidBlocks()` 在 DOM 更新后异步生成。聊天、分享页和提示词预览都显式执行第二阶段，但 `AdminAgentSkills.vue` 与 `AdminProjectSkills.vue` 只执行第一阶段，因此 loading 文案永久保留。

两个 Skill 页面都通过计算属性生成 `v-html`，并在选择文件时异步替换 `activeFileContent`。修复必须等待 Vue 将新的 `v-html` 写入 DOM 后再扫描，而且切换到另一个 Markdown 文件时必须重新触发。

## Goals / Non-Goals

**Goals:**

- 让 Agent Skill 和项目 Skill 的合法 Mermaid 代码块完成 SVG 渲染。
- 让 Mermaid 语法错误或库加载错误进入共享渲染器已有的错误降级状态，而不是永久 loading。
- 保持文件切换、同一文档多图、主题刷新等既有共享行为。

**Non-Goals:**

- 不改变 Mermaid 语法、主题、安全级别、放大或复制交互。
- 不修改 Skill 文件 API、存储格式或 Markdown frontmatter 解析。
- 不为后台预览新增独立 Mermaid 实现。

## Decisions

1. **复用 `processMermaidBlocks()`，不直接调用 Mermaid 库。** 共享函数已经包含懒加载、并发状态保护、成功 SVG 替换和失败降级。独立实现会造成主题、安全与错误行为漂移。
2. **观察稳定的 `renderedMarkdown` 结果，并在 `flush: 'post'` 加 `nextTick()` 后处理页面根节点。** 文件内容变化会自然触发观察器；等待 DOM 提交可以保证待处理占位符已经存在。相比在 API 请求函数中直接渲染，这一方案不依赖请求完成与 Vue DOM 更新的时序。
3. **为每个页面的 Markdown 预览根节点增加局部 ref。** 局部扫描只处理当前 Skill 文档，避免扫描整个 `document.body`，也不会重复触发其他页面中的 Mermaid 容器。
4. **维持共享函数的幂等状态机。** 重复观察或主题刷新只会处理 `pending` 容器，已经完成或正在渲染的容器不会被重复提交。

## Risks / Trade-offs

- **文件快速切换时旧渲染 Promise 可能稍后完成** → 旧节点已经脱离 DOM；新内容的观察器会扫描新的根节点，因此不会覆盖当前文件。
- **Vue 再次写入相同 `v-html` 可能抹掉 SVG** → `renderMarkdown()` 已使用内容稳定的容器 ID；观察源仅在实际 HTML 变化时触发，与聊天页的稳定渲染约束一致。
- **合法图表渲染依赖动态 chunk 可加载** → 共享函数在加载失败时移除 loading 并保留源码，保证终态可见。

## Migration Plan

前端发布即可生效，无数据迁移。回滚时仅需回退两个 Skill 页面中的 DOM ref 与渲染观察器；后台 API 和已安装 Skill 不受影响。

## Open Questions

无。
