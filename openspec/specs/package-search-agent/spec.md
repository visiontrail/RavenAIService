## ADDED Requirements

### Requirement: Claude Agent SDK 驱动的重构包检索 Agent
系统 SHALL 提供一个名为 `PackageSearchAgent` 的服务，使用 Claude Agent SDK 的 agent loop 处理自然语言的重构包检索请求，并通过 in-process MCP 工具直接读取 `RavenPackageService` 维护的包元数据。Agent MUST NOT 依赖任何 embedding、向量库、近似检索；MUST NOT 复用旧的 `intelligent_search` / `similarity_search` / `score_package` / `package_to_text` 代码路径。

#### Scenario: 处理简单的字段检索请求
- **WHEN** 用户发送 query "找一下名字带 katx 的最新两个包"
- **THEN** Agent 通过 `search_packages_by_text` 或 `list_packages` 工具至少调用一次后，返回的 final assistant message 中包含一段 fenced JSON 块，`recommended_package_ids` 与 `relevant_package_ids` 均为后端存在的真实包 ID 字符串

#### Scenario: 处理需要多工具组合的版本范围请求
- **WHEN** 用户发送 query "我要 lingxi-10 v2.3 之后的非补丁包，按发布时间倒序前 3 个"
- **THEN** Agent 调用 `filter_packages_by_version`（带 `package_type="lingxi-10"`、`version_min="2.3"`、`include_prerelease=False`）与 `list_packages`（带 `filters.is_patch=False`、`sort.by="createdAt"`、`sort.order="desc"`、`limit<=3`）至少一次，最终 `recommended_package_ids` 长度 ≤ 3 且全部对应满足条件的真实包

#### Scenario: 检索无结果
- **WHEN** 用户发送 query 描述的包在数据库中不存在
- **THEN** Agent 在尝试至少一次工具调用后返回的 fenced JSON 中 `recommended_package_ids=[]` 且 `relevant_package_ids=[]`，自然语言部分明确说明"未找到匹配的包"

#### Scenario: 模型幻觉 ID 被拦截
- **WHEN** Agent 在 fenced JSON 中返回了任何在 `RavenPackageService.get_package(id)` 查不到的 ID
- **THEN** API 层 MUST 在响应前过滤掉这些 ID，并在 `tool_trace` 末尾追加一条 `{type: "warning", message: "filtered N invalid ids"}`，响应体中的 ID 数组不再包含无效 ID

### Requirement: 重构包数据访问工具集
系统 SHALL 通过 in-process MCP server 暴露以下 7 个工具（且仅这些工具），每个工具直接调用 `RavenPackageService`，不读文件、不调外部服务：`list_packages`、`get_package_by_id`、`search_packages_by_text`、`filter_packages_by_version`、`list_components`、`find_packages_by_component`、`package_stats`。每个工具 MUST 声明 JSON schema，输入参数命名 / 类型与 design.md 中的表格一致；返回结构化文本 JSON。

#### Scenario: 工具输入校验拒绝越界 limit
- **WHEN** Agent 调用 `list_packages` 且 `limit` 超过配置 `package_search_max_limit`
- **THEN** 工具实现 MUST 把 limit 夹断到 `package_search_max_limit`，并在返回结果中包含 `total` 字段反映过滤前真实数量

#### Scenario: filter_packages_by_version 正确比较 SemVer
- **WHEN** Agent 调用 `filter_packages_by_version(package_type="lingxi-10", version_min="2.10.0")`
- **THEN** 结果 items 中 MUST 包含 `version="2.10.0"` 与 `version="2.11.0"`，MUST NOT 包含 `version="2.9.9"`（即按 SemVer 而非字符串字典序比较）

#### Scenario: include_prerelease=False 时过滤预发布版本
- **WHEN** Agent 调用 `filter_packages_by_version(...)` 且 `include_prerelease` 缺省或 `False`
- **THEN** 结果 items MUST NOT 包含任何 `version` 被 `packaging.version.parse(...).is_prerelease == True` 的包

#### Scenario: get_package_by_id 处理不存在的 ID
- **WHEN** Agent 调用 `get_package_by_id` 传入数据库中不存在的 ID
- **THEN** 工具 MUST 返回 `{"error": "not_found", "id": "..."}` 而不是抛异常

#### Scenario: PackageBrief 字段最小化
- **WHEN** 任何工具返回 `PackageBrief` 形式的 items
- **THEN** items 中的每个对象 MUST 仅包含 `id, name, version, packageType, isPatch, createdAt, components, tags, size` 这些字段（不含 sha256、不含磁盘 path）

### Requirement: 搜索 Agent 的 HTTP API
系统 SHALL 提供 `POST /raven/packages/agent-search` 接口接收用户自然语言查询，并以非流式或 SSE 流式返回结果。该接口 MUST 复用 `/raven/packages` 现有的鉴权配置，请求体 `query` 字段为必填且长度 ≤ 1000 字符（超长 MUST 返回 400）。

#### Scenario: 非流式响应包含结构化推荐
- **WHEN** 客户端 `POST /raven/packages/agent-search` body `{"query": "find latest ka-tx package"}` 不带 `stream` 或 `stream=false`
- **THEN** 响应体 MUST 是 JSON，且字段 `answer:string, recommended_package_ids:string[], relevant_package_ids:string[], tool_trace:object[], model:string, usage:object` 全部存在；`recommended_package_ids` 中所有 ID MUST 通过 `RavenPackageService.get_package` 校验

#### Scenario: 流式响应使用 AgentTraceEvent 通道
- **WHEN** 客户端 `POST /raven/packages/agent-search` body `{"query": "...", "stream": true}`
- **THEN** 响应 MUST 以 `text/event-stream` Content-Type 推送 SSE，事件类型对齐 [`docs/agent_trace_protocol.md`](../../../docs/agent_trace_protocol.md) 中的 `assistant_delta` / `tool_use` / `tool_result` / `final`；`final` 事件 data 与非流式响应体结构一致

#### Scenario: query 过长被拒绝
- **WHEN** 客户端提交 `query` 字符串长度 > 1000
- **THEN** API MUST 返回 HTTP 400，错误体中说明长度限制

#### Scenario: query 为空字符串被拒绝
- **WHEN** 客户端提交 `query` 为空字符串或仅含空白
- **THEN** API MUST 返回 HTTP 400

### Requirement: 最终回复的结构化解析契约
Agent 的最终 assistant message MUST 包含一个 ```json fenced code block，块内为合法 JSON 对象，至少包含 `recommended_package_ids:string[]` 与 `relevant_package_ids:string[]` 两个字段。API 层 SHALL 解析该 fenced block 并将其中的 ID 校验后填入响应；解析失败时降级为空数组并将原始自然语言文本完整返回给客户端。

#### Scenario: 模型遗漏 fenced JSON 时的降级
- **WHEN** Agent 最终消息中未发现 ```json fenced block
- **THEN** API MUST 仍以 200 返回，`answer` 字段为模型原文，`recommended_package_ids` 与 `relevant_package_ids` 均为 `[]`，`tool_trace` 末尾追加 `{type:"warning", message:"missing structured answer"}`

#### Scenario: fenced JSON 解析失败时的降级
- **WHEN** fenced block 中的内容不是合法 JSON 或缺少必需字段
- **THEN** API MUST 仍以 200 返回，`recommended_package_ids` 与 `relevant_package_ids` 均为 `[]`，`tool_trace` 末尾追加 `{type:"warning", message:"unparsable structured answer"}`

### Requirement: 对话框集成走流式 SSE

主对话框（`AIChat.vue`）对重构包 Agent 的调用 SHALL 走 SSE 流式路径（`POST /raven/packages/agent-search` 且 `stream: true`，经前端 `streamPackagesAgentSearch`），而非阻塞式非流式 REST。其 trace 与 `answer_delta` MUST 经与 DeviceAgent / 日志分析 Agent 相同的统一渲染管线实时呈现，三个 Agent 在对话框中的流式行为 MUST 一致。

调用过程中 MUST NOT 长时间停留在静态"正在思考..."占位：一旦后端产出首条 trace 或 `answer_delta`，UI MUST 实时更新。`final` 事件携带的结构化结果（`recommended_package_ids`、`relevant_package_ids` 等）MUST 仍用于推荐包的结构化展示与（登录态下的）会话持久化。

非流式 `agent-search` 端点 MUST 保留供非对话场景调用，本要求 MUST NOT 移除或破坏它。

#### Scenario: 对话框中重构包 Agent 实时呈现

- **WHEN** 用户在对话框中 @重构包 Agent 发起一次检索
- **THEN** 前端 MUST 通过 `stream: true` 订阅 SSE，实时渲染 trace 与逐字答复，UI MUST NOT 全程停留在"正在思考..."占位直到一次性返回

#### Scenario: 三个 Agent 流式行为一致

- **WHEN** 分别向 DeviceAgent、日志分析 Agent、重构包 Agent 发起一次对话
- **THEN** 三者 MUST 都通过 SSE 实时透传 trace，并都以 `answer_delta` 逐字呈现最终答复（在 provider 支持分块流式时）

#### Scenario: 结构化结果仍可用

- **WHEN** 重构包 Agent 流式完成并下发 `final` 事件
- **THEN** `final.data` 中的 `recommended_package_ids` MUST 仍被用于渲染推荐包卡片，登录态下该轮对话 MUST 被持久化

#### Scenario: 非流式端点保留

- **WHEN** 非对话场景以 `stream=false`（或不带 `stream`）调用 `POST /raven/packages/agent-search`
- **THEN** 该端点 MUST 仍返回与既有契约一致的非流式 JSON 响应

### Requirement: 删除旧 RAG 实现与路由
变更交付后，系统 MUST NOT 再保留以下任何代码或路由：`RavenPackageService.rebuild_search_index`、`search_status`、`similarity_search`、`intelligent_search`、`suggestions`、`score_package`、`package_to_text`、`vector_store_path` / `vector_meta_file` 字段；`/raven/search/status`、`/raven/search/rebuild-index`、`/raven/search/similarity`、`/raven/search/intelligent`、`/raven/search/suggestions` 路由；`app/config.py` 中的 `raven_vector_store_path` / `rag_embedding_provider` / `rag_embedding_model` 字段；包上传 / 删除流程对 `rebuild_search_index` 的任何调用。

#### Scenario: 旧路由不再注册
- **WHEN** 启动 FastAPI app 后枚举所有路由
- **THEN** 路由列表 MUST NOT 包含上述 5 条 `/raven/search/*` 路径

#### Scenario: 旧 service 方法被移除
- **WHEN** 在测试中 `from app.services.raven_package_service import raven_package_service` 后访问 `intelligent_search` / `similarity_search` / `rebuild_search_index` / `search_status` / `suggestions` 任一属性
- **THEN** Python MUST 抛出 `AttributeError`

#### Scenario: 包上传不再触发索引重建
- **WHEN** 客户端 `POST /raven/upload` 上传一个合法 `.tgz`
- **THEN** 响应体 MUST NOT 包含 `vectorIndexRebuild` 字段；服务进程 MUST NOT 调用任何 `rebuild_search_index` 相关代码（通过测试 mock 校验未被调用）
