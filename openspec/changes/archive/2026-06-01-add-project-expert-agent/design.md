## Context

Log Analysis Agent（`app/agents/log_analysis/`）已落地一条成熟链路：Claude Agent SDK 的 `query()` loop + 隔离临时工作区 + `lookup_project_repo` in-process MCP 工具解析仓库 + `git clone` 到 `repo/` + `setting_sources=["project"]` 加载用户 Skill + `trace.py` 把 SDK 消息流转换成 `AgentTraceEvent` SSE。主聊天侧由 `LogAnalysisChatService`（`app/services/log_analysis_chat_service.py`）维护**会话级持久工作区**：用户上传一次日志包后，后续追问复用同一份已解压日志与已克隆仓库。

它的强约束是"必须有日志归档"：`workspace.prepare(log_record)` 要求 `archive_path` 存在、要解压到 `logs/`、默认要求归档内含 `metadata.json` 来确定项目身份（`project_repo_id` 显式给出时可跳过该校验）。前端 `AIChat.vue` 的"日志分析"入口也以文件选择/拖拽为触发点。

"项目专家"要复用同一条 SDK 链路，但服务对象是**没有日志、只想就项目源码答疑**的用户。它和 Log Analysis 的唯一本质差异是：**去掉附件日志分析这一环**（无上传、无 `logs/`、无 `metadata.json`），项目身份改由用户显式选择。其余（克隆、Skill、trace、会话工作区、SSE、取消、轮询兜底）尽量复用。

约束：
- 不改动 Log Analysis Agent / DeviceAgent / GeneralAgent / PackageSearch 的现有行为。
- 不新增 env 配置、不新增第三方依赖（`claude-agent-sdk` 已存在）。
- 不改数据库 schema；复用 `chat_message` / `chat_session`。
- 单进程 uvicorn 部署假设与 Log Analysis 一致（in-process Job 注册表）。

## Goals / Non-Goals

**Goals:**
- 新增 `ProjectExpertAgent`，与 Log Analysis Agent 同构，复用其 `trace.py` 与 `lookup_project_repo` MCP 工具。
- 工作区只含 `repo/` + `task.json`，不解压归档、不要求 `metadata.json`。
- `project_repo_id` 必填，作为权威项目身份来源写入 `task.json.repo_info`。
- 会话级持久工作区支持多轮追问（首轮克隆、后续复用 `repo/.git`）。
- 复用 Log Analysis 的 SSE 事件协议（`run_start` / `step_*` / `thinking_*` / `answer_delta` / `run_complete`）、断线重连、`/result` 轮询兜底、取消。
- 在 `SUPPORTED_AGENTS` 注册 `project_expert`，支持 Skill 装载与 admin 管理。
- 前端新增"项目专家" Agent 选项，强制项目选择、禁用文件上传。

**Non-Goals:**
- 不为 Project Expert 引入 Human-in-the-loop（`can_use_tool`）审核——其工具集是只读分析类（Bash/Read/Grep/Glob），与 Log Analysis 同等风险面，沿用 Log Analysis 的 `permission_mode`。
- 不重构 Log Analysis 既有模块（只读复用 `trace.py` / `mcp_tools.py`）。
- 不引入"主力/轻量模型"运行期覆盖（已由 device-agent 变更统一到 `ANTHROPIC_*`）。
- 不实现 Redis 化多 worker 的 Job 注册表（与 Log Analysis 现状一致，留作后续）。

## Decisions

### 决策 1：新建独立 agent 包 `app/agents/project_expert/`，但复用 log_analysis 的 trace 与 mcp_tools

`ProjectExpertAgent` 的 loop 控制、token 掩码、取消/超时、结果抽取逻辑与 `LogAnalysisAgent` 几乎一致。两种实现路径：

- **(选定) 新建 `app/agents/project_expert/` 包**，其中 `agent.py` 自带精简后的 loop（删去日志相关逻辑），`prompts.py`/`workspace.py` 独立，而 `trace`、`mcp_tools` 直接 `from app.agents.log_analysis.trace import ...` / `from app.agents.log_analysis.mcp_tools import get_mcp_server`。
- (否决) 给 `LogAnalysisAgent` 加 `mode="project_expert"` 开关。否决理由：会让 Log Analysis 的工作区/提示词/校验分支布满 if，违背"不改动既有行为"约束，且两者入口语义（有无日志）差异大，强行合并降低可读性。

`AGENT_KEY = "project_expert"`。`ALLOWED_TOOLS = ["Bash", "Read", "Grep", "Glob", "Skill", PROJECT_REPO_MCP_TOOL]`（与 Log Analysis 相同，去掉的是提示词里的日志步骤，而非工具）。

> 复用 `trace.py` 是安全的：它不含任何"日志"语义，纯粹是 SDK 消息 → `AgentTraceEvent` 的转换层。若未来需要分叉，再抽到 `app/agents/_shared/trace.py`（本次不做）。

### 决策 2：工作区精简为 `repo/` + `task.json`，不创建 `logs/`，不解压，不校验 metadata.json

新建 `app/agents/project_expert/workspace.py`，提供 `prepare(*, project_repo, question, hints, session_id?) -> WorkspaceContext` 与 `cleanup(ctx)`：

- 在 `<code_repo_clone_base_dir>/<task_id>/` 下只创建 `repo/` 占位目录；
- 写 `task.json`，含非敏感字段 + 权威 `repo_info`：
  ```json
  {
    "question": "...",
    "hints": "...",
    "repo_info": {
      "project_code": "foo",
      "project_name": "Foo 服务",
      "repo_url": "https://git.example.com/foo.git",
      "default_branch": "main",
      "source": "user_selected_project_repo"
    }
  }
  ```
- `task.json` **不写** git token；token 仍只在 `lookup_project_repo` 工具响应内注入 `clone_url`（复用 log_analysis.mcp_tools 的现有行为）。即便 `repo_info` 已含 `repo_url`，提示词仍引导 Agent 调 `lookup_project_repo(project_code)` 拿带 token 的 `clone_url` 来克隆私有仓库——与 Log Analysis 路径一致，避免在 `task.json` 落 token。
- `WorkspaceContext` 复用 log_analysis 的 dataclass（`logs_dir` 字段对 Project Expert 置空字符串即可），或在 project_expert 包内定义一个不含 `logs_dir` 的轻量版本。**选定**：在 project_expert 包内定义独立的 `WorkspaceContext`（`task_id` / `temp_dir` / `repo_dir` / `task_json_path` / `metadata`），避免携带无意义的 `logs_dir`。

### 决策 3：`project_repo_id` 必填，服务层预解析项目身份

Log Analysis 在没有 `project_repo_id` 时回退到归档内 `metadata.json`。Project Expert 没有归档可回退，因此：

- `/project-expert/stream` 的 `project_repo_id` 为**新会话必填**；缺失时返回 4xx（`project_repo_required`）。
- 服务层 `ProjectExpertChatService` 在准备工作区前调用 `project_repo_service.get_by_id`（或 `get_enabled_by_id`）取仓库记录，把 `project_code` / `repo_url` / `default_branch` 写入 `task.json.repo_info(source="user_selected_project_repo")`。
- 后续轮（同 `session_id`）复用首轮工作区与 `project_repo_id`；若追问时传入与首轮不同的 `project_repo_id`，**选定策略**：以首轮绑定的项目为准并在响应里给出 `system_notice`（切项目需新开会话），避免在同一份 `repo/` 上混入另一个仓库。

### 决策 4：服务层以 `LogAnalysisChatService` 为蓝本，剥离上传分支

新建 `app/services/project_expert_chat_service.py`，单例 `project_expert_chat_service`：

- 复用 `AgentJob` 数据结构、in-process `_jobs` 注册表、`_JOB_RETENTION_SECONDS`、SSE 事件缓冲与 late-subscriber replay、`cancel`、`get_status`、`run_id` 投射到统一 run 生命周期等机制。
- `stream(*, message, session_id, history_json, remember, project_repo_id, db, user, owner_scope)` —— **签名去掉 `file`**。
- 会话注册表目录改为 `<base>/chat_project_expert_sessions`，与 Log Analysis 的 `chat_log_analysis_sessions` 隔离。
- 持久工作区策略复用 Log Analysis：会话首轮 `prepare` 出工作区并把 `temp_dir` 记入会话注册表；后续轮复用同一 `temp_dir`，Agent 见到 `repo/.git` 即复用克隆。
- 后台 Agent 任务调用 `ProjectExpertAgent().run_stream(ctx)`，把 `AgentTraceEvent` 转 SSE。
- 是否抽取公共基类：**否**（本次以复制 + 精简为主，避免大改 Log Analysis；若第三个同构 service 出现再抽 `_AgentChatServiceBase`）。

### 决策 5：API 端点与 Log Analysis 三件套对齐

在 `app/api/ai_chat.py` 新增：
- `POST /project-expert/stream`（`multipart/form-data` 或 JSON 均可；为与 Log Analysis 表单风格一致采用 `Form` 字段，但**无 `File`**）：`message` / `session_id` / `history` / `remember` / `project_repo_id`(必填)。
- `POST /project-expert/cancel`：body `{session_id}`。
- `GET /project-expert/result?session_id=...`：轮询兜底。

owner_scope / cookie 透传 / SSE header 与 Log Analysis 端点一致。

### 决策 6：提示词围绕"项目源码答疑"重写，不复用日志章节

在 `prompts_config.yaml` 新增 `claude_agent_project_expert.generic`：
- 工作目录说明只描述 `repo/`（首轮空、后续可能已含 `.git`）与 `task.json`；
- 删去"读取 logs/、定位 metadata.json、日志分类 root_cause/qa/..."等章节；
- 强制工作流：① 读 `task.json` 拿 `repo_info`；② 调 `lookup_project_repo(project_code)` 拿 `clone_url`/分支；③ 若 `repo/.git` 不存在则 `git clone` 到 `repo/`，存在则复用；④ 以用户 `question` 为中心用 Read/Grep/Glob/Bash 在 `repo/` 内分析；⑤ 给出有出处（文件:行号）的回答。
- `prompts.py` 提供 `get_prompts()` 与 `render_user_prompt(...)`，结构对齐 log_analysis.prompts 但读取 `claude_agent_project_expert` 键。

### 决策 7：Skill 装载复用现有机制

`skills_service.SUPPORTED_AGENTS` 新增：
```python
"project_expert": {
    "key": "project_expert",
    "name": "ProjectExpertAgent",
    "framework": "Claude Agent SDK",
    "description": "基于 Claude Agent SDK 的项目源码答疑智能体（POST /project-expert/stream）",
}
```
Agent 在 `prepare` 后、`query()` 前调用 `materialize_enabled_skills("project_expert", workspace_dir)`，并设 `setting_sources=["project"]`。admin `AdminAgentSkills.vue` 下拉据 `SUPPORTED_AGENTS` 自动出现新项，CRUD/启停复用 `/admin/agent-skills/*`，无需改动 admin 代码。

### 决策 8：前端新增 Agent 选项，强制项目、禁用上传

`AIChat.vue`：
- `AgentOption.agentType` 联合类型扩展为 `'package-manager' | 'log-analysis' | 'project-expert'`。
- 新增 `projectExpertAgentOption`（名称"项目专家"）。
- 选中"项目专家"时：复用现有 `ensureProjectRepoOptions()` 项目下拉，但把 `selectedProjectRepoId` 设为**发送前必填**（未选则禁用发送并提示）；同时禁用/隐藏日志文件选择与拖拽（与 package agent 互斥逻辑一致）。
- 发送走新增的 `chat` API 方法（`projectExpertStream`），复用 `conversationRuns` store 的 SSE 解析与 `AgentTraceStream` 渲染。

## Risks / Trade-offs

- **[复制而非抽象 service / agent loop 造成重复代码]** → 本次接受重复以隔离风险（不动 Log Analysis）。在 design 决策 1/4 中明确"出现第三个同构实现时再抽公共基类/共享 trace"，把抽象推迟到有 3 个样本时。
- **[复用 `log_analysis.trace` 形成跨包耦合]** → `trace.py` 无日志语义，耦合可接受；若 Log Analysis 后续要改 trace，需同时回归 Project Expert（在 tasks 中加一条交叉回归测试）。
- **[会话中途换项目导致 `repo/` 混仓]** → 决策 3 选定"以首轮项目为准 + system_notice 提示新开会话"，避免在同一工作区克隆第二个仓库。
- **[私有仓库 token 注入]** → 复用 log_analysis.mcp_tools，token 只在工具响应的 `clone_url` 内、不落 `task.json`、trace 中按现有 `mask_tokens` 掩码。需在测试中断言 `task.json` 与 trace 不含明文 token。
- **[大仓库克隆耗时 / 体积]** → 复用 Log Analysis 现有的工作区清理与超时机制；提示词建议 `git clone --depth 1`（浅克隆）以控时控量；会话工作区随会话清理策略回收。
- **[多 worker 部署下 in-process Job 注册表失效]** → 与 Log Analysis 同等限制，文档注明单进程假设；不在本次范围内解决。

## Migration Plan

1. 后端：新增 `app/agents/project_expert/` 包与 `project_expert_chat_service.py`，在 `prompts_config.yaml` 加 `claude_agent_project_expert` 块，在 `skills_service.SUPPORTED_AGENTS` 注册，在 `ai_chat.py` 加三个端点。纯新增，无破坏性变更。
2. 前端：`AIChat.vue` 加 Agent 选项 + 项目必选 + 禁用上传，`api/chat`（或 `api/index`）加 `projectExpertStream/cancel/result`。
3. 测试：`tests/agents/test_project_expert.py`（工作区不含 logs/、不要求 metadata.json、`project_repo_id` 必填、克隆流程、token 不落盘）、service 层会话复用与取消、API 端点契约。
4. 回滚：删除新增端点与前端选项即可，无数据迁移、无 schema 变更，对既有功能零影响。

## Open Questions

- 端点风格用 `Form`（与 Log Analysis 对齐、但无 File）还是 JSON（更贴合 Project Expert 无文件的特性）？倾向 JSON 更干净，但为前端复用 Log Analysis 的发送封装暂定 `Form`；实现时按前端复用成本二选一。
- 会话工作区的回收时机：复用 Log Analysis 的会话注册表 + 清理策略即可，是否需要为 Project Expert 设更短 TTL（代码仓库通常比解压日志更大）？默认沿用，留作运维可调。
