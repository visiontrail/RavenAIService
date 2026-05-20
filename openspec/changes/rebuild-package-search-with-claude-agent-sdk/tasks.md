## 1. 基础设施 / 配置

- [x] 1.1 在 `app/config.py` 新增字段 `package_search_max_turns: int = 8`、`package_search_default_limit: int = 5`、`package_search_max_limit: int = 50`
- [x] 1.2 在 `app/config.py` 删除字段 `raven_vector_store_path`、`rag_embedding_provider`、`rag_embedding_model`
- [x] 1.3 同步删除 `.env.example`（若存在）中对应键，新增 `PACKAGE_SEARCH_*` 三个键的示例
- [x] 1.4 更新 `tests/test_config.py` 删掉对旧 RAG 字段的断言，新增对新字段默认值的断言

## 2. 包元数据服务的数据访问 API

- [x] 2.1 在 `RavenPackageService` 中新增 `compare_versions(a: str, b: str) -> int`（使用 `packaging.version.parse`，fallback 到字符串比较）
- [x] 2.2 在 `RavenPackageService` 中新增 `iter_brief(packages) -> list[dict]`，返回 `PackageBrief` 字段集合（id/name/version/packageType/isPatch/createdAt/components/tags/size）
- [x] 2.3 在 `RavenPackageService` 中新增 `query_packages(filters, sort, limit, offset, max_limit) -> tuple[list[dict], int]`，复用现有 `filter_packages` 内部逻辑但返回元组（items, total_before_paging）
- [x] 2.4 在 `RavenPackageService` 中新增 `text_search(text, fields, limit, max_limit)`、`version_filter(package_type, version_min, version_max, include_prerelease, limit, max_limit)`、`list_components(package_type)`、`find_by_component(component_name, version)`、`stats_by(group_by)`
- [x] 2.5 编写 `tests/services/test_raven_package_service_query.py` 覆盖：SemVer 边界（1.10 vs 1.9、prerelease 过滤）、limit 夹断、不存在的 ID、空 query

## 3. Claude Agent SDK MCP 工具实现

- [ ] 3.1 新建 `app/agents/package_search/__init__.py`、`prompts.py`、`mcp_tools.py`、`agent.py`、`trace.py`
- [ ] 3.2 在 `mcp_tools.py` 中按 design.md 表格用 `@tool` 注册 7 个工具：`list_packages`、`get_package_by_id`、`search_packages_by_text`、`filter_packages_by_version`、`list_components`、`find_packages_by_component`、`package_stats`
- [ ] 3.3 每个工具的实现 MUST 走 `RavenPackageService` 单例（不读文件、不调外部服务），返回 `{"content": [{"type": "text", "text": json.dumps(payload)}]}`
- [ ] 3.4 在 `prompts.py` 编写 system prompt：说明工具用途、`PACKAGE_TYPES` 枚举、`PackageBrief` 字段含义、最终回复必须包含 fenced JSON 块的约定
- [ ] 3.5 用 `create_sdk_mcp_server(name="package_search", ...)` 把工具汇成一个 in-process MCP server，与 `log_analysis/mcp_tools.py` 的模式一致
- [ ] 3.6 编写 `tests/agents/package_search/test_mcp_tools.py` 单测每个工具的输入校验、limit 夹断、SemVer 比较、not_found 分支

## 4. Agent 主流程

- [ ] 4.1 在 `agent.py` 实现 `PackageSearchAgent`：构造 `ClaudeAgentOptions`（model/max_turns/allowed_tools/mcp_servers），通过 `app.agents.anthropic_client` 复用已有配置
- [ ] 4.2 实现 `run(query, session_id?) -> dict` 返回 `{answer, recommended_package_ids, relevant_package_ids, tool_trace, model, usage}`：调用 SDK loop，收集 `tool_use` / `tool_result` 事件落入 `tool_trace`
- [ ] 4.3 实现 fenced JSON 解析：从最终 assistant message 中提取 ` ```json ... ``` ` 块；解析失败 / 缺字段 / 字段类型错误均降级为 `[]`，并在 `tool_trace` 末尾追加 warning
- [ ] 4.4 实现 ID 校验：对解析出的所有 ID 调用 `RavenPackageService.get_package`，过滤掉不存在的 ID，被过滤的数量写入 warning
- [ ] 4.5 实现 `stream(query, session_id?)` 异步生成器，按 `AgentTraceEvent` 协议 yield SSE 字典（type: assistant_delta / tool_use / tool_result / final）
- [ ] 4.6 编写 `tests/agents/package_search/test_agent.py`：用 fake SDK loop 桩件验证 fenced JSON 解析、ID 过滤、warning 追加、tool_trace 结构

## 5. HTTP API

- [ ] 5.1 在 `app/api/packages.py`（或新建 `app/api/package_search.py`）新增 `POST /raven/packages/agent-search` 路由
- [ ] 5.2 请求体校验：`query` 必填、非空白、长度 ≤ 1000；超长 / 空白返回 HTTP 400
- [ ] 5.3 `stream=false` 分支：调用 `PackageSearchAgent.run`，返回非流式 JSON
- [ ] 5.4 `stream=true` 分支：返回 `StreamingResponse(..., media_type="text/event-stream")`，事件格式对齐 `docs/agent_trace_protocol.md`
- [ ] 5.5 复用 `/raven/packages` 现有 router 的鉴权依赖（与 list_packages 一致）
- [ ] 5.6 编写 `tests/api/test_package_search_api.py`：non-stream 200 / SSE 流 / query 过长 400 / 空 query 400 / 模型给无效 ID 时被过滤

## 6. 删除旧 RAG 实现

- [ ] 6.1 删除 `app/services/raven_package_service.py` 中以下方法 / 字段：`rebuild_search_index`、`search_status`、`similarity_search`、`intelligent_search`、`suggestions`、`score_package`、`package_to_text`、`vector_store_path`、`vector_meta_file`、`__init__` 中对它们的赋值
- [ ] 6.2 删除 `app/api/packages.py` 中以下路由：`/search/status`、`/search/rebuild-index`、`/search/similarity`、`/search/intelligent`、`/search/suggestions`
- [ ] 6.3 删除 `app/api/packages.py` 上传 / 批量上传流程中所有 `rebuild_search_index()` 调用与响应里的 `vectorIndexRebuild` 字段
- [ ] 6.4 全局 `grep` 确认 `intelligent_search` / `similarity_search` / `rebuild_search_index` / `vector_store_path` 在仓库中（不含 openspec/changes/archive、不含本次 change 的 specs）零引用
- [ ] 6.5 在 docs/ 下新增 / 更新一段运维说明：`data/raven/vector-store/` 已废弃，可手动删除

## 7. 前端切换

- [ ] 7.1 在 `frontend/src/api/raven.ts` 删除 `rebuildRavenIndex`、`getRavenSearchStatus`、`intelligentSearchPackages`、`getRavenSearchSuggestions` 以及相关类型 `RavenSearchStatus` 中只服务于旧 RAG 的字段
- [ ] 7.2 在 `frontend/src/api/raven.ts` 新增 `searchPackagesByAgent(query, opts?)` 与 `streamPackagesAgentSearch(query, onEvent)`（基于 `EventSource` 或 `fetch` + SSE 解析）
- [ ] 7.3 在 `frontend/src/types/index.ts` 删除旧搜索相关类型，新增 `PackageAgentSearchResponse`、`PackageAgentTraceEvent`
- [ ] 7.4 重写 `frontend/src/views/RavenManager.vue` 的智能搜索对话框：复用 `LogDetail.vue` 的 trace 渲染组件展示工具调用过程，最终显示推荐包列表（点击跳详情）
- [ ] 7.5 前端 `grep` 确认 `intelligentSearchPackages` / `rebuildRavenIndex` / `/search/intelligent` 字符串零引用

## 8. 端到端验证

- [ ] 8.1 启动后端 + 前端，手动验证：name 子串、版本范围、组件、统计四类典型 query 均能返回结构化推荐
- [ ] 8.2 手动验证 SSE 流式：trace 事件在前端实时显示，最终 final 事件落地推荐结果
- [ ] 8.3 手动验证：模型若幻觉 ID，响应体中已被过滤、warning 出现在 tool_trace
- [ ] 8.4 运行 `pytest tests/services tests/agents/package_search tests/api/test_package_search_api.py tests/test_config.py` 全绿
- [ ] 8.5 运行 `npm run typecheck` 与 `npm run lint`（前端）通过
- [ ] 8.6 `openspec validate rebuild-package-search-with-claude-agent-sdk --strict` 通过
