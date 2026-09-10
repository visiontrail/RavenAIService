## Why

日志分析和项目专家需要在每次回答中遵循 Humanizer-zh。仅上传 Skill 或依赖相关性匹配不能保证每轮加载，且上传数据不会随源码部署到新环境。

## What Changes

- 固化指定上游版本的完整 Humanizer-zh、许可证和来源信息。
- 两个 Agent 每轮自动加载完整规则及技术回答适配提示词，包含追问，并输出真实的服务端加载事件。
- 必需 Skill 不受相关性筛选、数量限制或同名上传内容覆盖；其他 Skill 保持现有行为。
- 保留结构化结果、原始证据、代码、引用和不确定性，不因润色放宽输出校验。
- 一并交付已验证的登录/注册弹窗遮罩误关闭修复。

## Capabilities

### New Capabilities
- `required-agent-skills`: 源码内置、逐轮强制加载并可观察的 Agent 回答规范。

### Modified Capabilities

无。

## Impact

涉及 Skills 服务、两个 Agent 的运行时提示词/事件、回归测试及 Agent 文档。不引入运行时下载、模型或数据库配置变更。nr-test 更新 backend、worker 和 frontend。
