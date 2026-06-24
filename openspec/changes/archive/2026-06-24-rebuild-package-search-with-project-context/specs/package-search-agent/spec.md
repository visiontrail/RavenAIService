## ADDED Requirements

### Requirement: 项目身份来自用户必选的项目仓库
重构包检索 Agent 的每次运行 SHALL 绑定一个用户显式选择的项目仓库（`project_repo`）。新会话请求缺少 `project_repo_id` 时，API MUST 在开始流式响应前返回 HTTP 400（错误体含 `reason: "project_repo_required"`）；`project_repo_id` 对应的项目不存在或 `enabled=false` 时 MUST 返回 4xx。项目身份 MUST 写入工作区 `task.json.repo_info`（`source="user_selected_project_repo"`），MUST NOT 把 git token 落盘。

#### Scenario: 新会话缺少项目被拒绝
- **WHEN** 客户端对一个没有既存工作区的会话调用重构包检索且未携带 `project_repo_id`
- **THEN** API MUST 返回 HTTP 400 且错误体包含 `reason: "project_repo_required"`，MUST NOT 启动 Agent loop

#### Scenario: 项目身份写入工作区
- **WHEN** 用户选择项目 `demo-proj` 发起检索
- **THEN** 工作区 `task.json.repo_info` MUST 含 `project_code="demo-proj"`、`repo_url`、`default_branch`，且文件内容 MUST NOT 含任何 git token

#### Scenario: 禁用项目被拒绝
- **WHEN** 请求携带的 `project_repo_id` 对应项目 `enabled=false`
- **THEN** API MUST 返回 4xx 错误，MUST NOT 启动 Agent loop

### Requirement: Agent 具备项目仓库访问能力
Agent 运行 SHALL 在隔离工作区（`repo/` 占位目录 + `task.json`，与项目专家同构）中进行，允许的工具 SHALL 为 `Bash`、`Read`、`Grep`、`Glob`、`mcp__project_repo__lookup_project_repo` 以及项目限定的包元数据 MCP 工具。Agent MUST 能通过 `lookup_project_repo` 解析所选项目的 clone URL（token 仅在工具响应内传递）并克隆仓库。任务结束后工作区按会话生命周期清理（详见会话级工作区复用需求）。

#### Scenario: Agent 克隆所选项目仓库
- **WHEN** 用户的问题需要 Git 上下文（如"v2.3 这个包对应哪些提交"）
- **THEN** Agent MUST 通过 `lookup_project_repo` 获取 clone URL 并在工作区 `repo/` 下克隆所选项目仓库，tool_trace 中 MUST NOT 出现明文 token

#### Scenario: 纯元数据问题不强制克隆
- **WHEN** 用户的问题仅凭包元数据即可回答（如"列出该项目最新 3 个非补丁包"）
- **THEN** Agent SHOULD 仅调用包元数据工具完成回答，不执行仓库克隆

### Requirement: Git 提交记录优先的分析策略
系统提示词 SHALL 向 Agent 声明强制的分析顺序契约：① 优先使用包元数据工具；② 需要仓库信息时优先用 Git 提交记录（`git log` / `git show` / `git diff --stat` 等）分析；③ 仅当提交记录不足以回答时才读取源码文件（`Read` / `Grep` 源码），且最终回答中 MUST 说明为何需要升级到读代码。提示词 SHALL 建议浅克隆/部分克隆策略以控制成本。

#### Scenario: 提交记录足以回答时不读代码
- **WHEN** 用户问"这两个版本的包之间项目改了什么"且 `git log` 输出足以回答
- **THEN** Agent MUST 基于提交记录作答，tool_trace 中 MUST NOT 出现对 `repo/` 下源码文件的 `Read`/`Grep` 调用

#### Scenario: 必要时升级读代码并说明理由
- **WHEN** 提交信息过于笼统、无法回答用户关于某变更细节的问题
- **THEN** Agent MAY 读取相关源码文件，且最终回答 MUST 说明读取代码的原因

### Requirement: 会话级工作区复用与聊天三端点
系统 SHALL 提供 `POST /package-search/stream`、`POST /package-search/cancel`、`GET /package-search/result` 三个端点（与项目专家三端点同构）：stream 端点以 SSE 透传 AgentTraceEvent 并支持登录态会话持久化；同一会话的后续提问 MUST 复用首轮绑定的项目与工作区（已克隆的仓库不重复克隆），后续请求携带不同 `project_repo_id` MUST NOT 切换已绑定项目；cancel 端点通过 cancel_event 终止运行中的任务；result 端点提供轮询兜底。非所有者 MUST 无法取消或查询他人会话（PermissionError → 403）。

#### Scenario: 后续提问复用工作区
- **WHEN** 用户在同一会话中发起第二个问题且未重新选择项目
- **THEN** 服务 MUST 复用既存工作区与已克隆仓库，MUST NOT 要求重新传 `project_repo_id`

#### Scenario: 运行中任务可取消
- **WHEN** 客户端对运行中的会话调用 `POST /package-search/cancel`
- **THEN** Agent loop MUST 在下一个消息边界终止并下发 `cancelled` 事件，result 端点状态变为 cancelled

#### Scenario: 会话项目绑定不漂移
- **WHEN** 同一会话的后续请求携带与首轮不同的 `project_repo_id`
- **THEN** 服务 MUST 继续使用首轮绑定的项目（与项目专家行为一致）

### Requirement: 系统提示词后台可配置
重构包检索 Agent 的系统提示词与用户提示词模板 SHALL 从 `prompts_config.yaml` 的 `claude_agent_package_search.generic` 区块加载（支持按 locale 的多语言变体、`zh` 兜底），MUST NOT 再硬编码于 Python 源码。该区块 MUST 注册到后台提示词管理元数据（`PROMPT_FUNCTION_META` / `PROMPT_AGENT_META`），在 AdminPrompts 页面可见可编辑；保存后 MUST 通过缓存失效立即生效（`_invalidate_prompt_caches` 覆盖 package_search 提示词缓存）。

#### Scenario: 后台编辑提示词即时生效
- **WHEN** 管理员在后台提示词管理页修改 `claude_agent_package_search.generic.system_prompt` 并保存
- **THEN** 下一次重构包检索运行 MUST 使用新提示词内容，无需重启服务

#### Scenario: 提示词条目出现在后台列表
- **WHEN** 管理员加载提示词管理页
- **THEN** 可编辑条目 MUST 包含功能名"重构包检索"下的 `claude_agent_package_search.generic.system_prompt`（含各语言变体）

### Requirement: 前端重构包 Agent 必选项目
`AIChat.vue` 中选择重构包 Agent（`package-manager`）后，SHALL 展示与日志分析/项目专家相同位置的项目选择下拉（选项来自已启用项目注册表），且与项目专家逻辑一致：未选择项目时发送按钮 MUST 禁用、尝试发送 MUST 弹出"请先选择项目"提示并中止。GeneralAgent 路由建议一键切换到重构包 Agent 时 MUST 同样触发项目选项加载与必选校验。发送请求 MUST 携带 `project_repo_id`。

#### Scenario: 选择重构包 Agent 后出现项目下拉
- **WHEN** 用户在对话框选择重构包 Agent
- **THEN** UI MUST 显示项目选择下拉并加载已启用项目列表

#### Scenario: 未选项目无法发送
- **WHEN** 用户选择了重构包 Agent、输入了问题但未选择项目并尝试发送
- **THEN** 前端 MUST 阻止发送并提示需先选择项目

#### Scenario: 建议切换同样必选项目
- **WHEN** GeneralAgent 返回 `suggested_agent_type="package_search"` 且用户点击一键切换
- **THEN** UI MUST 切到重构包 Agent 并按同一规则要求选择项目后才能发送

## MODIFIED Requirements

### Requirement: Claude Agent SDK 驱动的重构包检索 Agent
系统 SHALL 提供一个名为 `PackageSearchAgent` 的服务，使用 Claude Agent SDK 的 agent loop 处理自然语言的重构包检索请求：运行绑定用户所选项目，在隔离工作区中执行，通过 in-process MCP 工具读取 `RavenPackageService` 维护的包元数据（服务端限定为所选项目的包），并可访问所选项目的 Git 仓库。trace 层与运行状态机 SHALL 复用 `log_analysis` 的实现（与项目专家同构），淘汰 package_search 自有的 trace 拷贝。Agent MUST NOT 依赖任何 embedding、向量库、近似检索；MUST NOT 复用旧的 `intelligent_search` / `similarity_search` / `score_package` / `package_to_text` 代码路径。

#### Scenario: 处理简单的字段检索请求
- **WHEN** 用户选择项目 `demo-proj` 后发送 query "找一下名字带 katx 的最新两个包"
- **THEN** Agent 通过 `search_packages_by_text` 或 `list_packages` 工具至少调用一次后，返回的 final assistant message 中包含一段 fenced JSON 块，`recommended_package_ids` 与 `relevant_package_ids` 均为该项目下真实存在的包 ID 字符串

#### Scenario: 处理需要多工具组合的版本范围请求
- **WHEN** 用户在所选项目下发送 query "我要 v2.3 之后的非补丁包，按发布时间倒序前 3 个"
- **THEN** Agent 调用 `filter_packages_by_version`（带 `version_min="2.3"`、`include_prerelease=False`）与 `list_packages`（带 `filters.is_patch=False`、`sort.by="createdAt"`、`sort.order="desc"`、`limit<=3`）至少一次，最终 `recommended_package_ids` 长度 ≤ 3 且全部对应满足条件的真实包

#### Scenario: 检索无结果
- **WHEN** 用户 query 描述的包在所选项目下不存在
- **THEN** Agent 在尝试至少一次工具调用后返回的 fenced JSON 中 `recommended_package_ids=[]` 且 `relevant_package_ids=[]`，自然语言部分明确说明"未找到匹配的包"

#### Scenario: 模型幻觉 ID 被拦截
- **WHEN** Agent 在 fenced JSON 中返回了任何在所选项目范围内查不到的包 ID
- **THEN** 服务层 MUST 在响应前过滤掉这些 ID，并在 `tool_trace` 末尾追加一条 `{type: "warning", message: "filtered N invalid ids"}`，响应体中的 ID 数组不再包含无效 ID

### Requirement: 重构包数据访问工具集
系统 SHALL 通过 in-process MCP server 暴露以下 7 个包元数据工具：`list_packages`、`get_package_by_id`、`search_packages_by_text`、`filter_packages_by_version`、`list_components`、`find_packages_by_component`、`package_stats`。MCP server MUST 按运行绑定的 `project_code` 构建，所有工具 MUST 在服务端强制限定为该项目的包（`projectCode` 过滤），不依赖模型自觉。`list_packages.filters.type`、`filter_packages_by_version.package_type`、`list_components.package_type` 参数 MUST 移除；`package_stats.group_by` 的合法值为 `version_major | tag | isPatch`（`type` 维度移除）。每个工具 MUST 声明 JSON schema，直接调用 `RavenPackageService`，不读文件、不调外部服务，返回结构化文本 JSON。

#### Scenario: 工具结果限定在所选项目
- **WHEN** Agent 在绑定项目 `demo-proj` 的运行中调用 `list_packages`（不带任何过滤参数）
- **THEN** 返回 items MUST 全部满足 `projectCode="demo-proj"`，`total` MUST 为该项目的包总数

#### Scenario: get_package_by_id 不泄露其他项目的包
- **WHEN** Agent 调用 `get_package_by_id` 传入一个属于其他项目的真实包 ID
- **THEN** 工具 MUST 返回 `{"error": "not_found", "id": "..."}`

#### Scenario: 工具输入校验拒绝越界 limit
- **WHEN** Agent 调用 `list_packages` 且 `limit` 超过配置 `package_search_max_limit`
- **THEN** 工具实现 MUST 把 limit 夹断到 `package_search_max_limit`，并在返回结果中包含 `total` 字段反映过滤前真实数量

#### Scenario: filter_packages_by_version 正确比较 SemVer
- **WHEN** Agent 调用 `filter_packages_by_version(version_min="2.10.0")`
- **THEN** 结果 items 中 MUST 包含项目内 `version="2.10.0"` 与 `version="2.11.0"` 的包，MUST NOT 包含 `version="2.9.9"`（即按 SemVer 而非字符串字典序比较）

#### Scenario: include_prerelease=False 时过滤预发布版本
- **WHEN** Agent 调用 `filter_packages_by_version(...)` 且 `include_prerelease` 缺省或 `False`
- **THEN** 结果 items MUST NOT 包含任何 `version` 被 `packaging.version.parse(...).is_prerelease == True` 的包

#### Scenario: PackageBrief 字段最小化
- **WHEN** 任何工具返回 `PackageBrief` 形式的 items
- **THEN** items 中的每个对象 MUST 仅包含 `id, name, version, projectCode, isPatch, createdAt, components, tags, size` 这些字段（不含 sha256、不含磁盘 path）

### Requirement: 搜索 Agent 的 HTTP API
系统 SHALL 提供 `POST /raven/packages/agent-search` 接口接收用户自然语言查询，并以非流式或 SSE 流式返回结果。请求体 MUST 包含必填的 `project_repo_id`（整数），缺失或对应项目不存在/禁用时 MUST 返回 HTTP 400（错误体含 `reason: "project_repo_required"` 或项目无效说明）。该接口 MUST 复用 `/raven/packages` 现有的鉴权配置，请求体 `query` 字段为必填且长度 ≤ 1000 字符（超长 MUST 返回 400）。该端点每次请求独立准备/清理工作区（不做会话级复用），Agent 行为与聊天端点一致。

#### Scenario: 非流式响应包含结构化推荐
- **WHEN** 客户端 `POST /raven/packages/agent-search` body `{"query": "find latest ka-tx package", "project_repo_id": 3}` 不带 `stream` 或 `stream=false`
- **THEN** 响应体 MUST 是 JSON，且字段 `answer:string, recommended_package_ids:string[], relevant_package_ids:string[], tool_trace:object[], model:string, usage:object` 全部存在；`recommended_package_ids` 中所有 ID MUST 属于所选项目且通过存在性校验

#### Scenario: 缺失 project_repo_id 被拒绝
- **WHEN** 客户端 `POST /raven/packages/agent-search` body 不含 `project_repo_id`
- **THEN** API MUST 返回 HTTP 400，错误体含 `reason: "project_repo_required"`

#### Scenario: 流式响应使用 AgentTraceEvent 通道
- **WHEN** 客户端 `POST /raven/packages/agent-search` body `{"query": "...", "project_repo_id": 3, "stream": true}`
- **THEN** 响应 MUST 以 `text/event-stream` Content-Type 推送 SSE，事件类型对齐 [`docs/agent_trace_protocol.md`](../../../../docs/agent_trace_protocol.md)；`final` 事件 data 与非流式响应体结构一致

#### Scenario: query 过长被拒绝
- **WHEN** 客户端提交 `query` 字符串长度 > 1000
- **THEN** API MUST 返回 HTTP 400，错误体中说明长度限制

#### Scenario: query 为空字符串被拒绝
- **WHEN** 客户端提交 `query` 为空字符串或仅含空白
- **THEN** API MUST 返回 HTTP 400

### Requirement: 对话框集成走流式 SSE

主对话框（`AIChat.vue`）对重构包 Agent 的调用 SHALL 走 `POST /package-search/stream` 聊天端点，经 runs store 统一运行态管线（start/cancel/恢复逻辑与项目专家一致），淘汰页面内自维护的 `runPackageAgent` SSE 处理。其 trace 与 `answer_delta` MUST 经与 DeviceAgent / 日志分析 / 项目专家相同的统一渲染管线实时呈现，四个 Agent 在对话框中的流式行为 MUST 一致。

调用过程中 MUST NOT 长时间停留在静态"正在思考..."占位：一旦后端产出首条 trace 或 `answer_delta`，UI MUST 实时更新。`final` 事件携带的结构化结果（`recommended_package_ids`、`relevant_package_ids` 等）MUST 仍用于推荐包的结构化展示与（登录态下的）会话持久化。

非流式 `agent-search` 端点 MUST 保留供非对话场景（如 RavenManager 智能检索）调用，本要求 MUST NOT 移除或破坏它。

#### Scenario: 对话框中重构包 Agent 实时呈现

- **WHEN** 用户在对话框中选择项目并向重构包 Agent 发起一次检索
- **THEN** 前端 MUST 通过 `/package-search/stream` 订阅 SSE，实时渲染 trace 与逐字答复，UI MUST NOT 全程停留在"正在思考..."占位直到一次性返回

#### Scenario: 四个 Agent 流式行为一致

- **WHEN** 分别向 DeviceAgent、日志分析 Agent、项目专家、重构包 Agent 发起一次对话
- **THEN** 四者 MUST 都通过 SSE 实时透传 trace，并都以 `answer_delta` 逐字呈现最终答复（在 provider 支持分块流式时）

#### Scenario: 结构化结果仍可用

- **WHEN** 重构包 Agent 流式完成并下发 `final` 事件
- **THEN** `final.data` 中的 `recommended_package_ids` MUST 仍被用于渲染推荐包卡片，登录态下该轮对话 MUST 被持久化

#### Scenario: 对话中可取消重构包运行

- **WHEN** 重构包 Agent 运行中用户点击取消
- **THEN** 前端 MUST 经 runs store 调用 `/package-search/cancel`，UI 呈现取消态（与项目专家一致）

#### Scenario: 非流式端点保留

- **WHEN** 非对话场景以 `stream=false`（或不带 `stream`）调用 `POST /raven/packages/agent-search`
- **THEN** 该端点 MUST 仍返回与契约一致的非流式 JSON 响应
