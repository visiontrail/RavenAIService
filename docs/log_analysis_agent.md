# Log Analysis Agent 设计说明

本文档说明日志分析 Agent（`LogAnalysisAgent`）的工作流、源码定位、以及"代码强制使用"策略。面向后端工程师、Prompt 维护者与 QA。

- Python 入口：[app/agents/log_analysis/agent.py](../app/agents/log_analysis/agent.py)
- 工作区准备：[app/agents/log_analysis/workspace.py](../app/agents/log_analysis/workspace.py)
- MCP 工具：[app/agents/log_analysis/mcp_tools.py](../app/agents/log_analysis/mcp_tools.py)
- 系统提示词：[app/prompts/prompts_config.yaml](../app/prompts/prompts_config.yaml) 下的 `claude_agent_log_analysis.generic`
- 聊天编排：[app/services/log_analysis_chat_service.py](../app/services/log_analysis_chat_service.py)
- Celery 编排：[app/tasks/ai_analysis.py](../app/tasks/ai_analysis.py)

---

## 1. 工作区布局

每次任务在 `code_repo_clone_base_dir/<task_id>/` 下创建独立工作区：

```
<workspace>/
  task.json    # 任务元数据：log_id, question, log_type, hints, repo_info(可选)
  logs/        # 解压后的日志归档；metadata.json 可能在其子目录任意位置
  repo/        # 代码克隆目录（强制使用，详见第 3 节）
```

`task.json` 中的 `repo_info` 形态：

```json
{
  "project_code": "...",
  "project_name": "...",
  "repo_url": "https://...",          // 不带 token，用于展示
  "clone_url": "https://oauth2:***@...", // 注入 token，用于实际 clone
  "default_branch": "main",
  "auth_required": true,
  "matched_via": "user_selection",     // 或 metadata 中匹配到的 project_code 值
  "source": "user_selected_project_repo" // 仅当用户在前端显式选择项目时存在
}
```

---

## 2. Agent 工作流（Mandatory Workflow）

系统提示词把单次分析拆为 6 步，**Step 2–4 全部强制**：

| 步骤 | 标题 | 是否强制 |
|---|---|---|
| Step 0 | 问题分类（root_cause / qa / search / stats / meta / other） | 强制 |
| Step 1 | 定位 `metadata.json`（best-effort，找不到不报错） | 尽力 |
| Step 2 | 解析仓库信息（`task.json` / `metadata.json` / 注册表） | **强制** |
| Step 3 | 解析失败回退到 `mcp__project_repo__lookup_project_repo` | **强制** |
| Step 4 | `git clone` 到 `repo/`（若 `repo/.git` 已存在则复用） | **强制** |
| Step 5 | 同时基于日志和源码进行调查 | **强制** |
| Step 6 | 输出 fenced JSON（schema 见提示词） | 强制 |

当 Provider 支持进程内 MCP 工具时，第 4 步优先调用工作区绑定的
`mcp__project_repo__clone_project_repo`，而不是让模型接触 clone URL。主项目仍使用
`repo/`；项目卡片表明问题还需要其他项目时，工具将其克隆到
`related_repos/<project_code>/` 并返回路径、分支和 commit。项目专家复用同一工具与
路径约定。

仓库信息查找优先级（高→低）：

1. `repo_info.clone_url` / `repo_info.repo_url` + `repo_info.default_branch`
2. `project_info.clone_url` / `project_info.repo_url` + `project_info.default_branch`
3. 顶层 `clone_url` / `repo_url` / `repository_url` + `default_branch`
4. `git_context.repository_url` + `git_context.branch_name` / `git_context.commit_id`
5. 项目身份回退：`project_info.project_code` → `project_code` → `issue_info.project_code` → `log_types.<log_type>.project_code` → 任一 `log_types.*.project_code` → `issue_info.service_name`

无任何可解析仓库信息时，直接输出 `"status": "error", "error_kind": "missing_project_identity"`，**不允许仅凭日志答题**。

### 2.1 澄清提问优先于工作流

当用户开启了全局偏好「指令不清晰时允许 Agent 向我提问」时，本 Agent 会额外拿到
`mcp__ask__AskUserQuestion` 工具，以及一段说明「澄清优先于上面的强制工作流」的提示词
（[app/agents/clarification.py](../app/agents/clarification.py) 的 `workflow_agent=True` 分支）。

这段说明是必需的，不是锦上添花：上面的 6 步工作流本身在提示词里被表述为强制流程，
模型会把它理解为「无论如何都要把流程走完并产出 JSON」，从而在收到「请定位问题」这类
没有指明现象、模块或时间范围的笼统诉求时，直接挑一种解读继续跑完，而不是先问清楚。
指引里因此显式列出了本 Agent 场景下「问题不清晰」的判定标准（多处彼此独立的可疑点、
现象在材料中无对应线索、多附件未指明目标），以及「澄清可以发生在流程中间，拿到答案后
从当前步骤继续，最终仍按规定输出围栏 JSON」。

提问由聊天服务通过 `clarification_binding` 注入；Celery 批处理入口不传该参数，因此
不会提问（没有人在 SSE 那头作答）。事件与 broker 机制见
[agent_trace_protocol.md](agent_trace_protocol.md#clarification-askuserquestion)。

### 2.2 项目卡片发现与多项目工作区

项目专家和日志分析在作出项目相关结论前先调用
`mcp__project_repo__discover_projects` 读取完整的已启用项目卡片目录：

- 当前项目已覆盖问题：克隆/复用 `repo/`，不追加无关项目。
- 当前项目选错、另一个项目明确匹配：在当前会话调用
  `clone_project_repo(project_code)`，从返回的 `related_repos/...` 检出中回答，不再要求用户重开会话。
- 问题确实跨项目：只克隆完成问题所必需的项目，并在证据中标明项目与仓库路径。
- 无匹配或证据含糊：如实报告无匹配或请求澄清，不试探性克隆最相近项目。

克隆工具只接受 `project_code`，目标路径由服务端决定；HTTPS token、SSH 身份与仓库
URL 不会出现在工具响应。重复调用复用已有检出，成功后在 `task.json.related_repos`
保存不含凭据的项目卡片、相对路径、分支与 commit，供后续轮次和运行态核验。

---

## 3. 代码强制使用策略

**核心原则**：源码是日志真实含义的 ground truth；克隆并查阅源码是每次分析的强制环节，不再由模型自行判断。

适用范围：

- 无论问题类型（`qa` / `search` / `stats` / `meta` / `root_cause` / `other`）。
- 无论日志包是否含 `metadata.json`。
- 无论用户是否在前端显式选择了项目仓库。

### 3.1 行为对比

| 场景 | 旧行为 | 新行为 |
|---|---|---|
| 有 metadata.json，qa 类问题 | AI 自行判断"不用代码" → 不克隆 | 必须克隆 + 用代码佐证 |
| 无 metadata.json，前端选了项目 | AI 自行判断 → 经常跳过克隆 | 直接用 `task.json` 里的 `repo_info` → 必须克隆 + 用代码佐证 |
| 无 metadata.json 且未选项目 | 看情况报 `missing_project_identity` | 一律报 `missing_project_identity` 终止 |
| 克隆失败 | 行为未定义 | 在 `answer` 里如实报错，降级为 logs-only，禁止编造代码证据 |

### 3.2 用户显式选择项目的链路

1. 前端把 `project_repo_id` 随请求带入；
2. [log_analysis_chat_service.py](../app/services/log_analysis_chat_service.py) 调 `prepare(log_record, require_metadata=False)`（不再要求 `metadata.json` 存在），并调用 `_inject_repo_info_from_project_id`；
3. [ai_analysis.py](../app/tasks/ai_analysis.py) 的 `_inject_repo_info_from_project_id` 把仓库信息写入 `task.json`，标记 `source: "user_selected_project_repo"`；
4. [agent.py](../app/agents/log_analysis/agent.py) 在渲染提示词时探测到该标记，向系统提示词追加 *User-Selected Project Repository* 段落，告知 Agent：`repo_info` 权威、可跳过 metadata 发现，但**克隆与代码查阅仍是强制项**。

### 3.3 克隆失败的容错

- `git clone` 失败时，Agent 必须在 `answer` 中如实说明失败（带退出码 / 错误摘要），随后降级为 logs-only 模式。
- **不允许**用日志虚构出"代码层面"的结论。
- 证据数组中 `repo:path/file.go:N` 形式的引用必须指向**真实存在**的代码行。

---

## 4. Provider / MCP 能力矩阵

`discover_projects`、`lookup_project_repo` 与工作区绑定的 `clone_project_repo` 在不同 Provider 下的可用性见 [app/agents/anthropic_client.py](../app/agents/anthropic_client.py) 的 `PROVIDER_PROFILES`。当 `supports_mcp_server_tools=False` 时：

- 三个 MCP 工具都从 `allowed_tools` 中剔除；
- 系统提示词追加 *Runtime Constraint* 段落，提示 Agent 仅使用显式的 `repo_info` / `metadata.json` 字段；
- 仍**强制**克隆与代码查阅；找不到显式仓库信息时输出 `project_repo_not_registered` 终止。
- 该运行不能追加其他项目，且不得声称已完成多项目分析。

---

## 5. 输出 Schema（Step 6）

```json
{
  "status": "ok",
  "question_type": "root_cause|qa|search|stats|meta|other",
  "answer": "<面向用户问题的直接回答，中文>",
  "summary": "<一句话摘要，中文>",
  "severity": "info|warn|error|critical",
  "root_cause_hypotheses": [
    {
      "hypothesis": "<描述>",
      "evidence": ["repo:path/file.go:42", "log:subdir/app.log:100"]
    }
  ],
  "recommended_actions": [],
  "related_keywords": ["keyword1", "keyword2"]
}
```

字段约束按 `question_type` 分桶（详见提示词 Step 6）：

- `root_cause`：`root_cause_hypotheses` 可填，但每条必须带证据；无相关假设时留 `[]`，不要为凑数编造无关问题。
- `qa` / `search` / `stats` / `meta` / `other`：`root_cause_hypotheses` 必须为 `[]`，`severity` 默认 `info`，真正答案放 `answer`（可用 Markdown）。

---

## 6. 错误码（`error_kind`）

| `error_kind` | 触发条件 |
|---|---|
| `missing_archive` | `LogRecord` 无 `archive_path` / `file_path`，或文件不存在 |
| `missing_project_identity` | `metadata.json` / `task.json` 中均无可解析的仓库字段或项目身份 |
| `project_repo_not_registered` | 通过 `lookup_project_repo` 仍解析不到仓库；或 MCP 工具不可用且无显式仓库信息 |
| `timeout` | 超出 `anthropic_request_timeout_seconds` |
| `cancelled` | 用户主动取消（来自 `cancel_event`） |
| `schema_mismatch` | 模型输出不含 fenced JSON 或缺字段（兜底） |

---

## 7. Trace 协议

Agent 运行期间通过 `trace_emitter` 回调推送 `AgentTraceEvent`，事件类型与传输方式见 [agent_trace_protocol.md](agent_trace_protocol.md)。`LogAnalysisAgent.run` 同时把所有事件累计到结果里的 `trace_events`，便于断线重连/历史回放。

---

## 8. 维护清单

修改 Agent 行为时建议至少同步以下位置：

- [app/prompts/prompts_config.yaml](../app/prompts/prompts_config.yaml) — 系统提示词主体
- [app/agents/log_analysis/agent.py](../app/agents/log_analysis/agent.py) — 运行时提示词增量（Runtime Constraint / User-Selected Project Repository）
- [app/tasks/ai_analysis.py](../app/tasks/ai_analysis.py) — `repo_info` 注入逻辑
- [app/agents/clarification.py](../app/agents/clarification.py) — 澄清提问工具与提示词（四个对话 Agent 共用，改动会同时影响它们）
- 本文档 — 行为对比表与错误码表
