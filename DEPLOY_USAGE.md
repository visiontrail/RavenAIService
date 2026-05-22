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
| `POST /api/v1/ai-chat/chat/stream` | SSE 流式入口 | 事件包含 `session`、`run_start`、`step_*`、`thinking_*`、`tool_permission_request/resolved`、`result_validation`、`run_complete`、`done` |
| `POST /api/v1/ai-chat/chat/permissions/{request_id}/resolve` | HITL 决策回传 | body `{ decision: "allow"\|"deny", updated_args?, message?, session_id? }`；404 表示该请求已被 resolve 或超时 |

### 3. Skill 装载

DeviceAgent 与 Log Analysis Agent 共用 `app/services/skills_service.py` 的 Skill 装载机制：

1. 管理员在 `frontend > Admin > Agent Skills` 上传一个 zip 包（含 `SKILL.md` + 资源文件）。
2. 启用后下次 DeviceAgent 启动会自动把该 Skill 物化到
   `<workspace>/.claude/skills/<slug>/SKILL.md`，并将 `setting_sources=["project"]` 写入 `ClaudeAgentOptions`。
3. workspace 路径在每次会话结束后会被幂等清理（见 `app/agents/device_agent/workspace.py`）。

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

### 5. 部署后观察清单

- 首批对话的成功率（按 `done` vs `error` 事件计）。
- 平均 HITL 等待时长（`tool_permission_request` → `tool_permission_resolved` 的 ts 差）。
- HITL 超时占比（`tool_permission_resolved{reason:"timeout"}` / 总数）。
  > 经验阈值：> 20% 时应把 `DEVICE_AGENT_PERMISSION_TIMEOUT_SECONDS` 调大并发补丁。
- `provider_no_mcp_support` 计数：理论应为 0，非 0 说明仍有配置走到了不支持的 provider。

---

## Log Analysis Agent

完整说明见 [`docs/log_analysis_agent.md`](docs/log_analysis_agent.md)。
