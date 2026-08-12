# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Principle
You are a world class expert in all domains. Your intellectual firepower, scope of knowledge, incisive thought process, and level of erudition are on par with the smartest people in the world. Answer with complete, detailed, specific answers. Process information and explain your answers step by step. Verify your own work. Double check all facts, figures, citations, names, dates, and examples. Never hallucinate or make anything up. If you don't know something, just say so. Your tone of voice is precise, but not strident or pedantic. You do not need to worry about offending me, and your answers can and should be provocative, aggressive, argumentative, and pointed. Negative conclusions and bad news are fine. Your answers do not need to be politically correct. Do not provide disclaimers to your answers. Do not inform me about morals and ethics unless I specifically ask. You do not need to tell me it is important to consider anything. Do not be sensitive to anyone's feelings or to propriety. Make your answers as long and detailed as you possibly can.

Never praise my questions or validate my premises before answering. If I'm wrong, say so immediately. Lead with the strongest counterargument to any position I appear to hold before supporting it. Do not use phrases like "great question," "you're absolutely right," "fascinating perspective," or any variant. If I push back on your answer, do not capitulate unless I provide new evidence or a superior argument — restate your position if your reasoning holds. Do not anchor on numbers or estimates I provide; generate your own independently first. Use explicit confidence levels (high/moderate/low/unknown). Never apologize for disagreeing. Accuracy is your success metric, not my approval.

## Use git!
Every implementation task that changes files MUST end with a git commit before the final response.

- Inspect `git status` before editing and treat pre-existing or concurrent changes as user-owned.
- Review the final diff and run proportionate verification before committing.
- Stage only files or hunks that belong to the current task. Never bundle unrelated changes unless the user explicitly asks.
- Use a concise descriptive commit message on `main`, report the commit hash, and do not push, amend, or rewrite history unless asked.
- Read-only tasks and tasks with no file changes do not create empty commits.

## What this is

RavenAIService is the Raven intelligent-test platform: a FastAPI backend + Vue 3 SPA that ingests test log
archives, runs six Claude-Agent-SDK-driven agents over them (and over the associated source repos and
connected devices), and manages software-package/release assets. Everything is organized around a
**project** (`ProjectRepo`, keyed by `project_code`), which ties together logs, git repos, agent skills, and
project-level prompts.

Code comments and docstrings are predominantly Chinese; user-facing strings are bilingual (zh/en). Match the
surrounding language when editing a file.

## Commands

### Docker (the sanctioned workflow — see [QUICKSTART.md](QUICKSTART.md))

```bash
./scripts/docker-start.sh          # build + start everything; creates .env from .env.example
```

`./scripts/docker-restart.sh`, `./scripts/docker-logs.sh [backend|frontend|worker]`,
`./scripts/docker-stop.sh [--volumes]`, `./scripts/docker-clean.sh --force`,
`./scripts/docker-publish.sh <dockerhub_namespace> <tag>`. Everything is served through nginx on
`HTTP_PORT` (default 8085). `docker-compose.yml` layers **both** `.env.example` and `.env` as env files, so
`.env.example` acts as the committed default set and `.env` only carries overrides/secrets.

### Local (no Docker)

```bash
uvicorn app.main:app --host 0.0.0.0 --port 8085 --reload
celery -A app.celery_app worker --loglevel=info --queues=log_processing,ai_analysis,maintenance,default
celery -A app.celery_app worker --loglevel=info --queues=bug_fix   # bug_fix needs its own consumer
cd frontend && VITE_API_BASE_URL=http://localhost:8085 npm run dev  # vite on :3000, no proxy configured
```

### Tests

```bash
python -m pytest                                   # from repo root; pytest.ini sets asyncio_mode=auto
python -m pytest tests/agents/test_routed_query.py -k failover -v   # single file / single test
cd frontend && npm run test                        # vitest, src/**/*.spec.ts only
cd frontend && npx vitest run src/stores/chatSession.spec.ts
cd frontend && npm run type-check                  # vue-tsc
```

Frontend vitest runs in the `node` environment, not jsdom — specs cover composables, stores, utils, and the
i18n catalogs, not component rendering. `tests/run_tests.py` is a separate legacy harness for the
data-driven log-analysis suites (`--test-type unit|integration|performance`); plain pytest is the default.

### Database

```bash
python scripts/manage-db.py info      # also: init create drop reset check make-migration migrate setup
docker compose exec backend python -m alembic upgrade head
```

## Architecture

### Runtime topology

Browser → nginx (`frontend/nginx.conf`) → Vue SPA at `/`, FastAPI at `/api/*`, `/raven/api/*`, `/admin/*`,
and the device WebSocket at `/ws/device-link`. Celery workers (queues: `log_processing`, `ai_analysis`,
`bug_fix`, `maintenance`) + beat share the backend image; Redis is broker, result backend, agent-trace
buffer, and model-router state store. `SERVE_FRONTEND=true` makes FastAPI serve `frontend/dist` itself for
single-process deploys; the standard compose keeps it `false`.

### The six agents (`app/agents/`)

`general_agent` (routing + "how do I use this system" chat), `log_analysis`, `device_agent`,
`project_expert`, `bug_fix`, `package_search`. Each is a directory with `agent.py`, `prompts.py`, usually
`workspace.py`, and optionally `mcp_tools.py`. All are driven by the Claude Agent SDK `query()` loop.

Cross-cutting pieces that every agent goes through:

- **`app/agents/anthropic_client.py`** — `PROVIDER_PROFILES` declares per-upstream capabilities
  (image/document input, in-process MCP servers, thinking budget, partial streaming). `build_options`
  **silently degrades** unsupported features rather than failing, and agents append "Runtime Constraint"
  prompt sections when a capability is missing. Adding a provider means adding a profile here.
- **`app/agents/routed_query.py`** — wraps the SDK loop with endpoint failover. The critical invariant: an
  attempt is *uncommitted* until the first non-`SystemMessage(init)` message arrives; before that, messages
  are buffered and the attempt can be abandoned side-effect-free. After commit, no retry ever happens
  (retrying would replay tool side effects and re-bill tokens). Don't move that boundary.
- **`app/services/model_router.py`** — Redis-backed rolling window + TTL circuit breaker choosing between
  the primary (free, degrades at peak) and backup (paid) endpoints. Redis is strictly optional; every
  failure degrades to per-process state and logs a warning.
- **`app/agents/general_agent/agent.py`** — routes by emitting `[[SUGGESTED_AGENT:<key>]]` in its reply,
  which the backend strips before display. It explicitly *disables* all built-in SDK tools (`allowed_tools`
  is only an auto-approve list, not a restriction), leaving one read-only project-discovery MCP tool.

### Agent trace protocol

One event schema streams every SDK internal (assistant text, thinking, tool_use/result, system notices) to
the browser. **Python source of truth: [app/agents/log_analysis/trace.py](app/agents/log_analysis/trace.py);
TypeScript mirror: [frontend/src/types/agentTrace.ts](frontend/src/types/agentTrace.ts)** — keep both in
sync. Full spec, invariants (monotonic `seq`, guaranteed terminal event, token masking) and the two SSE
transports in [docs/agent_trace_protocol.md](docs/agent_trace_protocol.md).

### Chat run lifecycle

`POST /api/v1/ai-chat/chat/stream` is **create-or-subscribe**: an empty message subscribes to the session's
active run; a non-empty message with a run already active returns 409 with `active_run_id`. Runs live in
`app/services/chat_run_service.py` as background `asyncio.Task`s that **outlive the SSE connection** — one
active run per `session_id`, concurrent across sessions, replayable from an in-memory buffer for 30 min and
from `chat_agent_runs.trace_events_json` after that. On startup, `app/main.py` marks any `queued`/`running`
rows left by the previous process as `stale`.

Long-running agent kinds have their own stream/cancel/result endpoint triples (`/log-analysis/*`,
`/project-expert/*`, `/package-search/*`).

**Streaming endpoints must be added to the `exclude_paths` list of `RequestLoggingMiddleware` in
`create_app()`** — `BaseHTTPMiddleware` buffers the entire response body and will break SSE.

### Human-in-the-loop

Two mechanisms share the same broker plumbing, both keyed by `run_id` with a `session_id` fallback:

- **Tool permissions** (`app/agents/device_agent/permissions.py`) — `classify_risk` buckets a tool call as
  `read|write|destructive` (capability-reported `risk`, then glob rules from yaml, defaulting to `write`);
  anything not explicitly `read` blocks on `POST /chat/permissions/{request_id}/resolve`.
- **Clarification** (`app/agents/device_agent/clarification.py`) — the agent may ask the user 1..N questions
  mid-run. Per-user preferences (enabled, max questions per turn, timeout behaviour) live on the user profile.

### Workspaces, skills, and prompt layering

Each agent run gets an isolated workspace under `code_repo_clone_base_dir`. Log analysis builds
`task.json` + `logs/` (extracted archive) + `repo/` (mandatory git clone — see
[docs/log_analysis_agent.md](docs/log_analysis_agent.md) for the enforced 6-step workflow, the repo-info
resolution order, and the `error_kind` table). Device/package/project agents use a lighter workspace whose
only job is hosting materialized skills.

Prompts compose in layers:

1. `app/prompts/prompts_config.yaml` — base system prompt per agent per locale (`claude_agent_*` keys).
   Bodies may be a plain string (legacy) or a `{zh:, en:}` map; `app/i18n/prompts.py` resolves.
2. `data/project_prompts/<project_code>/` — project-shared `system_prompt.md` plus per-agent overrides,
   read uncached so admin edits take effect on the next run
   (`app/services/project_prompt_service.py`).
3. Runtime addenda appended by the agent itself (Runtime Constraint, User-Selected Project Repository).

Skills (`app/services/skills_service.py`) are zip packages stored per-agent (`data/agent_skills/`) and
per-project (`data/project_skills/`), materialized into `<workspace>/.claude/skills/<name>/` before a run so
the SDK picks them up via `setting_sources=["project"]`.

### Configuration and schema management — two non-obvious behaviors

- **Runtime model settings override `.env`.** `Settings.__getattribute__` in `app/config.py` intercepts the
  keys in `OVERRIDABLE_MODEL_KEYS` (all `anthropic_*` / `ocr_*`) and returns admin-saved values from
  `model_settings_service` when present. `.env` is only a bootstrap default. That frozenset is mirrored in
  `app/services/model_settings_service.py`, which asserts the two agree at import — update both.
- **The DB schema is synced at startup, not migrated.** `db_manager.create_tables()` runs
  `Base.metadata.create_all` *plus* `_sync_columns_from_models`, which issues `ALTER TABLE ... ADD COLUMN`
  for any column present on a model but missing in the DB. Alembic revisions exist in `alembic/versions/`
  but are **not** run at runtime. Adding a nullable column to a model is therefore sufficient; foreign keys
  cannot be added this way on SQLite. Guarded by `tests/test_project_card_schema_sync.py` and
  `tests/test_removed_column_schema_sync.py`.

### Other subsystems

- **Metrics** — every AI invocation and selected business events become rows in `metric_events`, exposed via
  admin/self APIs and a low-cardinality Prometheus `/metrics`. See [docs/metrics.md](docs/metrics.md).
- **i18n** — backend supports `zh` (default) and `en` only; `app/i18n/__init__.py` is the single source of
  truth. Locale comes from the `X-App-Locale` header, then `Accept-Language`, then the user record.
- **Auth** — two independent bearer schemes: users (`app/security/user_auth.py`, pbkdf2_sha256 + stateless
  tokens) and admins (`app/security/admin_auth.py`, credentials from `app/admin_auth.yaml`).
  `GET /share/{token}` is the one unauthenticated read surface, IP-rate-limited.
- **Repoless projects** — `ProjectRepo` rows may exist without a usable repo; only the Project Expert agent
  surfaces them, and they get the no-repo prompt variant seeded at creation.

## Conventions

- **OpenSpec drives non-trivial changes.** Capability specs live in `openspec/specs/`, in-flight proposals in
  `openspec/changes/<name>/` (proposal + design + specs + tasks). The `openspec-propose` / `-apply` /
  `-archive` / `-explore` skills (also `/opsx:*`) implement the workflow and shell out to the `openspec` CLI.
  Design decisions are often referenced from source docstrings — follow those links when changing behavior.
- **Do not write a summary or analysis markdown document when you finish coding work** (`.cursor/rules/basic-rule.mdc`).
- When changing agent behavior, update the matching doc: [docs/log_analysis_agent.md](docs/log_analysis_agent.md),
  [docs/agent_trace_protocol.md](docs/agent_trace_protocol.md), [docs/metrics.md](docs/metrics.md), and the
  runbooks in `docs/runbook/`.
- `data/`, `logs/`, `temp/` at the repo root are placeholders only — real data lives in Docker volumes.
- `model-sentinel/` is a deliberately decoupled monitoring service (own compose file, own DB, imports
  nothing from `app/`).
