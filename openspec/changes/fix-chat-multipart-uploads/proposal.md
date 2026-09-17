## Why

带图片的日志分析请求在业务校验之前被 multipart 普通字段默认 1 MiB 限额拒绝，前端又将 HTTP 400 显示为网络故障。项目专家和配置管理员使用同样的传输方式，也存在这个问题。

## What Changes

- 三个 multipart 对话入口统一使用标准图片文件上传，保留旧版 Base64 JSON 字段兼容。
- 兼容字段的解析容量与已配置的图片容量匹配，不引入更严格的图片数量或单图限制。
- 超限、格式错误及 HTTP 拒绝给出明确的中英文原因和处理建议，真实网络故障单独提示。
- 增加真实 multipart 请求和前端错误展示回归测试。

## Capabilities

### New Capabilities

- `chat-multipart-uploads`: 图片文件传输、旧客户端兼容和可操作的上传失败提示。

### Modified Capabilities

无。

## Impact

影响三个对话流式 API、图片校验、前端表单构造与错误处理。图片 OCR 和 Agent 输入模型保持兼容；无需数据库迁移。生产部署需单独确认范围。
