## Context

`RavenPackageService.intelligent_search` 现在被称作 "RAG"，但代码里没有任何向量化、embedding、ANN 检索：`rebuild_search_index` 只是把每个包的 `name / version / type / description / components / tags` 拼成一个字符串，落盘到 `data/raven/vector-store/documents.json`；`similarity_search` 又把 query 按 `[\s,;，。/\\_-]+` 切词，与拼接文本做子串包含计数，按命中率排序；`intelligent_search` 再用一个固定模板拼回中文答复（"已找到 X 个相关重构包…"）。这套实现既挂着 RAG 的招牌又无 RAG 的能力，模型完全没有参与"理解 + 决策"过程。

与此同时，`openspec/specs/anthropic-llm-config` 与 `openspec/specs/log-analysis-agent` 已经定义了 Claude Agent SDK + in-process MCP 工具的标准做法（`app/agents/anthropic_client.py`、`app/agents/log_analysis/mcp_tools.py`、`workspace.py`、`agent.py`），新 Agent 应该直接复用同一套基础设施。

包元数据存储仍维持现状：`data/raven/package-metadata.json` 是一个 JSON 数组，由 `RavenPackageService.load_packages()` / `save_packages()` 维护，全量加载到内存即可（数据量级在百~千条，全量 filter 没有性能问题）。本次**不**引入 SQL/SQLite 切换，避免无关迁移。

主要利益相关者：使用 Raven 管理后台搜索重构包的运维 / 测试工程师；前端 `RavenManager.vue` 智能搜索对话框；日后可能希望基于"自然语言 + 真实包数据"做自动化推荐的上层 Agent。

## Goals / Non-Goals

**Goals:**
- 让模型通过工具直接读到包数据库里的真实字段，而不是读"打分后的拼接文本"。
- Agent 输出必须可被前端机器解析：除自然语言答复外，附 `recommended_package_ids` 与 `relevant_package_ids`。
- 工具集"小而正交"：每个工具做一件清楚的事，参数严格 JSON schema，不让模型自由拼 SQL。
- 与 `AgentTraceEvent`（[`docs/agent_trace_protocol.md`](docs/agent_trace_protocol.md)）兼容，使 SSE 流式可在前端复用既有 trace UI。
- 一次性删干净旧 RAG 代码、旧路由、旧前端调用、旧配置项，不留 feature flag。

**Non-Goals:**
- 不引入真正的向量检索 / embedding 模型 / 向量库。
- 不改造包元数据底层存储（仍是 JSON 文件）。
- 不迁移 `chat_agent.py` / `ai_chat_service.py`（仍走 OpenAI 兼容路径），它们独立演进。
- 不实现"包推荐定时刷新""下载量加权排序"等推荐系统能力；只做"按用户当前问题检索 + 排序 + 解释"。
- 不做向量索引到新方案的数据迁移（旧 `documents.json` 直接丢弃）。

## Decisions

### 1. 完全删除 RAG 代码而非保留兼容路径
**Decision**：`raven_package_service` 中所有 `*_search_index` / `*_search` / `score_package` / `package_to_text` / `vector_*` 字段与方法一次性删掉；`/raven/search/*` 五条路由同步删除。

**Why over alternatives**：
- 保留旧路由 + 加 feature flag：会让前端继续维护两套 UI，且实际没人会切回去；
- 把 `intelligent_search` 改成"内部直接调用 Agent"：API 形态/输出契约差异太大（旧接口返回 `relevantPackages` 数组，新接口需要返回 trace + 推荐 ID），强行套同一路由反而劣化前端体验；
- 数据库里 `vector-store/` 目录只是磁盘文件，删除无需迁移脚本，运维文档说明即可。

### 2. 工具集设计：6 个正交工具，不暴露原始 list
**Decision**：MCP server 注册 6 个工具（见下表）。所有工具直接调用 `RavenPackageService` 内已有的"纯数据访问"方法（`get_all_packages` / `get_package` 等），新增的辅助方法（如 `compare_versions`）放在同一个 service 类下，保持单一访问入口。

| 工具 | 输入 | 输出 | 用途 |
|------|------|------|------|
| `list_packages` | `{filters?: {type?, is_patch?, tags?[], component?}, sort?: {by: "createdAt"\|"version"\|"name", order: "asc"\|"desc"}, limit?: int (≤max_limit), offset?: int}` | `{total, items: [PackageBrief]}` | Agent 想"按字段过滤翻页看一遍" |
| `get_package_by_id` | `{id: string}` | `PackageFull \| {error:"not_found"}` | 想看完整 metadata、sha256、components |
| `search_packages_by_text` | `{text: string, fields?: ("name"\|"version"\|"description"\|"tags"\|"components")[], limit?: int}` | `{items: [PackageBrief & {matched_fields: string[]}]}` | 纯字面量子串匹配（**不是** embedding），用于"看名字带 katx 的"这种需求 |
| `filter_packages_by_version` | `{package_type?: string, version_min?: string, version_max?: string, include_prerelease?: bool}` | `{items: [PackageBrief]}` | 处理"v2.3 以上"这类语义版本比较 |
| `list_components` | `{package_type?: string}` | `{components: [{name, count, package_types: [string]}]}` | 让 Agent 在不知道 component 拼写时先列出可选值 |
| `find_packages_by_component` | `{component_name: string, version?: string}` | `{items: [PackageBrief]}` | 用户问"哪些包含 cucp" |
| `package_stats` | `{group_by: "type"\|"version_major"\|"tag"\|"isPatch"}` | `{groups: [{key, count}]}` | 应对"补丁包占比""哪个型号包最多" |

**Why over alternatives**：
- 单一 `query_packages(...)` 大工具：参数空间太大，模型经常用错 / 漏参；用多个窄工具引导模型分步思考，工具调用也好做 trace 展示。
- 暴露 SQL/JSONPath：给模型自由组合查询能力太大，容易构造恶意 / 错误 query；明确的工具就是 API surface。
- 让 Agent 直接读 `package-metadata.json` 文件：会绕过未来可能的字段权限 / 软删除 / 排序逻辑，所有访问必须走 service 层。

`PackageBrief` 字段：`{id, name, version, packageType, isPatch, createdAt, components: [name], tags: [string], size}`（不含 sha256、不含 path）。`PackageFull` 在此基础上加 `path`（脱敏到文件名）、`metadata.sha256`、`metadata.description`、`metadata.customFields`。Agent 没必要每次都拉完整记录，brief 默认即可，工具 schema 在 description 中说明。

### 3. 语义版本比较交给后端，不让模型算
**Decision**：新增 `RavenPackageService.compare_versions(a, b) -> int`（基于 `packaging.version.parse`，fallback 到字符串字典序），由 `filter_packages_by_version` 在 service 内完成 min/max 过滤。`include_prerelease=False` 时跳过 `parse(...).is_prerelease`。

**Why over alternatives**：
- 让模型用工具组合自行比较：模型对 SemVer 一直不可靠，特别是 `1.10.0 vs 1.9.0`、`1.0-rc1` 这种 case；
- 用 LLM tool-use 让它写脚本：脱离 SDK 当前权限模型，且生产环境不允许任意代码执行。

### 4. 工具结果 token 预算
**Decision**：
- `list_packages` / 各 search 工具默认 `limit=5`，硬上限 `package_search_max_limit=50`；
- 单条 `PackageBrief` 控制在 ~200 字符以内；
- `total` 字段使工具返回值同时携带"还有多少没看到"，模型决定要不要换关键词。

**Why**：包数据量级在百~千条，但若模型盲目 `limit=1000` 拉一遍会塞爆上下文。硬上限放在 service 内强制截断，模型即使写超大 limit 也会被夹断。

### 5. 系统提示词与回答格式契约
**Decision**：system prompt 强制 Agent 在**最终**消息里输出一个 fenced JSON 块：
```json
{
  "recommended_package_ids": ["..."],
  "relevant_package_ids": ["..."],
  "notes": "可选：为何选这些包的一句话"
}
```
API 层解析最后一条 assistant message：先找 ```json fenced block；解析失败则降级返回 `recommended_package_ids=[]` 并把原文照原样发回前端，由前端展示"AI 已答复但未给出结构化推荐"。

**Why over alternatives**：
- 用 SDK 的 structured output：Claude Agent SDK 当前对 structured output 的支持还不稳定，且与工具循环混用时模型经常把工具调用和结构化输出搞混；fenced JSON 是社区最稳的退路。
- 给模型一个专门的 `submit_answer(...)` 工具：多一次工具往返，trace 噪声大，且 ROI 不高。

### 6. API 形态：单条新路由 + SSE
**Decision**：`POST /raven/packages/agent-search`：
- `stream=false`（默认）：阻塞返回 `{ answer, recommended_package_ids, relevant_package_ids, tool_trace: [{tool, input, output_summary}], model, usage }`，`tool_trace` 列出工具调用次序与简短摘要（每条工具结果摘要 ≤ 200 字符），用于前端展示推理过程；
- `stream=true`：返回 SSE，事件类型对齐 `AgentTraceEvent` 协议（`assistant_delta` / `tool_use` / `tool_result` / `final`），前端复用 [`frontend/src/views/LogDetail.vue`](frontend/src/views/LogDetail.vue) 中现成的渲染组件。

**Why**：
- 旧 `/search/intelligent` 是 POST 单条 JSON；新接口若也走完全同步，会让用户在多轮工具调用期间无反馈（实测 5~10s）。
- 复用既有 trace 通道避免前端两套渲染逻辑。

### 7. 不重建 / 维护索引
**Decision**：上传 / 修改 / 删除包不再调用任何索引重建。包数据落 `package-metadata.json` 即对 Agent 可见（service 每次工具调用即时读）。`load_packages` 已经在 service 单例里，没有 IO 瓶颈。

**Why**：去掉一个高频的、平时无用的副作用调用，使包 CRUD 接口响应更快、错误面更小。

## Risks / Trade-offs

- **[模型给出无效 ID]** Agent 可能在 `recommended_package_ids` 里填它幻觉出来的 ID → API 层在返回前用 `RavenPackageService.get_package(id)` 校验，过滤掉不存在的 ID 并在 `tool_trace` 末尾追加 `{type: "warning", message: "filtered N invalid ids"}`。
- **[多轮工具调用导致延迟]** 默认 `max_turns=8`，常见查询 2~4 turn 即可结束；通过流式 SSE + 前端 trace 渲染缓解感知延迟。
- **[包数量增长]** 当前百~千条全量内存过滤无压力；若未来过万条，需重新评估是否引入 SQLite 索引——但这是与本变更解耦的演进路径。
- **[运维误清理]** `data/raven/vector-store/` 不再使用但**不**自动删除，避免误删用户备份；运维文档说明可手动清理。
- **[前端兼容]** 旧"智能搜索"对话框被替换为新的 Agent 对话框，UI 元素改动较大；通过保留入口位置（"智能搜索"按钮）与相同的"输入框 + 推荐结果列表"主结构，将学习成本控制在最小。
- **[字面量搜索的局限]** 用户问"我要 KA 频段的发射机"时，模型必须自己映射到 `ka-tx` 这种 `packageType`。在 system prompt 中显式给出 `PACKAGE_TYPES` 枚举与组件命名约定，并允许 Agent 用 `list_components` / `package_stats(group_by="type")` 先列出可选项。

## Migration Plan

1. **后端**：先合入新代码（Agent + 工具 + 新路由），与旧 `/search/*` 并存一个 commit；
2. **前端**：紧随其后一个 commit，把 `RavenManager.vue` 切到 `/packages/agent-search`，移除旧 API 调用与 `raven.ts` 导出；
3. **删除**：最后一个 commit 删除 `raven_package_service` 里的旧方法、`packages.py` 里的旧路由、`config.py` 里的旧字段；
4. **运维**：发布说明里写一段"`data/raven/vector-store/` 已不再使用，可在确认后手动删除"。

回滚策略：三个 commit 顺序原子，回滚时 revert 删除 commit 即可恢复双路并存；若新 Agent 在生产出大问题，先 revert 前端 commit 让用户继续走旧搜索（功能弱但可用），再排查后端。

## Open Questions

- 是否需要给 `/raven/packages/agent-search` 加 admin/普通用户的鉴权差异？倾向于复用 `/raven/packages` 现有鉴权；待 admin 审计后确认。
- `tool_trace` 是否需要持久化（用于复盘 / 审计）？本变更内只放在响应体；持久化在后续变更评估。
- 用户 query 长度上限：暂定 1000 字符，超出 400 截断到 1000 加警告。如果业务有更长的查询场景，再调。
