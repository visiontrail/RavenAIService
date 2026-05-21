## Why

当前的"重构包智能检索"功能（`app/services/raven_package_service.py` 中的 `intelligent_search` / `similarity_search` / `rebuild_search_index` / `search_status` 以及 `app/api/packages.py` 下的 `/search/*` 路由）名义上是 RAG，但实际上只做了一次基于 token 命中数的字符串打分（`score_package`），把分词结果硬塞回模板化的回复（"已找到 X 个相关重构包…"），既没有真正的向量召回，也无法理解用户的自然语言需求（例如"我要 LX10 v2.3 之后的补丁包，按时间倒序"、"哪些包包含 cucp 组件且 sha256 是 abcd..."）。同时项目其它 Agent 场景已统一迁移到 **Claude Agent SDK**（`openspec/specs/log-analysis-agent`、`openspec/specs/anthropic-llm-config`），保留这套"伪 RAG"既割裂技术栈，也无法利用 SDK 的 agent loop / tool use 能力。

我们希望**彻底抛弃 RAG（向量召回 + 拼模板回答）这条路径**，改为：让 Claude Agent SDK 驱动一个**带工具调用循环的 Agent**，由模型自主决定调用哪些"直接查询重构包数据库"的工具（按字段过滤、按版本范围排序、读取单包详情、读取 components / tags / sha256、统计聚合等），用工具返回的真实数据回答用户问题，并显式选出推荐的包 ID。

## What Changes

- **BREAKING** 删除"伪 RAG"实现：
  - `app/services/raven_package_service.py` 中的 `rebuild_search_index`、`search_status`、`similarity_search`、`intelligent_search`、`suggestions`、`score_package`、`package_to_text`、`vector_store_path` / `vector_meta_file` 字段与目录创建逻辑；
  - `app/api/packages.py` 中 `/search/status`、`/search/rebuild-index`、`/search/similarity`、`/search/intelligent`、`/search/suggestions` 五条路由及其调用点；
  - `app/api/packages.py` 在 `upload_package` / `bulk_upload` 等流程里对 `rebuild_search_index()` 的同步触发；
  - `app/config.py` 中仅服务于该 RAG 的字段：`raven_vector_store_path`、`rag_embedding_provider`、`rag_embedding_model`；磁盘上对应的 `data/raven/vector-store/` 目录在运维迁移说明中标记为可删除。
- **BREAKING** 前端不再调用 `/search/*` 旧路由：移除 `frontend/src/api/raven.ts` 中的 `rebuildRavenIndex`、`getRavenSearchStatus`、`intelligentSearchPackages`、`getRavenSearchSuggestions` 等导出，及 `frontend/src/views/RavenManager.vue` 里调用它们的"智能搜索对话框"逻辑，统一改为调用新的 Agent 接口。
- 新增 **`PackageSearchAgent`**（`app/agents/package_search/`），完全基于 Claude Agent SDK：
  - 使用统一的 `anthropic_client`（来自现有 `anthropic-llm-config` capability），不再依赖 `langchain_openai` / `langgraph`；
  - 在 in-process MCP server 中注册一组"直接查重构包数据库"的工具（不做向量召回，所有调用直接命中 `RavenPackageService` 的元数据存储），由 Agent loop 自主组合调用，详见 design.md：
    - `list_packages(filters?, sort?, limit?, offset?)`
    - `get_package_by_id(id)`
    - `search_packages_by_text(text, fields?, limit?)`（纯字面量子串匹配，不是 embedding）
    - `filter_packages_by_version(package_type?, version_min?, version_max?, include_prerelease?)`
    - `list_components(package_type?)` / `find_packages_by_component(component_name, version?)`
    - `package_stats(group_by?)`（按 type/version/tag 聚合计数，用于支持"最近哪类包最多"之类问题）
  - 系统提示词引导 Agent：先用工具调查事实，再回答；必须在回答末尾用结构化 JSON 块给出 `recommended_package_ids` 与 `relevant_package_ids`，并附"工具调用证据"（哪几次工具调用、返回了什么）。
- 新增 **HTTP API**：`POST /packages/agent-search`，请求体 `{ query: string, session_id?: string, stream?: boolean }`，响应：非流式返回 `{ answer, recommended_package_ids, relevant_package_ids, tool_trace, model, usage }`；流式（`stream: true`）以 SSE 形式按 Claude Agent SDK 的 `MessageStream` 协议下发 `assistant` / `tool_use` / `tool_result` 事件，复用 [`docs/agent_trace_protocol.md`](docs/agent_trace_protocol.md) 中已定义的 `AgentTraceEvent` 通道命名约定。
- 前端 `RavenManager.vue` 的"智能搜索"对话框改为调用 `/packages/agent-search`：
  - 用户提问 → 显示 Agent 推理 / 工具调用气泡（复用 `LogDetail.vue` 已有的 trace 渲染样式）→ 终态展示推荐包列表（点击跳详情）。
- **不引入** 任何 embedding 模型、向量库、ANN 检索；`requirements.txt` 不新增依赖（`claude-agent-sdk` 已存在）。

## Capabilities

### New Capabilities
- `package-search-agent`：基于 Claude Agent SDK 的重构包智能检索能力。提供：(1) `PackageSearchAgent` 主流程（system prompt + allowed_tools + agent loop）；(2) in-process MCP 工具集（直接查 `RavenPackageService` 元数据，无向量召回）；(3) `/packages/agent-search` HTTP API（非流式 + SSE 流式）；(4) 与既有 `AgentTraceEvent` 通道兼容的工具调用 trace 输出格式。

### Modified Capabilities
<!-- openspec/specs/ 中没有现存 capability 描述包检索；本变更不修改已有 capability。 -->

## Impact

- **代码删除**：
  - `app/services/raven_package_service.py` 中约 100 行"伪 RAG"代码（`rebuild_search_index` / `search_status` / `similarity_search` / `intelligent_search` / `suggestions` / `score_package` / `package_to_text` / `vector_store_path` 相关）；
  - `app/api/packages.py` 中 `/search/*` 五条路由 + 上传流程中的索引重建调用；
  - `frontend/src/api/raven.ts` 中 4 个旧导出与对应类型；`frontend/src/views/RavenManager.vue` 中旧搜索对话框 + 调用逻辑（替换为新的 Agent 对话框）。
- **新增代码**：`app/agents/package_search/{__init__.py,agent.py,prompts.py,mcp_tools.py}`、`app/api/packages.py` 中新增 `/packages/agent-search` 路由（或新建 `app/api/package_search.py`）、`frontend/src/api/raven.ts` 中新增 `searchPackagesByAgent` / `streamPackagesAgentSearch`、`frontend/src/views/RavenManager.vue` 中新的 Agent 搜索对话框。测试覆盖 `tests/agents/test_package_search_agent.py`、`tests/api/test_package_search_api.py`。
- **配置**：`app/config.py` 删除 `raven_vector_store_path`、`rag_embedding_provider`、`rag_embedding_model` 三个字段；新增 `package_search_max_turns`（默认 8）、`package_search_default_limit`（默认 5）、`package_search_max_limit`（默认 50）；`.env.example`（若有）同步移除并新增对应键。复用现有 `anthropic_*` 配置，不引入新的 LLM provider 字段。
- **API/契约**：
  - 移除：`GET /raven/search/status`、`POST /raven/search/rebuild-index`、`POST /raven/search/similarity`、`POST /raven/search/intelligent`、`POST /raven/search/suggestions`（前端同步移除调用）。
  - 新增：`POST /raven/packages/agent-search`，请求 / 响应格式见 design.md 与 specs/package-search-agent/spec.md。
- **依赖**：不新增依赖；后续清理阶段可考虑评估是否还有除日志分析与本变更外仍使用 `langchain*` 的代码（本次不在范围内）。
- **数据迁移**：磁盘上 `data/raven/vector-store/` 目录及其下的 `documents.json` / `*.meta.json` 在部署后无人引用，运维文档（`docs/`）增加一行说明"可手动删除"。**不**写自动删除脚本，以免误删用户备份。
- **运维**：上传 / 删除包不再触发 `rebuild_search_index`，包元数据落盘后即对 Agent 可见，省去重建索引的等待。Celery / Worker 不受影响（Agent 调用在线进行）。
- **未迁移项**：`app/agents/chat_agent.py`（设备 MCP 对话）与 `app/services/ai_chat_service.py` 仍走 OpenAI 兼容路径，本变更不动。
