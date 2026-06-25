## Why

用户在主对话窗口经常需要就截图、报错画面、设备面板照片等图像内容提问，但当前对话只接受纯文本，无法粘贴图片。同时主力 Agent（DeviceAgent / GeneralAgent）走的是 `claude_agent_sdk.query()` 文本提示链路,且默认 provider（如 DeepSeek）不具备图像输入能力。我们需要在不改动主力 Agent 文本协议的前提下，引入“多模态模型解析图片 → 把图片理解结果以文本回灌给主力 Agent”的旁路能力。

## What Changes

- 在对话输入框支持**粘贴/拖拽/选择图片**（剪贴板 paste、文件选择），输入区展示缩略图、可删除、带类型/大小/数量校验。
- `ChatRequest` 与 `/chat/stream` 接受随消息附带的图片（base64 data URL 列表）。
- 新增**独立的多模态模型配置**（`ANTHROPIC_MULTIMODAL_*` 环境变量 + provider 能力解析），与主力 Agent 模型解耦，可单独指定具备图像理解能力的 provider/model/base_url/key。
- 新增**图片理解服务**（仿 `title_generator_service` 的旁路调用模式）：当本轮携带图片时，先用多模态模型结合用户提问上下文解析图片，产出结构化文本理解。
- 在 run 编排中，将图片理解文本**注入主力 Agent 的用户提示**（作为 `<image_understanding>` 段），主力 Agent 继续以纯文本完成后续推理与工具调用。
- 优雅降级：多模态模型未配置或解析失败时，不阻断对话——附带提示告知用户图片未被解析，主力 Agent 仅基于文本作答。

## Capabilities

### New Capabilities
- `multimodal-image-understanding`: 独立的多模态模型配置解析、图片理解旁路服务，以及“图片→文本理解→回灌主力 Agent”的 run 编排与降级策略。

### Modified Capabilities
- `anthropic-llm-config`: 在 provider/能力矩阵与 `build_options` 之上，新增多模态模型的配置字段与解析路径（独立于主力模型，复用 `supports_image_input` 能力校验）。
- `chat-conversation-ui`: 主对话输入区新增图片粘贴/附件能力（缩略图、删除、校验）并随消息发送给后端。

## Impact

- 后端：`app/config.py`（新增 `ANTHROPIC_MULTIMODAL_*` 设置）、`app/agents/anthropic_client.py`（多模态模型/能力解析）、新增 `app/services/image_understanding_service.py`、`app/models/chat.py`（`ChatRequest` 增加 `images`）、`app/api/ai_chat.py`（透传图片）、`app/services/chat_run_service.py` 与 `app/services/ai_chat_service.py`（编排注入）、`app/agents/device_agent` 与 `app/agents/general_agent`（用户提示拼接图片理解段）。
- 前端：`frontend/src/views/AIChat.vue`（粘贴/附件 UI）、`frontend/src/stores/chatSession.ts` 与 `frontend/src/api/chat.ts`（携带图片发送）、i18n 文案。
- 配置/部署：`.env` / `.env.example` 新增多模态模型变量；`AdminModelSettings.vue` 文档区追加变量说明；`DEPLOY_USAGE.md` 更新。
- 依赖：复用现有 `claude-agent-sdk` 图像 content block，无新增三方依赖；持久化历史仍以文本理解为准（图片本身不入库或仅按需临时落盘）。
