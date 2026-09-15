## Why
后台原始事件的对话抽屉容易误关闭，Mermaid 缺少大图入口，管理员也无法在原 AI 工作空间中临时追问。下载事件使审计列表过于拥挤。

## What Changes
- 对话改为居中弹窗，仅通过 X 关闭；支持 Mermaid 大图缩放。
- 增加管理员专用、仅内存保留的多轮临时追问，复用事件关联的原工作空间进行只读查询，绝不写入原用户历史。
- 原始事件列表及分页总数排除 package_download，保留下载记录和业务统计。

## Capabilities
### New Capabilities
- `admin-conversation-review`: 对话弹窗、图表预览与隔离临时追问。
### Modified Capabilities
- `system-user-metrics`: 原始事件列表隐藏下载事件。

## Impact
AdminMetrics、管理员指标 API、专用临时追问服务、Markdown 图表交互、中英文文案、metrics 文档及回归测试。无数据库迁移。
