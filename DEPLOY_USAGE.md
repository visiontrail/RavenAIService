# RavenAI 服务部署与使用说明

本文档面向运维与现场工程师，整理需要在部署后逐项确认的运行期配置；
针对每个 Agent 还附了功能开关、人机交互流程与故障排查的速查清单。

---

## DeviceAgent（自然语言控设备 / `POST /api/v1/ai-chat/chat`）

> 该 Agent 由 Claude Agent SDK 驱动，对设备的工具调用通过 in-process MCP server
> 代理到上位机链路。完整设计见 `openspec/specs/device-agent/spec.md`，与
> Log Analysis Agent 的关系见 [`docs/log_analysis_agent.md`](docs/log_analysis_agent.md)。

### 1. Provider 与环境变量

DeviceAgent 依赖 Anthropic 风格的 Claude Agent SDK。**必须确保 provider 支持
in-process MCP 工具**：

| 变量 | 必需 | 说明 |
| --- | --- | --- |
| `ANTHROPIC_PROVIDER` | 是 | 推荐 `anthropic`。`deepseek` profile 若被切换为 `supports_mcp_server_tools=False` 会被 DeviceAgent 直接拒绝（见下文错误码） |
| `ANTHROPIC_API_KEY` | 是 | provider API key |
| `ANTHROPIC_MODEL` | 否 | 留空则使用 provider profile 的默认模型 |
| `ANTHROPIC_SMALL_FAST_MODEL` | 推荐 | 用于会话标题生成的快模型；缺省时回退到 profile 的 `default_small_fast_model` |
| `ANTHROPIC_MAX_HISTORY_TURNS` | 否 | 默认 `10`。控制拼接进 system prompt 的历史轮数（最近优先） |
| `DEVICE_AGENT_PERMISSION_TIMEOUT_SECONDS` | 否 | 默认 `120`。HITL 等待用户裁决的上限，超时按 `deny` 处理 |
| `DEVICE_AGENT_RESULT_EXCERPT_BYTES` | 否 | 默认 `16384`。单条工具结果摘要的字节上限 |
| `DEVICE_AGENT_RESULT_MAX_BYTES` | 否 | 默认 `262144`。整次 PostToolUse 总长上限；超出替换为 `error_kind=result_too_large` |
| `DEVICE_AGENT_MAX_REMOTE_TOOLS` | 否 | 默认 `64`。注册到 SDK 的远端工具数上限，超出通过 `system_notice` 提示 |

启动时若 provider profile 的 `supports_mcp_server_tools=False`，
`POST /chat` / `POST /chat/stream` 会立刻在 trace 流里
返回 `error{ error_kind="provider_no_mcp_support" }`，并跳过 SDK 调用。

### 2. HITL（Human-in-the-Loop）流程

每次 DeviceAgent 尝试调用某个远端工具时，`can_use_tool` 钩子按以下规则裁决：

1. 风险分级 — 顺序：`tool_meta.risk` > `prompts_config.yaml.claude_agent_device.risk_rules` 模式匹配 > 兜底 `write`。
2. `read` 级别 — 直接放行，不打扰用户；trace 中只有 `tool_call_*` 事件，没有 `tool_permission_request`。
3. `write` / `destructive` 级别 — 推送 `tool_permission_request` SSE 事件，进入等待：
   - 前端弹窗显示工具名、参数、风险等级、rationale；
   - 用户允许 / 拒绝 / 编辑参数后允许 → `POST /api/v1/ai-chat/chat/permissions/{request_id}/resolve`；
   - 超过 `DEVICE_AGENT_PERMISSION_TIMEOUT_SECONDS` 仍未收到决策 → broker 自动 `deny`，
     trace 中 `tool_permission_resolved{reason:"timeout"}`。
4. 工具返回后由 PostToolUse hook 校验：若不符合 `Decision 10` schema 或可选 `outputSchema`，
   trace 推 `result_validation{status:"schema_mismatch", reason}`，并把工具输出替换为
   `{ "error_kind": "schema_mismatch", ... }` 喂回模型。

API 端点（`app/api/ai_chat.py`）：

| 方法 / 路径 | 用途 | 备注 |
| --- | --- | --- |
| `POST /api/v1/ai-chat/chat` | 非流式入口 | 返回 `ChatResponse{answer, model, session_id, messages}` |
| `POST /api/v1/ai-chat/chat/stream` | SSE 流式入口（create-or-subscribe） | 同一 `(owner_scope, session_id)` 已有 active run 时再次发送非空 `message` 返回 409 `{active_run_id}`；`message=""` 则订阅现有 run。事件包含 `session`、`run_start`、`step_*`、`thinking_*`、`tool_permission_request/resolved`、`result_validation`、`run_complete`、`done`，并在 payload 中携带 `run_id` / `session_id` |
| `GET /api/v1/ai-chat/chat/sessions/{session_id}/active-run` | 查询当前会话 active run 的快照 | 200 含 `{run_id, status, agent_kind, events, trace_events, answer_so_far, pending_permissions}`；404 表示该 owner 下无 active run |
| `GET /api/v1/ai-chat/chat/runs/{run_id}` | 获取 run 终态快照 | 内存命中优先；落库后从 `chat_agent_runs.trace_events_json` 回放；owner_scope 不匹配返回 404，不泄露其它用户 run 的存在 |
| `GET /api/v1/ai-chat/chat/runs/{run_id}/stream` | 订阅指定 run 的 SSE | 先 replay buffered events，再实时接续；客户端断开**只**释放订阅，不会取消后台 Agent loop |
| `POST /api/v1/ai-chat/chat/runs/{run_id}/cancel` | 主动取消 run | 仅 owner 可调用；对 DeviceAgent 调用 `asyncio.Task.cancel()`，对 LogAnalysis 调用其 cancel_event |
| `POST /api/v1/ai-chat/chat/permissions/{request_id}/resolve` | HITL 决策回传 | body `{ decision, updated_args?, message?, run_id?, session_id? }`；解析顺序 `run_id` → `(owner_scope, session_id)` → legacy scan（始终按 owner_scope 过滤）；404 表示该请求已被 resolve 或超时 |

### 3. Skill 装载

DeviceAgent 与 Log Analysis Agent 共用 `app/services/skills_service.py` 的 Skill 装载机制：

1. 管理员在 `frontend > Admin > Agent Skills` 上传一个 zip 包（含 `SKILL.md` + 资源文件）。
2. 启用后下次 DeviceAgent 启动会自动把该 Skill 物化到
   `<workspace>/.claude/skills/<slug>/SKILL.md`，并将 `setting_sources=["project"]` 写入 `ClaudeAgentOptions`。
3. workspace 路径在每次会话结束后会被幂等清理（见 `app/agents/device_agent/workspace.py`）。

Excel / spreadsheet 类 Skill 若需要读取或修改 `.xlsx` 文件，应部署包含
`pandas`、`openpyxl` 与 `LibreOffice Calc`/`soffice` 的运行环境。官方镜像已在
`requirements.txt` 与 `Dockerfile` 中包含这些依赖；自定义镜像需保持一致，
否则 Skill 可以被加载，但执行 `scripts/recalc.py` 等公式重算脚本时会失败。

操作步骤、目录布局与故障排查方式参见
[`docs/log_analysis_agent.md` § 1 工作区布局](docs/log_analysis_agent.md#1-工作区布局)
— DeviceAgent 完全沿用同一约定。

### 4. 故障排查（常见错误码）

| `error_kind` | 含义 | 处置 |
| --- | --- | --- |
| `provider_no_mcp_support` | 当前 Anthropic provider 不支持 in-process MCP 工具 | 切换 `ANTHROPIC_PROVIDER=anthropic` 后重试 |
| `internal_error` | dispatcher 异常被吞下（链路抖动 / 上位机回包格式错误） | 查 `device_link_manager` 日志，确认设备端 v2 envelope 兼容性 |
| `result_too_large` | PostToolUse 总长超过 `DEVICE_AGENT_RESULT_MAX_BYTES` | 调大上限或要求工具支持分页 |
| `schema_mismatch` | 工具返回不符合 `Decision 10` 或 `outputSchema` | 查 trace 中的 `reason`，定位上位机字段 |

### 5. 并发会话与后台 run

自 `support-concurrent-chat-agent-sessions` 变更起，每次发送都会创建一个
**ChatAgentRun**（落库 `chat_agent_runs` 表），由 `ChatRunService` 在后端独立持有
生命周期。SSE 是订阅者，不是执行者：

- **多会话并发**：不同 `(owner_scope, session_id)` 可以同时各自有一个 active run；
  事件、HITL 弹窗、`.claude/skills` 工作区与最终持久化互不串线。
- **单会话单 run**：同一 session 已有 active run 时再次发送 → HTTP 409 `{active_run_id}`，
  前端可改用 `GET .../runs/{run_id}/stream` 订阅。
- **离开窗口继续运行**：用户切到其它会话或关闭标签页只会释放订阅；后台 Agent loop
  与 HITL broker 仍在运行。登录用户重新点击该 session 时通过 active-run snapshot 恢复
  上下文与待裁决弹窗；匿名用户的恢复仅在进程内 retention 内有效。
- **进程重启的 stale run**：服务启动时把 `chat_agent_runs.status IN ('queued','running')`
  的旧 run 标记为 `stale`，并写入 `error="server restarted before run completed"`。
  侧边栏 spinner 停转，用户重新发送即可。
- **DeviceAgent 工作区隔离**：每个 run 的工作目录路径形如
  `.../device_agent/<owner_scope>/<session_id>/<run_id>/`。即便两个用户使用相同
  `session_id`，`.claude/skills` 与临时文件也完全隔离；可选保留时间由
  `DEVICE_AGENT_RETAIN_WORKSPACE_SECONDS`（默认终态后立即清理）控制。
- **可选每用户并发上限**：`CHAT_AGENT_MAX_CONCURRENT_RUNS_PER_USER`（默认 `0`，不限制）
  超过时立即返回 429；用于压制突发流量。
- **匿名用户隔离**：未登录请求的 `owner_scope = "anon:<server_generated>"`，承载在 cookie
  或 `X-Client-Scope` header 上；同一用户多个 tab 仍共享同一 anon scope，跨用户/跨浏览器
  无法触达彼此 run。

### 6. 部署后观察清单

- 首批对话的成功率（按 `done` vs `error` 事件计）。
- 平均 HITL 等待时长（`tool_permission_request` → `tool_permission_resolved` 的 ts 差）。
- HITL 超时占比（`tool_permission_resolved{reason:"timeout"}` / 总数）。
  > 经验阈值：> 20% 时应把 `DEVICE_AGENT_PERMISSION_TIMEOUT_SECONDS` 调大并发补丁。
- `provider_no_mcp_support` 计数：理论应为 0，非 0 说明仍有配置走到了不支持的 provider。

---

## 图片输入 / OCR 视觉模型（对话框粘贴图片）

用户在对话框**粘贴 / 拖拽 / 选择图片**后（对任意 Agent 均可用），后端先用一个**独立于主力模型**的 OCR / 视觉模型把图片转成文字，再以 `<user_image_ocr>` 段合并进本轮用户提示，随后交给项目专家 / 日志分析 / 包检索 / 设备联动 / 通用等任意 Agent。OCR 走 **OpenAI 兼容端点**（`/compatible-mode/v1/chat/completions`，`image_url` data URL），默认对接**阿里云百炼 DashScope Qwen-VL**，与 `ANTHROPIC_*` 主力模型完全解耦。

### 环境变量

| 变量 | 默认 | 说明 |
| --- | --- | --- |
| `OCR_ENABLED` | `true` | 图片识别总开关；`false` 时无条件降级（本轮仅按文本作答） |
| `OCR_API_KEY` | 空 | OCR 模型 API Key。**未配置即视为「未配置」→ 自动降级**，前端提示「图片未被识别」 |
| `OCR_BASE_URL` | `https://dashscope.aliyuncs.com/compatible-mode/v1` | OpenAI 兼容端点 |
| `OCR_MODEL` | `qwen3.5-ocr` | 阿里云专用 OCR 模型；也可用 `qwen-vl-ocr-latest` / `qwen-vl-ocr` |
| `OCR_PROVIDER` | `dashscope` | 计量 / 日志标签（用量记入 `metric_events` 的 `source="ocr"`） |
| `OCR_MAX_TOKENS` | `2048` | 单次识别输出上限 |
| `OCR_REQUEST_TIMEOUT_SECONDS` | `30` | 单次识别请求超时；超时即降级为纯文本 |
| `OCR_MAX_IMAGES` | `6` | 单轮图片数上限（前后端一致，超限 4xx） |
| `OCR_MAX_IMAGE_MB` | `5` | 单图大小上限，单位 MB（前后端一致，超限 4xx） |
| `CHAT_IMAGE_STORE_DIR` | `temp/chat_images` | 原图落盘目录（相对路径按项目根解析）；供历史回显读取，随会话删除而清理 |
| `CHAT_IMAGE_WORKSPACE_MATERIALIZE` | `true` | 是否把原图物化到 Agent 工作区 `<workspace>/images/`；仅在 provider 支持图像输入时生效 |

DashScope 示例：`OCR_BASE_URL=https://<WorkspaceId>.cn-beijing.maas.aliyuncs.com/compatible-mode/v1`、`OCR_MODEL=qwen3.5-ocr`。也可使用北京公共域名 `https://dashscope.aliyuncs.com/compatible-mode/v1`；API Key 的地域、业务空间和模型授权必须与端点及模型一致，否则会返回 `Model.AccessDenied`。

### 行为与合规

- **优雅降级**：未配置 / 超时 / 非 2xx / 网络异常时，本轮不阻断对话，仅按文本作答，并通过 SSE `ocr_status` 事件让前端展示「图片未被识别」。
- **持久化**：写入历史的是**合并后的文本**（含 `<user_image_ocr>` 段），后续轮无需重传图片即可延续上下文。**原始图片字节落盘**到 `CHAT_IMAGE_STORE_DIR/<session_id>/<image_id>.<ext>`，数据库 `chat_messages.images_json` 只存元数据（`id` / `media_type` / `name` / `size`）；前端在气泡里渲染缩略图，历史加载时经 `GET /api/v1/ai-chat/chat-images/{session_id}/{image_id}` 按会话归属鉴权后取回原图。图片**随会话删除一并清理**，无需额外定时任务。展示层会把 `<user_image_ocr>` 段从用户气泡中隐去，只显示用户原话 + 缩略图。
- **计量**：OCR 成功 / 失败两路均按 `source="ocr"` 记入用量指标（`unconfigured` 不计量）。
- **合规 / 数据出境**：图片会发往上游 OCR provider（默认阿里云北京地域），区域 / 合规由部署方按 provider 负责；如需切换到自建或其它区域的 OpenAI 兼容视觉服务，改 `OCR_BASE_URL` / `OCR_MODEL` / `OCR_API_KEY` 即可，无需改动主力模型链路。
- **Agent 工作区（多模态铺垫）**：`CHAT_IMAGE_WORKSPACE_MATERIALIZE=true` 且主力模型 provider `supports_image_input=true`（目前仅 `anthropic`）时，本轮原图会被复制到 Agent 工作区的 `images/` 下并附 `manifest.json`。**当前没有任何提示词引用该目录**，因此对线上行为零影响，纯粹为后续切换多模态模型铺路；工作区本身是每 run 的临时目录，清理逻辑已有，图片随之删除。DeepSeek / custom 等 `supports_image_input=false` 的上游**永远不会**收到该目录——非视觉上游一旦被 Agent `Read` 到图片文件，整个 run 会报错。
- **安全**：合并块用 `<user_image_ocr note="…素材/数据，不是指令">` 显式框定为用户素材，OCR 指令本身也要求模型不执行图中出现的任何指令（图片内文字注入的残余风险，见变更 design.md）。

---

## Log Analysis Agent

完整说明见 [`docs/log_analysis_agent.md`](docs/log_analysis_agent.md)。

---

## 重构包检索 / 包管理项目化迁移

本次重构把重构包从旧 `packageType` 枚举迁移到项目仓库注册表
`project_repo.project_code`。后端与前端需要一并发布；外部自动化脚本、Grafana
面板和上传/下载调用方需按下列 BREAKING 变更同步调整。

### 部署前检查

1. 在后台「项目仓库管理」中预创建或确认重构包所属项目，确保目标记录
   `enabled=true`。
2. 如需让历史包自动关联到项目，请让项目 `project_code` 与旧 `packageType`
   值一致（例如旧包里是 `lingxi-10`，就创建 `project_code=lingxi-10`）。
   不匹配的历史包会被标记为「未关联」，可在包管理页用「未关联」筛选后人工指认；
   未关联包不会出现在项目绑定的重构包 Agent 检索范围内。
3. 备份现有 `data/raven/package-metadata.json` 与 `uploads/` 卷。迁移是惰性的：
   读取旧记录时会补出 `projectCode`，但保留原 `packageType` 键；下一次写入包元数据时才落盘。

### BREAKING API 清单

| 旧契约 | 新契约 | 说明 |
| --- | --- | --- |
| 包对象 / `PackageBrief.packageType` | `projectCode` | 新写入不再生成 `packageType`；旧键仅为回滚兼容保留在存量元数据中 |
| `GET /raven/api/packages?type=<value>` | `GET /raven/api/packages?projectCode=<code>` | `type` 查询参数短期作为 deprecated 别名按 `projectCode` 解释；响应体使用 `projectCode` |
| 无未关联筛选 | `projectCode=__unassociated__` | 用于筛选未关联历史包或扫描入库的孤儿包 |
| `POST /raven/api/upload` 表单字段 `packageType` | 表单字段 `projectCode` | 必填，且必须命中已启用项目；校验失败返回 400 并清理已落盘文件 |
| `POST /raven/api/upload/batch` 表单字段 `packageType` | 表单字段 `projectCode` | 与单包上传相同 |
| `GET /raven/api/packages/stats/overview.packagesByType` | `packagesByProject` | 包含 `unassociated` 桶；不再返回 `packagesByType` |
| `GET /raven/api/download/type/{package_type}` | `GET /raven/api/download/project/{project_code}` | 旧路由移除；单包直发，多包打 zip |
| `POST /raven/api/packages/agent-search` 无项目要求 | body 必填 `project_repo_id` | 缺失返回 400，`reason="project_repo_required"` |
| 对话框旧包 Agent 流式逻辑 | `POST /api/v1/ai-chat/package-search/stream` | 与项目专家同构，首轮会话必须选择项目；后续同会话复用首轮项目与工作区 |

### 指标与 Grafana

- `package_activity` 业务事件 metadata 从 `package_type` 改为 `project_code`；
  未关联包记为 `unassociated`。
- Prometheus 指标 `raven_package_activity_total` 删除 `package_type` label，
  仅保留 `action` 与 `status`，避免把项目标识作为高基数 label。
- 旧 Grafana 查询如
  `sum by (package_type) (rate(raven_package_activity_total[5m]))`
  会失效。迁移后可改为按动作/状态聚合，例如
  `sum by (action, status) (rate(raven_package_activity_total[5m]))`；
  如需按项目看分布，请改用后台总览 API 的 `packages.counts_by_project`
  或包管理页统计，而不是 Prometheus label。

### 回滚

直接回滚代码即可。新版本读取旧元数据时保留原始 `packageType` 键，不删除存量字段；
因此旧版本仍可读取同一份包元数据。回滚后，新版本期间写入的 `projectCode`
不会被旧版本理解为包类型，必要时需用备份或人工字段映射恢复旧展示口径。

---

## 对话分享（公开只读链接）

会话 owner 可在对话面板右上角三点菜单点击「分享对话」，生成一个**公开只读链接**：任何持链接者无需登录即可查看该对话在分享时刻的**快照**。owner 可随时「更新分享」刷新快照或「取消分享」（取消后链接立即失效）。

### 接口

| 方法/路径 | 鉴权 | 说明 |
| --- | --- | --- |
| `POST /api/v1/users/chat-sessions/{session_id}/share` | 用户 | 创建或刷新分享，返回 `{ token, share_url, shared_at, message_count, is_active }`；空会话返回 422 |
| `GET /api/v1/users/chat-sessions/{session_id}/share` | 用户 | 查询分享状态（未分享返回 `is_active=false`） |
| `DELETE /api/v1/users/chat-sessions/{session_id}/share` | 用户 | 撤销分享 |
| `GET /api/v1/share/{token}` | **无** | 公开读取快照，仅返回 `title`/`shared_at`/`message_count`/`messages[{role,content,created_at}]`；无效或已撤销 token 返回 404 |

公开页面路由为前端 SPA 的 `/share/:token`（脱离工作台布局，无侧边栏/输入框/鉴权）；`share_url` 即指向该页面。

### 环境变量

| 变量 | 必填 | 说明 |
| --- | --- | --- |
| `PUBLIC_BASE_URL` | 否 | 公开分享链接的站点根地址，如 `https://ravenai.example.com`。留空时后端回退请求 `Origin` / `Host` 拼接（本地与多域名部署可不配）。生产建议显式配置，确保复制出的链接可被外部直接打开 |
| `SHARE_PUBLIC_RATE_LIMIT` | 否 | 公开 `GET /api/v1/share/{token}` 按来源 IP 的窗口内最大请求数，默认 `60`；用于抑制对 token 空间的扫描枚举，超额返回 429 |
| `SHARE_PUBLIC_RATE_WINDOW_SECONDS` | 否 | 上述限流时间窗（秒），默认 `60` |

### 安全要点

- token 由 `secrets.token_urlsafe(16)`（~128bit 熵）生成，与 `session_id` / `user_id` 解耦，不可枚举。
- 快照在**写入时**完成脱敏：仅保留 `role` / `content` / `created_at`，丢弃 owner 身份、`session_id` 与 agent trace；公开响应直接回吐快照，单点收口。
- 撤销即 `is_active=false`，公开端点立即 404（与 ChatGPT 一致，已打开页面的已加载内容不做额外回收）。
- 公开内容仍来自消息正文，owner 需自行确保不分享含敏感信息的对话；弹窗已显式提示「持链接者均可查看」。
