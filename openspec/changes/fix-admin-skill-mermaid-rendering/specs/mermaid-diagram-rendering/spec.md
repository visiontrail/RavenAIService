## MODIFIED Requirements

### Requirement: Mermaid 代码块识别与渲染
当 AI 回复或后台 Skill Markdown 文件预览包含 ` ```mermaid ` 代码块时，系统 SHALL 将其渲染为可视化 SVG 图表，而非永久停留在 loading 占位状态或仅显示纯文本代码。系统 SHALL 支持 Mermaid.js 支持的所有图表类型，包括但不限于 flowchart、sequence、class、state、ER、gantt、pie、mindmap。

#### Scenario: 渲染包含 flowchart 的 AI 回复
- **WHEN** AI 回复内容包含 ` ```mermaid\nflowchart TD\n  A-->B\n``` `
- **THEN** 该代码块 SHALL 被渲染为 SVG 流程图，显示在消息气泡内

#### Scenario: 渲染包含 sequence diagram 的 AI 回复
- **WHEN** AI 回复内容包含 ` ```mermaid\nsequenceDiagram\n  Alice->>Bob: Hello\n``` `
- **THEN** 该代码块 SHALL 被渲染为 SVG 序列图

#### Scenario: 同一消息包含多个 Mermaid 图表
- **WHEN** AI 回复中包含两个或以上 ` ```mermaid ` 代码块
- **THEN** 每个代码块 SHALL 分别独立渲染为对应的 SVG 图表

#### Scenario: 渲染 Agent Skill Markdown 中的图表
- **WHEN** 管理员在 Agent Skills 页面选择一个包含合法 Mermaid 代码块的 Markdown 文件
- **THEN** 该代码块 SHALL 在文件预览 DOM 更新后被渲染为 SVG
- **AND** 预览 SHALL 不再显示“图表渲染中”占位状态

#### Scenario: 渲染项目 Skill Markdown 中的图表
- **WHEN** 管理员在项目 Skills 页面选择一个包含合法 Mermaid 代码块的 Markdown 文件
- **THEN** 该代码块 SHALL 在文件预览 DOM 更新后被渲染为 SVG
- **AND** 预览 SHALL 不再显示“图表渲染中”占位状态

#### Scenario: 切换 Skill Markdown 文件后渲染新图表
- **WHEN** 管理员从一个已预览文件切换到另一个包含 Mermaid 代码块的 Markdown 文件
- **THEN** 系统 SHALL 扫描并渲染新文件产生的 pending Mermaid 容器

## ADDED Requirements

### Requirement: 后台 Skill Mermaid 预览必须进入可见终态
后台 Agent Skill 和项目 Skill Markdown 预览中的每个 Mermaid 容器 MUST 最终进入成功 SVG 状态或既有错误降级状态，不得无限期停留在 loading 状态。

#### Scenario: Skill Mermaid 语法无效
- **WHEN** 管理员预览的 Skill Markdown 包含无法由 Mermaid 解析的语法
- **THEN** 预览 SHALL 显示错误提示和原始 Mermaid 源码
- **AND** loading 指示器 SHALL 被移除

#### Scenario: Skill Mermaid 库加载失败
- **WHEN** 管理员预览 Skill Markdown 时 Mermaid 动态模块加载失败
- **THEN** 预览 SHALL 保留原始 Mermaid 源码作为降级内容
- **AND** loading 指示器 SHALL 被移除
