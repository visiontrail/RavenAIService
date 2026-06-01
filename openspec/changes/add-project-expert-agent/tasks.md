## 1. Prompts & Skill registry

- [x] 1.1 在 `app/prompts/prompts_config.yaml` 新增 `claude_agent_project_expert.generic` 块（`system_prompt` + `user_prompt_template`）：描述只含 `repo/` 与 `task.json` 的工作区、首轮克隆/后续复用 `repo/.git` 规则、`lookup_project_repo` 用法、以"回答用户问题"为目标的工作流；不含任何 logs/ 或 metadata.json 步骤
- [x] 1.2 在 `app/services/skills_service.py` 的 `SUPPORTED_AGENTS` 注册 `project_expert` 条目（`name="ProjectExpertAgent"`, `framework="Claude Agent SDK"`）

## 2. Agent package (`app/agents/project_expert/`)

- [x] 2.1 新建 `__init__.py` 并导出 `ProjectExpertAgent`
- [x] 2.2 新建 `prompts.py`：`get_prompts()` / `render_user_prompt(...)`，读取 `claude_agent_project_expert` 键，结构对齐 `log_analysis/prompts.py`
- [x] 2.3 新建 `workspace.py`：`WorkspaceContext`（`task_id`/`temp_dir`/`repo_dir`/`task_json_path`/`metadata`，无 `logs_dir`）、`prepare(*, project_repo, question, hints, session_id?)`（只建 `repo/`，写含 `repo_info(source="user_selected_project_repo")` 的 `task.json`，不解压、不校验 metadata.json、不落 git token）、幂等 `cleanup(ctx)`
- [x] 2.4 新建 `agent.py`：`ProjectExpertAgent` 驱动 `query()` loop，`AGENT_KEY="project_expert"`，`ALLOWED_TOOLS=[Bash,Read,Grep,Glob,Skill,PROJECT_REPO_MCP_TOOL]`；`from app.agents.log_analysis.trace import ...` 复用 trace；`from app.agents.log_analysis.mcp_tools import get_mcp_server` 复用 `lookup_project_repo`；提供 `run`/`run_sync`，复用取消/超时/token 掩码/结果抽取逻辑
- [x] 2.5 在 `agent.py` 的 run 前调用 `skills_service.materialize_enabled_skills("project_expert", workspace_dir)` 并设 `setting_sources=["project"]`

## 3. Service layer

- [x] 3.1 新建 `app/services/project_expert_chat_service.py`，以 `LogAnalysisChatService` 为蓝本复制 `AgentJob` / in-process `_jobs` 注册表 / SSE 缓冲 / late-subscriber replay / `run_id` 投射 / 保留时长常量
- [x] 3.2 实现 `stream(*, message, session_id, history_json, remember, project_repo_id, db, user, owner_scope)`（无 `file` 参数）：新会话校验 `project_repo_id` 必填，经 `project_repo_service` 解析项目并 `prepare` 工作区；会话注册表目录用 `<base>/chat_project_expert_sessions`
- [x] 3.3 实现会话级持久工作区：首轮 `prepare` 并记录 `temp_dir`；后续轮复用同一工作区（Agent 见 `repo/.git` 复用克隆）
- [x] 3.4 实现中途换项目策略：follow-up 传入与首轮不同的 `project_repo_id` 时维持首轮项目并发 `system_notice`
- [x] 3.5 实现 `cancel(session_id, user)` 与 `get_status(session_id, user)`（轮询兜底）；导出单例 `project_expert_chat_service`

## 4. API endpoints (`app/api/ai_chat.py`)

- [x] 4.1 新增 `POST /project-expert/stream`：`message`/`session_id`/`history`/`remember`/`project_repo_id`(必填) 表单字段，无 `File`；owner_scope + cookie 透传 + SSE header 对齐 `/log-analysis/stream`
- [x] 4.2 新增 `POST /project-expert/cancel`（body `{session_id}`）与 `GET /project-expert/result?session_id=...`
- [x] 4.3 缺失 `project_repo_id` 的新会话返回 4xx（`project_repo_required`）

## 5. Front-end (`frontend/`)

- [x] 5.1 `AIChat.vue`：`AgentOption.agentType` 扩展 `'project-expert'`，新增 `projectExpertAgentOption`（名称"项目专家"）
- [x] 5.2 选中"项目专家"时复用 `ensureProjectRepoOptions()`，把 `selectedProjectRepoId` 设为发送前必填（未选禁用发送并提示），并禁用日志文件选择/拖拽（与 package agent 互斥逻辑一致）
- [x] 5.3 在 `frontend/src/api/`（chat/index）新增 `projectExpertStream` / `projectExpertCancel` / `projectExpertResult` 方法，发送时带 `project_repo_id`
- [x] 5.4 复用 `conversationRuns` store 的 SSE 解析与 `AgentTraceStream.vue` 渲染 Project Expert 的 trace

## 6. Tests & verification

- [x] 6.1 `tests/agents/test_project_expert.py`：工作区只含 `repo/`+`task.json`、无 `logs/`、不要求 metadata.json；`task.json` 含 `repo_info(source="user_selected_project_repo")` 且不含 token
- [x] 6.2 测试首轮克隆 / 后续复用 `repo/.git` 不重复克隆；trace 与 `task.json` 不含明文 git token（断言 `mask_tokens` 生效）
- [x] 6.3 service 测试：`project_repo_id` 必填校验、会话工作区复用、中途换项目 `system_notice`、取消、`/result` 轮询
- [x] 6.4 API 契约测试：`/project-expert/stream` 无 `file` 参数、SSE 事件类型与 Log Analysis 一致；缺 `project_repo_id` 返回 `project_repo_required`
- [ ] 6.5 交叉回归：确认改动未影响 `log_analysis` / DeviceAgent / GeneralAgent / PackageSearch 既有测试（复用 `log_analysis.trace` 的耦合回归）
- [x] 6.6 `openspec validate add-project-expert-agent` 通过；手动跑通一次"选项目 → 提问 → 克隆 → 回答 → 追问复用"端到端
