## ADDED Requirements

### Requirement: Mermaid 代码块识别与渲染
当 AI 回复包含 ` ```mermaid ` 代码块时，系统 SHALL 将其渲染为可视化 SVG 图表，而非纯文本代码。系统 SHALL 支持 Mermaid.js 支持的所有图表类型，包括但不限于 flowchart、sequence、class、state、ER、gantt、pie、mindmap。

#### Scenario: 渲染包含 flowchart 的 AI 回复
- **WHEN** AI 回复内容包含 ` ```mermaid\nflowchart TD\n  A-->B\n``` `
- **THEN** 该代码块 SHALL 被渲染为 SVG 流程图，显示在消息气泡内

#### Scenario: 渲染包含 sequence diagram 的 AI 回复
- **WHEN** AI 回复内容包含 ` ```mermaid\nsequenceDiagram\n  Alice->>Bob: Hello\n``` `
- **THEN** 该代码块 SHALL 被渲染为 SVG 序列图

#### Scenario: 同一消息包含多个 Mermaid 图表
- **WHEN** AI 回复中包含两个或以上 ` ```mermaid ` 代码块
- **THEN** 每个代码块 SHALL 分别独立渲染为对应的 SVG 图表

### Requirement: Mermaid 库懒加载
系统 SHALL 使用动态 import 按需加载 Mermaid.js 库，不影响首屏加载性能。

#### Scenario: 首次遇到 Mermaid 代码块
- **WHEN** 用户打开聊天界面，AI 首次回复包含 Mermaid 代码块
- **THEN** 系统 SHALL 动态加载 Mermaid.js 库，加载期间在图表位置显示 loading 指示器

#### Scenario: Mermaid 库已缓存
- **WHEN** Mermaid.js 库已在本次会话中加载过
- **THEN** 后续 Mermaid 代码块 SHALL 直接渲染，无需再次加载

### Requirement: 渲染失败降级处理
当 Mermaid 代码块渲染失败时，系统 SHALL 优雅降级，显示原始代码并附带错误提示。

#### Scenario: 语法错误的 Mermaid 代码
- **WHEN** AI 回复中的 Mermaid 代码块包含语法错误导致渲染失败
- **THEN** 系统 SHALL 在该代码块位置显示带语法高亮的原始 Mermaid 源码
- **AND** 在代码块上方显示简短的错误提示信息

#### Scenario: Mermaid 库加载失败
- **WHEN** Mermaid.js 库因网络或其他原因加载失败
- **THEN** 系统 SHALL 将 Mermaid 代码块作为普通代码块显示（带语法高亮）
- **AND** 不影响消息中其他非 Mermaid 内容的正常渲染

### Requirement: 流式渲染兼容
在 AI 回复流式输出过程中，系统 SHALL 正确处理尚未完成的 Mermaid 代码块。

#### Scenario: 流式输出中 Mermaid 代码块尚未闭合
- **WHEN** AI 回复正在流式输出，Mermaid 代码块的结束标记 ` ``` ` 尚未出现
- **THEN** 系统 SHALL 在该代码块位置显示 loading 或源码预览状态，不尝试渲染

#### Scenario: 流式输出中 Mermaid 代码块完成
- **WHEN** AI 回复流式输出完成了一个完整的 Mermaid 代码块（出现闭合 ` ``` `）
- **THEN** 系统 SHALL 触发该代码块的 Mermaid 渲染

### Requirement: 图表放大查看
用户 SHALL 能够点击已渲染的 Mermaid 图表，在弹窗中查看更大尺寸的图表。

#### Scenario: 点击图表弹出放大视图
- **WHEN** 用户点击消息中已渲染的 Mermaid SVG 图表
- **THEN** 系统 SHALL 打开一个对话框/弹窗，以更大尺寸展示该图表
- **AND** 弹窗 SHALL 支持关闭操作

#### Scenario: 放大视图中图表尺寸适配
- **WHEN** 放大弹窗打开
- **THEN** 图表 SHALL 适配弹窗可用空间，保持宽高比

### Requirement: 复制 Mermaid 源码
用户 SHALL 能够复制 Mermaid 图表的原始源码。

#### Scenario: 复制图表源码
- **WHEN** 用户在 Mermaid 图表容器中点击"复制源码"按钮
- **THEN** 系统 SHALL 将该图表的 Mermaid 源码文本复制到系统剪贴板
- **AND** 显示复制成功的反馈提示

### Requirement: 图表安全渲染
系统 SHALL 确保 Mermaid 图表渲染不引入 XSS 安全漏洞。

#### Scenario: Mermaid 源码包含恶意脚本
- **WHEN** Mermaid 代码块中包含 HTML 标签或 JavaScript 代码（如 `<script>`）
- **THEN** Mermaid SHALL 以 `securityLevel: 'strict'` 模式渲染，禁止执行任何脚本或 HTML 标签

### Requirement: 图表主题与样式
Mermaid 图表 SHALL 使用与现有代码块深色主题协调的 dark 主题样式。

#### Scenario: 图表在聊天界面中的视觉一致性
- **WHEN** Mermaid 图表渲染完成显示在聊天消息中
- **THEN** 图表容器的背景、圆角、阴影样式 SHALL 与现有 `.hljs` 代码块容器风格一致
- **AND** 图表内的配色 SHALL 使用 Mermaid dark 主题
