## Context

`app/agents/log_agent.py`、`app/agents/code_analysis_graph.py` 与 `app/agents/xml_utils.py` 共同构成基于 LangGraph 的日志分析 Pipeline：通过 `LogAnalysisAgent`/`CodeAnalysisGraph` 两套 TypedDict 状态机驱动多阶段 LLM 调用，调用方为 `app/tasks/ai_analysis.py::run_ai_analysis_task` (Celery)。LLM 客户端走 `langchain-openai` 的 `ChatOpenAI`，指向 OpenAI 兼容网关（`deepseek_base_url`、`llm_model_name=glm-4.6`）。仓库克隆、日志解压、五维子图编排、提示词渲染、token 压缩等逻辑全部塞在两个上千行的 Python 模块里，提示词写在 `app/prompts/prompts_config.yaml`，由 `_PROMPTS_CACHE` 私有字典缓存。

我们要把这一套全部撤掉，改用 Anthropic 官方的 **Claude Agent SDK**（Python 包 `claude-agent-sdk`）：模型自己控制 agent loop，调用 SDK 内置的 `Bash`/`Read`/`Grep`/`Glob`/`Edit` 等工具，由 Agent 自主完成仓库克隆、关键字检索、日志比对。我们只负责：准备工作区（解压日志归档到临时路径）、注入系统提示词、配置可用工具与权限、收集最终结构化输出。同时为后续把 `chat_agent` / `ai_chat_service` 也搬到 Anthropic 标准上做铺垫，本次先建立 `anthropic_*` 配置族与统一客户端入口。

约束：
- Celery worker 运行环境需具备 `git` CLI、对私有仓库的网络访问、对 `api.anthropic.com`（或企业代理）的出站访问。
- 日志归档可能是大文件（GB 级），临时目录必须按任务隔离并在结束时清理；不能干扰已有的 `cleanup_temp_directories` 定时任务。
- 现有 `LogRecord.ai_analysis_result` 字段为 JSON 文本，前端已依赖部分键（摘要、根因），结构变更要在 design 里固定下来。
- 不接管 `chat_agent`/`ai_chat_service` 的现状；保留 OpenAI 兼容配置。

## Goals / Non-Goals

**Goals:**
- 用 Claude Agent SDK 的 agent loop 完全替换 LangGraph 版日志分析，整段移除旧实现而非渐进重构。
- 建立 `anthropic_*` 配置族与 `app/agents/anthropic_client.py` 统一入口，供本次及后续迁移复用。
- 由 Agent 自主驱动："克隆仓库 → 解压日志 → 关键字检索 → 日志比对 → 输出结构化结论"完整链路，无需在 Python 层硬编码各步骤的 LLM 调用。
- 维持 `POST /logs/{id}/ai-analysis` 等触发接口的对外 URL 与基本响应形态；输出 JSON 结构在 design 中固化并通知前端。
- 工作区严格隔离、自动清理；任务级超时与最大 token / 最大轮次有显式上限。

**Non-Goals:**
- 不迁移 `chat_agent` / `ai_chat_service` / `device_prompt_tool`；这些保持 OpenAI 兼容路径，由后续变更处理。
- 不再保留对"无 repo 元数据时降级到旧 LogAnalysisAgent"的兼容路径——缺少仓库元数据时直接报错。
- 不引入新数据库表或修改 `LogRecord` schema（仅写 `ai_analysis_result` JSON 字段）。
- 不在本次变更中扩展前端 UI；前端按既有解析逻辑兼容新 JSON key。
- 不实现多用户并发抢占同一仓库克隆的复用缓存（每任务独占临时目录，简化实现）。

## Decisions

### Decision 1：用 Claude Agent SDK Python 包，模式选 `query()` 流式迭代

**选择**：直接 `from claude_agent_sdk import query, ClaudeAgentOptions, AssistantMessage, ResultMessage` 在 Celery 任务里以 `async for message in query(...)` 驱动 agent loop；以 `asyncio.run(...)` 包一层供同步 Celery 调用。

**理由**：
- SDK 的 `query()` 提供完整的 agent loop（自动驱动模型→工具→模型循环），无需我们再写 LangGraph 那样的子图。
- 流式消息便于按 `AssistantMessage`/`ToolUseBlock`/`ResultMessage` 写结构化日志，方便排障与限流。
- `ClaudeAgentOptions` 直接控制 `system_prompt`、`allowed_tools`、`permission_mode`、`cwd`、`max_turns`，与"由 Agent 自主使用工具"的目标对齐。

**备选**：使用 `ClaudeSDKClient`（多轮会话式 API）。被否：本任务是单轮"分析一次性产物"，会话式 API 反而要自己管理生命周期。

### Decision 2：Anthropic 配置族新增而非替换 OpenAI 兼容配置，并以 provider profile 显式建模上游服务商

**选择**：在 `app/config.py` 的 `Settings` 中新增独立字段：
```
anthropic_provider: Literal["anthropic", "deepseek", "custom"] = "deepseek"
anthropic_api_key: Optional[str] = None
anthropic_base_url: Optional[str] = None       # None 时由 provider profile 提供
anthropic_model: Optional[str] = None          # None 时由 provider profile 提供默认 model id
anthropic_small_fast_model: Optional[str] = None
anthropic_max_tokens: int = 8192
anthropic_max_turns: int = 30
anthropic_permission_mode: str = "acceptEdits"  # 见 Decision 4
anthropic_request_timeout_seconds: int = 600
```

`app/agents/anthropic_client.py` 内置 `PROVIDER_PROFILES: dict[str, ProviderProfile]`，每个 profile 是一个 dataclass：
```
@dataclass(frozen=True)
class ProviderProfile:
    name: str
    default_base_url: str
    default_model: str
    default_small_fast_model: Optional[str]
    supports_image_input: bool
    supports_document_input: bool
    supports_mcp_server_tools: bool
    thinking_budget_tokens_effective: bool
    disable_parallel_tool_use_effective: bool
    notes: str
```
首发两个 profile：
- `anthropic`：`default_base_url="https://api.anthropic.com"`，`default_model="claude-sonnet-4-6"`，能力全开。
- `deepseek`：`default_base_url="https://api.deepseek.com/anthropic"`，`default_model="deepseek-v4-pro"`（小模型 `deepseek-v4-flash`）；`supports_image_input=False`、`supports_document_input=False`、`supports_mcp_server_tools=False`、`thinking_budget_tokens_effective=False`、`disable_parallel_tool_use_effective=False`（来源：https://api-docs.deepseek.com 兼容性说明）。
- 用户可选 `custom`，必须显式提供 `anthropic_base_url` 与 `anthropic_model`，能力默认按最严格（全部 `False`）。

`build_options(...)` 解析顺序：caller override → `Settings` 字段 → `PROVIDER_PROFILES[settings.anthropic_provider]` 默认值。同时 `assert_anthropic_configured()` 校验：`api_key` 存在；`provider=custom` 时 `base_url`+`model` 必须存在；调用方请求的特性（如 thinking budget）若 profile 标记为不生效则告警 / 拒绝（见 Decision 10）。

**理由**：保留 `deepseek_*` / `llm_*` 旧字段让 `chat_agent` / `ai_chat_service` 不受影响；新增 provider profile 让"切换上游"变成一行配置改动，而非散落在多处的 base_url / model 字符串拼接。本次默认 provider 设为 `deepseek` 以匹配实际部署环境。

**备选**：直接替换 OpenAI 字段并改写 `chat_agent`——超出本次范围且会放大 PR。
**备选**：不引入 profile，调用方直接传 `base_url`/`model`——能跑但失去能力矩阵记录，遇到"为啥 thinking budget 没生效"这类问题没有单一事实源。

### Decision 3：工作区由 Python 准备，仓库地址由 Agent 自主解析并克隆

**选择**：
- Python 端 (`workspace.py`) 在 `code_repo_clone_base_dir/<task_id>/` 下创建临时目录，写入：
  - `logs/`：解压后的日志（`tar.gz` / `zip` / `7z`），其中应包含归档自带的 `metadata.json`；
  - `task.json`：仅包含 Python 端已知的非敏感入参（`question`、`hints`、`log_id`、`log_type` hint），**不**预解析仓库 URL、**不**写入 git token；
  - 空 `repo/` 占位目录。
- 在系统提示词中明确告知 Agent 的标准工作流：
  1. `Read logs/.../metadata.json`（路径在归档内可能带子目录前缀，Agent 需 `Glob` 定位），提取 `project_code`（与可选 `project_name`）；
  2. 调用 MCP 工具 `lookup_project_repo(project_code, project_name?)` → 拿到 `{repo_url, default_branch, auth_required}`；
  3. 用 `Bash` 在 `repo/` 下 `git clone <repo_url> repo && git -C repo checkout <commit-or-default-branch>`；克隆 URL **不在命令行明文出现 token**——见 Decision 12 的 token 注入策略；
  4. 用 `Bash`/`Read`/`Grep`/`Glob` 检索代码与日志。
- `ClaudeAgentOptions.cwd` 指向该临时目录；`allowed_tools` 在 Bash/Read/Grep/Glob 之外加上 MCP 工具命名空间 `mcp__project_repo__lookup_project_repo`；禁用 `Edit`/`Write`/`WebFetch`。

**理由**：用户明确要求 (a) "AI Agent 自己使用临时路径来克隆代码库"、(b) "AI 应该根据项目名称和代号去寻找对应的 git 仓库地址"、(c) "暴露工具来让 AI 获取这个信息"。Python 端只承担"无法或不应让 LLM 做的事"（解压大归档、保管 token、查 DB），其余动作（读 metadata.json、决定调用哪个工具、执行 git 命令、检索）都交给 Agent loop。

**备选**：Python 端预读 metadata.json + 预查注册表，把 `repo_url` 直接塞进 task.json——更简单但违反用户的"由 AI 自主寻找"诉求，且失去了"工具可被 Agent 重复调用以试不同 project_code"的灵活性，否决。

### Decision 4：权限模式 + 工作目录沙箱

**选择**：`permission_mode="acceptEdits"`，`allowed_tools=["Bash","Read","Grep","Glob"]`（明确不含 `Edit`、`Write`、`WebFetch`、`WebSearch`、`TodoWrite`）。`cwd` 指向任务临时目录，并通过 `add_dirs=[]` 不暴露仓库以外路径。Bash 调用通过 SDK 默认的 hook 机制限制——我们额外在系统提示词中要求"所有命令必须运行在 cwd 之下"。

**理由**：日志分析是只读任务，禁止 Agent 写回项目代码或访问外网；`Bash` 必须放开因为需要 `git clone` 与可能的 `tar` 解包（如果我们让 Agent 自行解压则更好，但目前由 Python 端解压更稳）。

**备选**：使用 `permission_mode="default"` 触发逐次确认——不适合后台 Celery 任务。

### Decision 5：Agent 输出契约用"最后一条 message 必须是 JSON 块"

**选择**：在系统提示词最后一段强制要求：
> When you have completed the investigation, output ONLY a fenced JSON code block matching this schema, with no trailing prose:
> ```json
> {"summary": "...","severity":"info|warn|error|critical","root_cause_hypotheses":[{"hypothesis":"...","evidence":["repo:path:line","log:path:line"],"confidence":0.0}],"recommended_actions":["..."],"related_keywords":["..."]}
> ```
Python 端用 `ResultMessage`（SDK 提供）拿最终文本，正则匹配第一段 fenced JSON 解析；解析失败则把 raw text 直接写入 `ai_analysis_result.raw`，并在 `LogRecord.ai_analysis_result.status = "schema_mismatch"`。

**理由**：避免在 Python 端再做一轮 LLM 总结；SDK 的 `ResultMessage.result` 已包含最终文本。

**备选**：把工具结果先汇总再请第二个 Agent 总结——增加额外开销且不必要。

### Decision 6：日志归档解压由 Python 端完成

**选择**：`workspace.py` 在准备阶段把 `LogRecord.archive_path`（已有字段，本地路径）按扩展名调用 `tarfile`/`zipfile`/`py7zr` 解压到 `<workspace>/logs/`，最大解压总大小受 `settings.ai_analysis_max_extract_bytes`（新增，默认 2 GiB）保护，超限拒绝任务。

**理由**：解压不需要 LLM 决策；放在 Python 侧可以集中做大小校验、防 zip-bomb，避免 Agent 误用 `Bash tar` 时把磁盘写满。

**备选**：让 Agent 自己 `tar -xzf`——更"自主"但失去解压配额控制，否决。

### Decision 7：Celery 任务结构与超时

**选择**：保留 `app/tasks/ai_analysis.py::run_ai_analysis_task` 名称与签名（参数为 `log_id: int`），内部：
1. 同步读取 `LogRecord`，校验 `repo_url`/`commit`/`archive_path`；缺失立即失败。
2. 调用 `workspace.prepare(log_record)` 返回 `WorkspaceContext`（含 `temp_dir`、`meta`、清理回调）。
3. 调用 `agent.run(workspace_ctx)`（内部 `asyncio.run`）。
4. `finally:` 一定调用 `workspace.cleanup()`。

任务级软超时设为 `settings.anthropic_request_timeout_seconds + 60`，硬超时多 60s；`max_turns` 同时限制 agent loop 步数。

**理由**：Celery 一致性最小变更；超时双层（HTTP/SDK + Celery）防止 worker 卡死。

### Decision 8：提示词重新写，不参考旧 prompts_config.yaml

**选择**：在 `app/prompts/prompts_config.yaml` 中新增独立 section `claude_agent_log_analysis`（与旧 key 并列），分日志类型（`protocol_stack`、`generic`）维护 `system_prompt` + `user_prompt_template`。旧 key 在本变更删除。提示词显式列出工作目录结构、可用工具、输出契约。

**理由**：用户要求"先删除，再使用 Claude Agent SDK 完全实现"，且 LangGraph 时代提示词是为五维子图写的，复用会带偏 agent loop。

### Decision 9：`ai_analysis_result` JSON 结构固定

**选择**：写入字段为
```json
{
  "engine": "claude-agent-sdk",
  "model": "<settings.anthropic_model>",
  "schema_version": 2,
  "status": "ok" | "schema_mismatch" | "error",
  "summary": "...",
  "severity": "info|warn|error|critical",
  "root_cause_hypotheses": [...],
  "recommended_actions": [...],
  "related_keywords": [...],
  "tool_trace": [{"name":"Bash","input":"...","output_excerpt":"..."}, ...],
  "raw": "<full final text>",
  "duration_seconds": 12.34,
  "token_usage": {"input_tokens":..,"output_tokens":..,"cache_read_tokens":..}
}
```
`tool_trace` 只保留每次工具调用的命令与输出前 1 KiB，便于排障。`schema_version` 用于前端兼容旧 v1 输出。

### Decision 10：把 provider 配置桥接到 Claude Agent SDK 的标准入参，而不是 patch SDK

**选择**：Claude Agent SDK 内部走 Anthropic Python SDK，后者识别 `ANTHROPIC_API_KEY` / `ANTHROPIC_BASE_URL` / `ANTHROPIC_AUTH_TOKEN` 等标准环境变量。我们在 `anthropic_client.build_options(...)` 里：
1. 解析出 `effective_api_key` / `effective_base_url` / `effective_model`（含 provider profile 默认值）。
2. 通过 `ClaudeAgentOptions.env={"ANTHROPIC_API_KEY": ..., "ANTHROPIC_BASE_URL": ..., "ANTHROPIC_MODEL": ...}` 注入到 SDK 子进程；同时显式 `ClaudeAgentOptions.model=effective_model`。
3. 若 caller 请求了当前 profile 标记为"不生效"的特性（如对 DeepSeek profile 设置 `thinking={"budget_tokens": N}`），`build_options` 在日志中以 WARNING 提示并去掉该参数；若 caller 要求图像/文档输入但 profile 不支持，直接抛 `ProviderCapabilityError`。

**理由**：完全不依赖对 SDK 的 monkey-patch，"换 provider"等价于"换两个环境变量 + 换 model id"，与 DeepSeek 官方接入文档（设置 `ANTHROPIC_BASE_URL` + `ANTHROPIC_API_KEY` + 使用其推荐 model id）一致。

**备选**：fork SDK 注入 base_url ——明确反对，升级痛苦。
**备选**：进程级 `os.environ["ANTHROPIC_BASE_URL"] = ...` ——会污染全局，无法在同进程内并存多个 provider（即便短期不需要也是反模式）。

### Decision 11：项目→仓库映射用独立 DB 表，不再用两个 .env 字段

**选择**：新增 SQLAlchemy 模型 `ProjectRepo`（表名 `project_repo`）：
```
id              integer  PK
project_code    string   unique not null   # 业务唯一键，与 metadata.json 中保持一致
project_name    string   not null          # 展示用名称
repo_url        string   not null          # 完整 git URL（不含 token）
default_branch  string   not null default 'main'
git_token       string   nullable          # 覆盖全局 code_repo_git_token；NULL 表示走全局
description     string   nullable
enabled         boolean  not null default true
created_at      datetime not null
updated_at      datetime not null
```
新增 `app/services/project_repo_service.py`：CRUD + `get_by_project_code(code)` + `test_connection(id)`（复用现有 `repo_settings_service.test_repo_connection` 的实现）。新增 alembic migration，并在 migration 中尝试把当前 `settings.code_repo_oam_url` / `code_repo_stack_url` 各自 seed 一行（`project_code='oam_antenna'` / `'stack'`，`project_name` 与 url 取自 settings；不存在则跳过），让现网平滑迁移。`code_repo_oam_url`/`code_repo_stack_url` 字段在本变更里**保留但弃用**——`load_repo_settings` 仍可回退读取它们以保持前端旧 UI 在过渡期不崩。下个 release 删除字段与旧 UI。

**理由**：当前 `.env` 里只支持两个固定槽位（OAM/Stack），新需求是任意数量项目；DB 是天然合适存储；使用独立表而不是把数据塞进现有某个表，便于审计、单独加索引、单独权限。

**备选**：继续 `.env` 用 JSON 字符串保存——可行但不可索引、原子写难、admin UI 需自己解析 JSON，否决。
**备选**：复用 `RepoSettings` 现有 `RepoEntry` 结构 + 序列化为 JSON 写入新字段——比 .env 略好但缺乏 DB 优势，否决。

### Decision 12：通过 Claude Agent SDK in-process MCP server 暴露 `lookup_project_repo` 工具

**选择**：新增 `app/agents/log_analysis/mcp_tools.py`：
```python
from claude_agent_sdk import tool, create_sdk_mcp_server

@tool(
    "lookup_project_repo",
    "Resolve a git repo URL by project_code (and optional project_name) "
    "from the admin-managed registry. Returns clone-ready URL, default branch, "
    "and a one-time short-lived clone token URL when authentication is required.",
    {"project_code": str, "project_name": str | None},
)
async def lookup_project_repo(args):
    code = args["project_code"].strip()
    name = (args.get("project_name") or "").strip() or None
    repo = project_repo_service.get_by_project_code(code)
    if not repo or not repo.enabled:
        return {"content": [{"type": "text", "text": json.dumps({"error":"not_found","project_code":code})}]}
    clone_url = _build_clone_url(repo)   # 注入 token，仅在工具结果内返回
    return {"content": [{"type":"text","text": json.dumps({
        "project_code": repo.project_code,
        "project_name": repo.project_name,
        "repo_url": _mask(repo.repo_url),       # 给 Agent 看的展示 URL（无 token）
        "clone_url": clone_url,                  # Agent 实际 git clone 用
        "default_branch": repo.default_branch,
        "auth_required": bool(repo.git_token or settings.code_repo_git_token),
    })}]}

server = create_sdk_mcp_server(
    name="project_repo", version="1.0.0", tools=[lookup_project_repo]
)
```
`build_options(...)` 把该 server 加入 `ClaudeAgentOptions.mcp_servers={"project_repo": server}`，并把工具名 `mcp__project_repo__lookup_project_repo` 加入 `allowed_tools`。

Token 处理：`clone_url` 字段把 token 注入 `https://oauth2:<token>@host/...` 形式，Agent 可直接 `git clone "$clone_url"`；同时 Agent 应在执行后 `unset` 或避免在 echo 中重复——系统提示词显式要求"不要重复打印 clone_url，引用其值时使用 shell 变量"。`tool_trace` 入库前对 `clone_url` 做 `_mask_repo_url` 脱敏。

**理由**：(a) Claude Agent SDK 原生支持 in-process MCP（`create_sdk_mcp_server`），无需启子进程；(b) 把"查注册表"做成工具而非提示词预填，让 Agent 在第一次失败（如 metadata.json 中 project_code 拼写不规范）后可以再次调用调整参数；(c) 把"明文 token URL 仅出现在工具响应"集中在一个返回点，便于审计。

**备选**：用 SDK 内置 `Bash` 让 Agent `curl` 我们的内部 admin API——需要在 worker 暴露内部接口、做 auth，复杂度高且对外网暴露面增加，否决。
**备选**：Python 预查 + 把 `clone_url` 写进 task.json——见 Decision 3 的备选，违反"由 AI 自主寻找"诉求。

### Decision 13：metadata.json 项目字段约定与缺失/不匹配的 fail-fast

**选择**：固定从 `metadata.json` 读取以下字段（按优先级回退）：
- `project_info.project_code` > `project_code` > `service_name`（已有字段，作为最弱回退）
- `project_info.project_name` > `project_name`

系统提示词把这一回退序列写明给 Agent。Agent 在拿到 `lookup_project_repo` 返回 `error=not_found` 时，**应**：
1. 用 `project_name` 作为 `project_code` 重试一次；
2. 仍失败则在最终 JSON 中以 `status="error"`、`error_kind="project_repo_not_registered"` 报告，**不**继续克隆/分析。

Python 端在 `agent.run` 收尾时检查：若最终 JSON 缺少所有 `root_cause_hypotheses` 且 `error_kind` 已知，按已知错误归类；否则按 `schema_mismatch` 归类。

**理由**：把"项目代号 → repo URL"的所有失败模式都收敛到几个明确的 `error_kind`，前端/运维可直接据此告警（"请管理员去 admin 页面注册项目 X"）。

**备选**：Agent 自己想办法 fallback（如全文 grep 仓库列表）——浪费 token、不可预期，否决。

- **风险**：Anthropic API 不可达或仓库克隆失败时 Agent 会卡循环。**缓解**：双重超时 + `max_turns` + 系统提示词要求"任何 Bash 错误立刻在最终 JSON 中 `status="error"` 报告并停止"。
- **风险**：私有仓库 token 注入到 URL 后会被 Agent 在 `Bash` 命令里打印出来，最终落入日志/`tool_trace`。**缓解**：`workspace.py` 把 `<repo_url with token>` 写进 `meta.json`，但系统提示词强制要求 Agent 用 `git clone "$(cat meta.json | jq -r .repo_url)"` 调用以避免明文出现在命令行；同时在 `tool_trace` 落库前做 `_mask_repo_url` 脱敏。
- **风险**：Claude Agent SDK 内置 `Bash` 工具默认权限较宽，可能执行破坏性命令。**缓解**：`permission_mode="acceptEdits"` 不会自动批准 Bash 之外的写操作；`allowed_tools` 不含 `Edit`/`Write`；额外用 SDK `hooks.PreToolUse` 拦截 `Bash` 中 `rm -rf /`、`curl`、`wget` 等敏感前缀（白名单：`git`/`grep`/`rg`/`tar`/`zcat`/`find`/`cat`/`head`/`tail`/`wc`/`jq`/`ls`）。
- **风险**：大日志归档解压撑爆磁盘。**缓解**：`ai_analysis_max_extract_bytes` 默认 2 GiB 上限 + 每条 entry 大小校验；命中限制直接 `WorkspaceError` 让任务失败。
- **风险**：删除 LangGraph 后若 Anthropic 配置缺失会导致所有日志分析失败。**缓解**：发布前在 staging 配置 `ANTHROPIC_API_KEY` 并跑回归；部署清单中加入"必须配置 Anthropic 凭证"。
- **Trade-off**：放弃 LangGraph 提供的可视化/可重放调试能力，换取自主 agent loop 的灵活性。后续如需可观测，依赖 Anthropic 控制台或自建 `tool_trace` 浏览页。
- **Trade-off**：每次任务都重新 `git clone`（不复用缓存），带来网络/磁盘开销。本次接受，未来如成本敏感可加 commit 级 git mirror 缓存。
- **风险**：DeepSeek Anthropic 兼容端点未来可能滞后于 Anthropic SDK 升级（参数变更、字段重命名），出现"在 Anthropic 上跑得通，在 DeepSeek 上 400"的偏差。**缓解**：CI 增加针对 `deepseek` profile 的契约 smoke test（mock 响应）；线上失败时按 `error_kind="provider_incompatible"` 归类便于按 provider 维度排错。
- **风险**：DeepSeek 文档明确"未知 model 名会自动 fallback 到 `deepseek-v4-flash`"，这意味着 model id 拼错不会报错、但会偷偷降级。**缓解**：`build_options` 启动时通过 `assert_anthropic_configured()` 把 `effective_model` 写入日志一行，并放入 `ai_analysis_result.model` 中以便事后审计；CI 中校验 `model` 字段确实是配置值。
- **风险**：兼容 provider 默认不支持图像/文档输入与 MCP server 工具；若未来其他 agent 误用这些特性会在运行时失败。**缓解**：`ProviderCapabilityError` 在 `build_options` 阶段就抛出（fail-fast），而不是等到调用 API。
- **风险**：`metadata.json` 中 `project_code` 与注册表中条目大小写/前后空格不一致，导致 `not_found`。**缓解**：`project_repo_service.get_by_project_code` 做 `lower().strip()` 规范化匹配；admin UI 在保存时也做同样规范化；`lookup_project_repo` 工具响应里把规范化后的 `project_code` 回显给 Agent，便于人类审计。
- **风险**：注册表里 `git_token` 字段以明文存储（与现有 `code_repo_git_token` 一致）。**缓解**：本变更先沿用现有方案（`.env` 全局 token 也是明文）；在 issues 中开"凭据加密存储"独立 ticket。API 响应里始终用 `••••••••` 占位返回 token 状态而非明文（参考现有 `_TOKEN_MASK`）。
- **风险**：MCP 工具返回的 `clone_url` 含明文 token，可能被 Agent 误打印到 stdout/Bash 输出，进而落到 `tool_trace`。**缓解**：(a) 系统提示词显式禁止 echo `clone_url`；(b) `agent.run` 在写 `tool_trace` 前对所有 `output_excerpt` 做 token 正则脱敏（`https://[^@]+@` → `https://***@`）；(c) 单元测试断言 `tool_trace` 中无明文 token。
- **风险**：旧前端在过渡期访问 `GET /admin/repo-settings`，但后端已改为只读视图后 PUT 失败会让管理员困惑。**缓解**：本变更内 `PUT /admin/repo-settings` 仍可写但只更新 `code_repo_git_token` 与 `clone_depth` 全局字段；OAM/Stack URL 字段标 `deprecated: true` 提示前端切换。
- **风险**：DeepSeek `thinking.budget_tokens` 被忽略——若提示词依赖"先想后说"的 reasoning trace，效果可能与 Anthropic 不一致。**缓解**：日志分析提示词在 design 阶段就不依赖 `budget_tokens`；如果未来场景需要，必须切回 Anthropic 官方 provider 并在 spec 中标注。

## Migration Plan

1. **Step 1（依赖）**：先发一个仅修改 `requirements.txt` 的 PR 增加 `claude-agent-sdk`，确保镜像构建顺利；保留 LangGraph 依赖直到 Step 4。
2. **Step 2（配置）**：合入 `anthropic_*` 字段、provider profile 与 `app/agents/anthropic_client.py`；不引用，不影响行为。在 staging 配置 `ANTHROPIC_PROVIDER=deepseek` + `ANTHROPIC_API_KEY=<DeepSeek key>`（profile 默认 `base_url` / `model` 即可，无需额外配置 `ANTHROPIC_BASE_URL`）。
3. **Step 3（注册表 DB+API+前端）**：合入 `ProjectRepo` 模型 + alembic migration（含 OAM/Stack seed）+ `project_repo_service` + admin CRUD endpoints + 前端"项目仓库管理"页。运行 migration 后管理员立刻可在 admin 页录入新项目；旧 OAM/Stack 字段保留只读。
4. **Step 4（新 Agent）**：合入 `app/agents/log_analysis/`（含 `mcp_tools.py`）、新提示词条目、`workspace.py`；写 unit/integration test；用 mock SDK 驱动端到端，确认 metadata.json → lookup tool → git clone 流程；暂不接通 Celery 入口。
5. **Step 5（切换 + 删旧）**：在同一 PR 内：把 `run_ai_analysis_task` 切到新 Agent；删除 `log_agent.py` / `code_analysis_graph.py` / `xml_utils.py` / `prompts_config.yaml` 旧 key / `requirements.txt` 中 LangGraph 系列依赖。
6. **Step 6（前端）**：通知前端按 `schema_version=2` 解析 `ai_analysis_result`；旧 `repo-settings` 页改为只读提示"已迁移到项目仓库管理"。
7. **回滚**：保留 Step 5 之前的 commit 标签 `pre-claude-agent-sdk-migration`；如需回滚，revert Step 5 即可恢复 LangGraph 路径（Step 2/3/4 引入的代码与 DB 表可保留至下一次清理；alembic migration 可逆）。

## Open Questions

- 默认 provider 是否就用 `deepseek`？本设计当前按 `anthropic_provider="deepseek"` 默认；如未来希望本地开发用 Anthropic 官方便于调试，可改为 `custom` 强制显式配置——待与运维确认部署习惯。
- DeepSeek 当前列出 `deepseek-v4-pro` / `deepseek-v4-flash`，但实际我们租户开通的模型名是否一致？需要从 DeepSeek 后台确认后写入 profile 的 `default_model`。
- `code_repo_clone_depth` 当前默认 1（浅克隆），但 Agent 可能需要看历史 commit 对比，是否在系统提示词里允许 Agent 自行 `git fetch --unshallow`？倾向"默认不允许，必要时由 Agent 在 root_cause 评估后请求"——待与算法 owner 对齐。
- `tool_trace` 是否完整入库（可能很大）？默认每条 1 KiB 截断，若产品需要完整 trace，再加独立表 / 对象存储。
- 是否需要在 profile 中预留 `智谱 GLM` 的 Anthropic 兼容端点？目前文档未给出 GLM 的 Anthropic 兼容入口，留待之后引入；本次只做接口可扩展，不预置 profile 条目。
- `metadata.json` 中项目字段的真实键名待确认：当前设计假设 `project_info.{project_code, project_name}`，回退到 `project_code`/`project_name` 顶层键，再回退到 `issue_info.service_name`。需要从生成 `metadata.json` 的客户端/打包脚本侧确认实际 schema，必要时调整 Decision 13 的回退序列。
- `git_token` 是否做 KMS / 应用级加密？本变更先沿用现有明文方案，独立 issue 跟进。
