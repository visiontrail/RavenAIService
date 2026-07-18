## ADDED Requirements

### Requirement: Unselected conversations route to the General Agent

当一轮对话请求**未选择任何专门 Agent**（请求的 `agent_type` 为 `None` 或空字符串，且不是设备操作）时，系统 SHALL 将该请求路由到通用轻量级 Agent（`GeneralAgent`，`AGENT_KEY == "general_agent"`）。系统 SHALL NOT 因为用户在已有会话窗口中继续提问而拒绝处理或丢失该请求。

#### Scenario: 续聊未选 Agent 默认走 GeneralAgent

- **WHEN** 用户在一个已存在的会话里发送新消息，且 `agent_type` 为 `None`/空、未选设备操作
- **THEN** 系统驱动 `GeneralAgent` 处理该请求
- **AND** 后台 run 的 `agent_kind` 记为 `general`

#### Scenario: 设备操作不走 GeneralAgent

- **WHEN** 请求的 `agent_type` 为 `device`
- **THEN** 系统路由到 DeviceAgent，而非 GeneralAgent

### Requirement: General Agent receives and uses bounded conversation context

`GeneralAgent` SHALL 通过 `GeneralAgentContext.history` 接收会话历史，并在构造提示词时将历史按时间顺序注入 `<conversation_history>` 区块。历史 SHALL 被截断为最近 `anthropic_max_history_turns` 轮（user+assistant 成对计数），以控制小/快模型的上下文长度。历史中各消息的角色 SHALL 被规范化为 `user` / `assistant` / `system`。

#### Scenario: 历史被注入提示词

- **WHEN** `GeneralAgentContext.history` 非空
- **THEN** 发送给模型的用户提示词包含一个 `<conversation_history>` 区块
- **AND** 该区块内每条消息以 `[role] content` 形式呈现，role 已规范化

#### Scenario: 历史按上限截断

- **WHEN** 历史长度超过 `anthropic_max_history_turns * 2` 条
- **THEN** 仅最近的 `anthropic_max_history_turns * 2` 条被注入

#### Scenario: 无历史时不注入区块

- **WHEN** `history` 为空
- **THEN** 用户提示词不包含 `<conversation_history>` 区块

### Requirement: General Agent classifies intent and guides Agent selection

`GeneralAgent` 的系统提示词 SHALL 描述本系统全部四个专门 Agent 及其职责：`device`（设备操作）、`log_analysis`（日志分析）、`package_search`（检索包）、`project_expert`（项目专家）。对用户的**最新输入**，`GeneralAgent` SHALL 将其归入三类之一并据此回应：

- **A 类——询问"系统怎么用/有什么功能"**：直接、简洁作答，不编造系统中不存在的功能。
- **B 类——实际需要某个专门 Agent 才能完成的任务**：SHALL NOT 尝试自行执行或臆测结果；SHALL 明确告知用户该需求需使用对应的专门 Agent，并提示用户**必须先在上方选择对应 Agent** 后再发送请求。
- **C 类——与本系统完全无关**：SHALL 拒答，并引导用户选择合适的功能模块。

固定拒答 / 兜底引导话术 SHALL 覆盖全部专门 Agent（含 `project_expert`），不得遗漏。

#### Scenario: 专门任务被引导到对应 Agent

- **WHEN** 用户最新输入是一个明显属于某专门 Agent 的任务（例如要求重启某设备、分析某份日志、查询某个包的版本、定位某项目源码实现）
- **THEN** 回复明确指出需要使用对应的专门 Agent
- **AND** 回复要求用户先在上方选中该 Agent 再发送请求
- **AND** 回复不包含对该任务结果的臆测性解答

#### Scenario: 系统使用问题直接作答

- **WHEN** 用户最新输入是询问"Raven AI 系统怎么用 / 有什么功能"
- **THEN** GeneralAgent 直接给出系统使用说明，而不要求切换 Agent

### Requirement: General Agent emits a structured agent suggestion

`GeneralAgent` SHALL 在每轮回复的**最后一行**输出一个机器可读标记 `[[SUGGESTED_AGENT:<key>]]`，`<key>` 取值仅限 `device`、`log_analysis`、`package_search`、`project_expert`、`none`。`GeneralAgent.run_stream` SHALL 解析该标记，将其归一化为 `suggested_agent_type` 字段放入 `run_complete` 事件（`none`、缺失或非法值归一化为 `null`），并 SHALL 从呈现给用户的正文中**剥离全部标记**及尾随空白，使用户可见文本不含任何 `[[SUGGESTED_AGENT:...]]` 片段。

#### Scenario: B 类请求产出非空建议且正文已清理

- **WHEN** 用户最新输入属于 B 类（需某专门 Agent）
- **THEN** `run_complete` 事件的 `suggested_agent_type` 等于对应 key（如 `log_analysis`）
- **AND** `final_text` 中不包含任何 `[[SUGGESTED_AGENT:...]]` 文本

#### Scenario: A/C 类请求建议为 null

- **WHEN** 用户最新输入属于 A 类或 C 类
- **THEN** `run_complete` 事件的 `suggested_agent_type` 为 `null`

#### Scenario: 缺失或非法标记安全降级

- **WHEN** 模型未输出标记，或输出了不在允许集合内的 key
- **THEN** `suggested_agent_type` 归一化为 `null`
- **AND** 正文照常展示，不报错

### Requirement: Agent suggestion is propagated through the run lifecycle

系统 SHALL 把 `suggested_agent_type` 从 `GeneralAgent` 的 `run_complete` 事件透传到对外暴露的 run 生命周期：流式 SSE 的 `run_complete` 帧与终态 `done` 帧 SHALL 携带 `suggested_agent_type`；非流式 `ChatResponse` SHALL 包含 `suggested_agent_type` 字段。该字段 SHALL 为可选，缺省 `null`，且 SHALL NOT 改变任何既有事件类型或字段语义。run 快照（用于断线重连/回放）SHALL 保留该建议。

#### Scenario: done 帧携带建议

- **WHEN** 一次 GeneralAgent run 完成且产出了非空建议
- **THEN** SSE `done` 帧包含 `suggested_agent_type` 字段，值与 `run_complete` 一致

#### Scenario: 非流式响应携带建议

- **WHEN** 通过非流式 `/chat` 调用 GeneralAgent 且产出了非空建议
- **THEN** `ChatResponse.suggested_agent_type` 等于该建议

#### Scenario: 旧客户端向后兼容

- **WHEN** 客户端不识别 `suggested_agent_type`
- **THEN** 既有 `run_complete` / `done` / `ChatResponse` 字段保持不变，客户端可忽略该新增字段而正常工作

### Requirement: Front-end surfaces the suggestion and offers one-click switch

前端 SHALL 在本轮回复对应的会话状态中记录 `suggestedAgentType`，并在其非空时向用户展示一个醒目的、非阻塞的提示，告知该请求需要使用对应的专门 Agent，并提示用户先选择该 Agent。对可在前端 Agent 下拉中选择的专门 Agent（`log_analysis` / `package_search` / `project_expert`），前端 SHALL 提供一键切换到对应 Agent 选项；对 `device`（走独立设备操作入口），前端 SHALL 给出文字引导。每开始新一轮 run，前端 SHALL 将 `suggestedAgentType` 重置为 `null`。

#### Scenario: 非空建议展示提示条

- **WHEN** 某轮 GeneralAgent 回复带回 `suggested_agent_type = "project_expert"`
- **THEN** 前端展示提示，引导用户选择「项目专家」
- **AND** 提供一键切换到「项目专家」Agent 选项

#### Scenario: 新 run 重置建议

- **WHEN** 用户发起新一轮对话
- **THEN** 上一轮的建议提示被清除


### Requirement: GeneralAgent uses the project catalog for project recommendations
When a user asks a project-bound question through GeneralAgent, GeneralAgent SHALL call `mcp__project_repo__discover_projects` before naming a registered project or asserting that no project fits. It SHALL still recommend the appropriate specialized Agent, and SHALL include the matching project name/code when catalog evidence is clear.

#### Scenario: GeneralAgent recommends a concrete project and Agent
- **WHEN** a source-code question clearly matches one enabled project card
- **THEN** GeneralAgent tells the user to use ProjectExpertAgent with that project name/code
- **AND** its structured `suggested_agent_type` remains `project_expert`

#### Scenario: GeneralAgent reports no suitable project
- **WHEN** a project-bound question matches no card in the complete discovery response
- **THEN** GeneralAgent says no suitable project is currently registered
- **AND** it does not invent a project or answer the domain question

#### Scenario: Discovery is unavailable
- **WHEN** the configured provider cannot register the discovery tool
- **THEN** GeneralAgent falls back to specialized-Agent routing without naming a concrete project
- **AND** it does not claim that the project catalog has no match

### Requirement: General Agent runs a bounded Claude Agent SDK tool loop

GeneralAgent SHALL drive `claude_agent_sdk.query()` as a message-by-message Agent loop until a terminal result, timeout, cancellation/error, or its GeneralAgent-specific turn bound. It SHALL project SDK tool calls, tool results, partial answer text, usage, and the terminal result into the existing chat trace event vocabulary while preserving the final plain-text response and `suggested_agent_type` contract.

#### Scenario: Project discovery executes inside the loop

- **WHEN** the model calls `mcp__project_repo__discover_projects` while handling a project-bound request
- **THEN** GeneralAgent continues the SDK loop with the tool result and produces a final routing response
- **AND** the run emits correlated tool start/end trace events before `run_complete`

#### Scenario: Loop bound is recoverable

- **WHEN** the SDK reaches the configured GeneralAgent turn bound after producing usable text
- **THEN** GeneralAgent completes with the collected text instead of failing the entire chat run
- **AND** if no usable text exists it returns the existing safe routing fallback

### Requirement: General Agent has least-privilege project discovery

When the configured provider supports in-process MCP tools, GeneralAgent SHALL register the discovery-only project repository MCP server and allow `mcp__project_repo__discover_projects`. It MUST NOT register or allow `mcp__project_repo__lookup_project_repo`, filesystem, shell, web, task, or write tools. When MCP tools are unsupported, it SHALL route to specialist Agents without naming a concrete registered project or claiming that no suitable project exists.

#### Scenario: Discovery-only server is registered

- **WHEN** GeneralAgent builds SDK options for an MCP-capable provider
- **THEN** its allowed tools include `mcp__project_repo__discover_projects`
- **AND** its registered project repository server exposes no credential-bearing lookup capability

#### Scenario: Unsupported provider degrades safely

- **WHEN** GeneralAgent runs with a provider that does not support MCP server tools
- **THEN** no project repository MCP server or MCP allowed tool is configured
- **AND** its prompt forbids concrete project-existence and no-match assertions

### Requirement: General Agent supports Agent-level Skills without project binding

The system SHALL register `general_agent` in the existing Agent Skills administration. Before every GeneralAgent SDK run it SHALL materialize enabled Agent-level Skills into the isolated run workspace, allow the SDK `Skill` tool when Skills are available, and set `setting_sources=["project"]` so the SDK can discover them. It SHALL NOT load project-level Skills, accept a project code, or appear in project-level Skill/prompt configuration surfaces.

#### Scenario: Enabled GeneralAgent Skill is loaded

- **WHEN** an enabled Agent Skill is installed for `general_agent`
- **THEN** the run workspace contains `.claude/skills/<skill-name>/SKILL.md`
- **AND** SDK options allow `Skill` and use `setting_sources=["project"]`
- **AND** `run_start` and `run_complete` report the loaded Skill name

#### Scenario: GeneralAgent remains absent from projects

- **WHEN** project-level Agent configuration keys and project selection choices are enumerated
- **THEN** `general_agent` is absent
- **AND** project-bound questions are still routed to the relevant specialist Agent

### Requirement: General Agent always uses the small fast model profile

GeneralAgent SHALL pass an explicit model resolved from `anthropic_small_fast_model` or the active provider's `default_small_fast_model`. It MUST NOT use the configured primary Anthropic model or the provider's primary default, and SHALL retain GeneralAgent-specific max-token, timeout, and turn bounds.

#### Scenario: Primary and small models differ

- **WHEN** both a primary model and a small/fast model are configured
- **THEN** GeneralAgent SDK options use the small/fast model
- **AND** ProjectExpertAgent and LogAnalysisAgent remain free to use the primary model

#### Scenario: Small model is unavailable

- **WHEN** neither an explicit nor provider-default small/fast model can be resolved
- **THEN** GeneralAgent fails with a clear configuration error
- **AND** it does not silently execute on the primary model
