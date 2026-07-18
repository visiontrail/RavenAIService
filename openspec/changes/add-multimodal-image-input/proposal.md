## Why

用户经常需要就**截图、报错画面、设备面板照片、日志片段图片**等图像内容提问，但当前对话框只接受纯文本与日志文件附件，无法粘贴图片。同时主力对话模型走 `claude_agent_sdk.query()` 的 Anthropic 兼容纯文本链路，默认 provider（DeepSeek）`supports_image_input=False`，用户主力模型未必具备 OCR/视觉能力。

我们希望在**不改动任何 Agent 的文本协议**的前提下，引入一个**独立、可配置的 OCR / 视觉理解模型**（默认对接阿里云百炼 DashScope Qwen-VL 的 OpenAI 兼容端点）：用户在前端粘贴图片后，OCR 模型把图片转成文字，作为一段带标注的素材**追加到本轮用户提示词**中，随后项目专家、日志分析、包检索、设备联动、通用等**任意 Agent** 都能基于这段文字继续推理与工具调用。OCR 模型与主力模型完全解耦，可单独配置 provider / model / key / base_url。

## What Changes

- 对话输入框在**任意 Agent** 下支持**粘贴 / 拖拽 / 选择图片**（剪贴板 paste、图片文件选择、拖拽）；输入区展示缩略图、可删除，带 MIME 白名单 / 单图大小 / 数量校验。图片附件与既有「日志文件附件」相互独立、可同时存在。
- 新增**独立 OCR 模型配置**（`OCR_*` 环境变量），与主力模型解耦，默认指向 DashScope Qwen-VL 的 OpenAI 兼容端点；在 `AdminModelSettings.vue` 只读文档页与 `.env.example` / `DEPLOY_USAGE.md` 补充说明。
- 新增 **OCR 服务** `app/services/ocr_service.py`：通过 `httpx` 调用 OpenAI 兼容的 `chat/completions`（`image_url` data URL），把图片转成结构化文字。best-effort：超时 / 失败 / 未配置均不阻断对话；按 `title_generator` 同构方式用 `metrics_service.record_ai_usage(source="ocr")` 计量。
- 在**各 Agent 入口做统一预处理**：请求携带图片时先做 OCR，再把识别文本以 `<user_image_ocr>` 段**合并进传给 Agent 的用户消息**。下游各 Agent 与其提示词渲染逻辑**零改动**——它们只是收到了更丰富的用户文本。
- **优雅降级**：OCR 未配置 / 超时 / 失败时，本轮仅按文本作答，并提示用户「图片未被识别」。
- **持久化**：合并后的用户消息（含 OCR 文本）写入历史，后续轮无需重传图片即可延续上下文；原始图片字节不入库。

## Capabilities

### New Capabilities
- `image-ocr-input`: 独立可配置的 OCR/视觉模型（DashScope Qwen-VL，OpenAI 兼容），把用户粘贴的图片转成文字，并在 Agent 入口以 agent-无关的方式合并进用户提示词，含校验、降级、持久化与用量计量。

### Modified Capabilities
- `chat-conversation-ui`: 对话输入区在任意 Agent 下新增图片粘贴 / 拖拽 / 选择能力（缩略图、删除、校验），并随消息把图片发送给对应 Agent 的后端入口。

## Impact

- 后端：`app/config.py`（新增 `OCR_*` 设置）、新增 `app/services/ocr_service.py`、`app/models/chat.py`（新增 `ImageAttachment`、`ChatRequest` 增加 `images`）、`app/api/ai_chat.py`（`/chat/stream` 及项目专家 / 包检索 / 日志分析入口透传 + 合并）、`app/services/log_analysis_chat_service.py`、`app/services/project_expert_chat_service.py`、`app/services/package_search_chat_service.py`（入口合并 OCR 文本）、`app/services/metrics_service.py`（沿用既有接口新增 `source="ocr"` 计量）。
- 前端：`frontend/src/views/AIChat.vue`（粘贴 / 缩略图 / 校验 / 各 Agent 发送路径）、`frontend/src/stores/conversationRuns.ts`（各 `start*Run` 携带 `images`）、`frontend/src/api/chat.ts`（payload 类型）、`i18n/zh.ts` 与 `i18n/en.ts` 文案。
- 配置 / 部署：`.env` / `.env.example` 新增 `OCR_*` 变量；`AdminModelSettings.vue` 文档区追加变量说明；`DEPLOY_USAGE.md` 更新。
- 依赖：显式声明已安装的 `httpx`（`requirements.txt`）；**不引入** 视觉 SDK，也不改动 claude-agent-sdk 主力模型链路；Agent 与主力模型协议保持纯文本不变。
