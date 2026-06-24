# 设计：重构包检索 Agent 项目化重建

## Context

平台现有三个专门 Agent 的架构成熟度不一致：

| 维度 | 日志分析 | 项目专家 | 重构包检索（现状） |
|---|---|---|---|
| 项目身份来源 | metadata.json 或用户选择的 `project_repo` | 用户必选的 `project_repo` | 无（与项目无关） |
| 仓库访问 | 有（工作区 + `lookup_project_repo` MCP + Bash/Read/Grep/Glob） | 有（同左） | 无（仅 7 个元数据 MCP 工具） |
| 系统提示词 | `prompts_config.yaml` → 后台可编辑 | 同左 | Python 常量硬编码 |
| 会话端点 | `/log-analysis/{stream,cancel,result}` | `/project-expert/{stream,cancel,result}` | `POST /packages/agent-search`（一次性 SSE，无 cancel/result） |
| 会话级工作区复用 | 有 | 有（`session_has_workspace`） | 无 |

包元数据由 `RavenPackageService` 维护在 JSON 文件中（无数据库表），`packageType` 取值是写死的 6 个枚举（`PACKAGE_TYPES`），上传时还会按文件名启发式推断类型。项目仓库注册表（`project_repo` 表，含 `project_code` 唯一键）已是日志分析与项目专家的权威项目身份来源。

约束：
- 包元数据存储契约（JSON 文件 + uploads 目录）需保留，便于旧卷复用（见 `raven_package_service.py` 模块注释）；
- `system-user-metrics` 规范要求 Prometheus 标签低基数，且 **MUST NOT** 把项目标识作为 label；
- Agent trace 协议（`docs/agent_trace_protocol.md`）与前端统一渲染管线需保持兼容；
- 重构包 Agent 的最终回复契约（fenced JSON 内 `recommended_package_ids` / `relevant_package_ids`）被前端推荐包卡片依赖，必须保留。

## Goals / Non-Goals

**Goals:**

1. 包元数据与项目关联（`projectCode` ← `project_repo.project_code`），淘汰硬编码包类型；
2. 重构包 Agent 获得与项目专家同构的项目绑定、工作区与仓库访问能力；
3. Agent 分析策略差异化：Git 提交记录优先，仅在必要时读代码；
4. 系统提示词进入 `prompts_config.yaml` 并可在后台编辑；
5. 对外 API、前端（对话、包管理、上传）、指标全链路适配。

**Non-Goals:**

- 不为重构包 Agent 接入 Skill 加载（后续提案）；
- 不引入项目成员级包可见性鉴权；
- 不改变包文件的物理存储（uploads 目录、.tgz/.tar.gz）；
- 不把包元数据迁移进数据库。

## Decisions

### D1：包-项目关联用 `projectCode` 字符串而非 `project_repo_id` 外键

包元数据存在 JSON 文件中，没有外键约束可言；`project_repo.project_code` 是稳定的业务唯一键（注册表有唯一约束、小写规范化），而自增 `id` 在跨环境迁移卷时不稳定。因此包元数据新增 `projectCode` 字段存项目代号；运行时通过 `project_repo_service` 反查项目展示名。

替代方案：存 `project_repo_id`（整数）—— 被否决，跨环境复用包卷时 id 会漂移；存 `{id, code}` 双字段 —— 冗余且有不一致风险。

### D2：存量数据迁移 = 字段平移 + "未关联"兜底，不做映射表

`load_packages()` 读到旧记录时惰性规范化：`projectCode = 旧 packageType 值`，并保留原始 `packageType` 键不再写入新值（读取兼容、写入废弃）。旧枚举值（如 `lingxi-10`）若恰好是已注册项目的 `project_code` 则自然关联成功；否则该包在 UI 中显示为"未关联项目"，可被筛选出来由管理员重新指认（编辑包元数据已有 update 通道）。

理由：6 个旧枚举是否对应真实项目只有部署方知道，硬编码映射表必然出错；惰性迁移避免一次性脚本对只读卷的写入风险（首次写操作时才落盘）。

替代方案：启动时一次性重写元数据文件 —— 被否决，只读/共享卷场景有副作用；要求管理员先建好同名项目再升级 —— 作为部署建议写入迁移说明，但不作为硬前置。

### D3：上传时 `projectCode` 必填且必须命中已启用项目；文件名启发式推断废弃

`POST /upload`、`POST /upload/batch` 的 `packageType` 表单字段替换为 `projectCode`，服务端校验其对应 `project_repo` 存在且 `enabled`，否则 400。`determine_package_type()` 文件名启发式删除——项目无法从文件名可靠推断，静默猜错比报错更糟。`scan_uploads_directory()` 扫描出的孤儿文件 `projectCode` 置空（"未关联"），等待管理员指认。

### D4：Agent 重建对齐项目专家：独立 workspace + 复用 log_analysis trace 状态机

新增 `app/agents/package_search/workspace.py`（同构于 `project_expert/workspace.py`：`repo/` 占位 + `task.json`，`repo_info` 写入用户所选项目，不落 git token）。`agent.py` 改为复用 `log_analysis` 的 trace 层与 `_RunState` 状态机（与项目专家同一套），淘汰 package_search 自有的 `trace.py` 拷贝。但**最终结果解析保留包检索自己的契约**（fenced JSON → `recommended_package_ids` / `relevant_package_ids` + ID 校验过滤），不套用日志分析的 `answer/summary` schema。

ALLOWED_TOOLS = `Bash`、`Read`、`Grep`、`Glob` + `mcp__project_repo__lookup_project_repo` + 7 个包元数据 MCP 工具。

替代方案：保留现有自研 loop 仅加 cwd —— 被否决，会留下两套平行的 trace/状态机实现，且无法复用取消（cancel_event）机制。

### D5：包元数据 MCP 工具服务端强制限定到所选项目

7 个工具的实现在创建 MCP server 时闭包捕获本次会话的 `project_code`，所有查询先按 `projectCode == project_code` 过滤；`list_packages.filters.type`、`filter_packages_by_version.package_type`、`list_components.package_type` 参数移除，`package_stats.group_by` 的 `type` 维度更名为 `project`（在单项目范围内仍可按 `version_major`/`tag`/`isPatch` 聚合）。不依赖提示词约束模型——越权查询在工具层就查不到。

实现方式：`get_mcp_server()` 改为 `get_mcp_server(project_code: str)`，按会话构建（与项目专家把 server 实例化绑定到 run 的做法一致）。

### D6：Git 提交记录优先策略放在系统提示词 + 用户提示词双重声明

策略属于"行为引导"而非"权限边界"（读代码的能力必须保留，因为"非常必要时"允许），因此不在工具层做硬限制，而是：

1. 系统提示词中明确分析顺序契约：① 包元数据工具 → ② `git log` / `git show` / `git diff --stat` 等提交记录命令 → ③ 仅当提交记录不足以回答时才 `Read`/`Grep` 源码，且要求 Agent 在回答中说明为何升级到读代码；
2. 建议浅克隆策略写入提示词（如 `git clone --filter=blob:none`（partial clone）优先，足以看全提交历史而不拉全部文件内容），降低大仓库成本；
3. 该提示词在 `prompts_config.yaml` 中后台可调，部署方可按需收紧或放宽。

### D7：新增聊天三端点 + 专属 chat service；`/packages/agent-search` 保留并升级

新增 `app/services/package_search_chat_service.py`（镜像 `project_expert_chat_service`：新会话必填 `project_repo_id`、校验项目存在且启用、会话级工作区复用、后台线程 + cancel_event、SSE 透传 trace、登录态持久化、`get_status` 轮询兜底），并在 `ai_chat.py` 注册 `/package-search/stream`、`/package-search/cancel`、`/package-search/result`。

`AIChat.vue` 的重构包对话改走 runs store 统一管线（与项目专家相同的 start/cancel/恢复逻辑），淘汰页面内自维护的 `runPackageAgent` SSE 处理。

既有 `POST /packages/agent-search`（RavenManager 智能检索页使用）保留端点形态，但请求体新增必填 `project_repo_id`：缺失返回 400（`reason: "project_repo_required"`）。它继续走一次性无工作区路径吗？——否：为保证"同一 Agent 同一能力"，它内部同样走重建后的 Agent（含工作区），只是不做会话工作区复用（每次请求独立准备/清理）。

替代方案：agent-search 维持纯元数据模式（无仓库）—— 被否决，会出现"同名 Agent 两种行为"，且用户明确要求该 Agent 整体具备仓库能力。

### D8：提示词区块与后台注册

`prompts_config.yaml` 新增：

```yaml
claude_agent_package_search:
  generic:
    system_prompt:
      zh: |
        （从现 prompts.py 迁移，并补充：项目绑定上下文、仓库工作区说明、
        Git 提交记录优先契约、fenced JSON 输出契约）
    user_prompt_template:
      zh: |
        （question / hints / task_id / workspace_dir 占位符，对齐项目专家）
```

`prompts_config_service.py`：`PROMPT_FUNCTION_META` 增加 `claude_agent_package_search`（名称"重构包检索"），`PROMPT_AGENT_META` 增加 `(claude_agent_package_search, generic)`（"重构包配置管理员"），`_invalidate_prompt_caches()` 增加对 `package_search.prompts._PROMPTS_CACHE` 的清理。`package_search/prompts.py` 重写为 YAML 加载器（同构于 `project_expert/prompts.py`），AdminPrompts 页面无需改动即自动出现新区块。

### D9：前端项目选择复用既有 `selectedProjectRepoId` 单一状态

`AIChat.vue` 已有跨 Agent 的 `selectedProjectRepoId` + `projectRepoOptions` 机制（日志分析可选、项目专家必选）。重构包 Agent 仅需：

- `isProjectRepoSelectVisible` 计算属性纳入 `isPackageAgentSelected`；
- `isProjectRepoRequiredMissing` 纳入 `isPackageAgentSelected`（必选语义与项目专家完全一致：未选项目禁用发送 + 提示 `selectProjectFirst`）；
- `setTargetAgent` 对 `package-manager` 也调用 `ensureProjectRepoOptions()`；
- GeneralAgent 建议切换（`chooseSuggestedAgent('package_search')`）后由上述同一套状态自然生效。

RavenManager 智能检索页新增独立的项目下拉（必选，未选时禁用检索按钮），请求体带 `project_repo_id`。上传表单与列表筛选的包类型下拉替换为项目下拉，选项来自 `projectRepoApi.listEnabled()`，另含一个"未关联"筛选项（仅筛选用，不可作为上传目标）。

### D10：指标维度调整且不违反低基数约束

- 持久化业务事件 `package_activity` 的 metadata：`package_type` → `project_code`（DB 事件允许携带项目标识，规范只限制 Prometheus label）；
- Prometheus `raven_package_activity_total`：现有 `package_type` label 若直接替换为 `project_code` 会违反"label 不得含项目标识"，因此 **删除该维度**，label 只保留 `action` + `status`；
- 管理端总览 `packagesByType` → `packagesByProject`（含 `unassociated` 桶），`AdminMetrics.vue` 同步改文案与字段。

## Risks / Trade-offs

- **[BREAKING API 影响外部消费方]** 包管理 API 的字段/路径更名会破坏既有脚本 → 迁移说明中列出全部变更点；`GET /packages` 对旧 `type` 查询参数短期接受并按 `projectCode` 解释（标记 deprecated，仅查询参数层兼容，响应体不再含 `packageType` 新值）。
- **[存量包大面积"未关联"]** 部署方若未注册同名项目，旧包将全部进"未关联"桶且不出现在 Agent 检索范围内 → 部署清单第一步要求按旧枚举值预创建/确认 `project_repo` 记录；UI 提供"未关联"筛选便于批量指认。
- **[Agent 必选项目降低易用性]** 跨项目的全局包检索问题（"全库哪个包最新"）不再可答 → 与项目专家保持一致是用户明确要求；全局视角仍有 RavenManager 列表/统计页兜底。
- **[克隆大仓库拖慢检索响应]** 包检索过去是秒级元数据查询，引入仓库后首问可能分钟级 → 提示词引导"只有需要 Git 上下文才克隆"（元数据问题不碰仓库）+ partial clone 建议 + 会话级工作区复用避免重复克隆。
- **[惰性迁移的读写不对称]** 规范化只在读路径做、写路径落盘，存在新旧字段并存窗口 → 规范化函数幂等，所有读取入口统一走 `load_packages()` 单点。
- **[Prometheus 删除 label 影响现有面板]** `package_type` label 移除会让旧 Grafana 查询失效 → 在迁移说明中标注；时序数据本身不丢失。

## Migration Plan

1. **部署前**：管理员在后台"项目仓库管理"中确认/创建与旧包类型值同码的项目（如需保留旧分类口径）；
2. **部署**：后端 + 前端一并发布（BREAKING API 不做灰度双写）；`prompts_config.yaml` 随版本附带新区块默认值；
3. **部署后**：访问包管理页触发惰性迁移落盘；用"未关联"筛选核对存量包归属；
4. **回滚**：代码回滚即可——惰性迁移保留了原始 `packageType` 键不删除，旧版本服务仍可读取同一份元数据文件。

## Open Questions

- 旧 `GET /download/type/{package_type}` 路径是否需要 301/兼容路由（取决于是否有外部自动化依赖该路径）——默认直接移除，若部署方反馈有依赖再补兼容路由；
- "未关联"包是否允许通过 Agent 检索（当前设计：不允许，Agent 工具严格按所选项目过滤）——如有需求可后续在工具层加 `include_unassociated` 开关。
