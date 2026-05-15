# RavenAIService

[中文](README.md) | English

RavenAIService is the core service repository of the `Raven` intelligent testing platform. It is designed for complex telecom testing scenarios and brings together log intake, intelligent analysis, device collaboration, version asset management, and release operations into one platform foundation.

It is no longer just a “log staging service”. It is the business backbone that connects test data, AI capabilities, device-side execution, and package assets across testing, R&D, delivery, and operations workflows.

## Product Positioning

Raven focuses on a few recurring pain points in telecom testing:

- logs come from many places and are hard to standardize or reuse
- protocol-stack logs are expensive to process and slow to investigate
- troubleshooting is still heavily experience-driven and difficult to scale
- platform workflows and device workflows are disconnected
- packages, patches, releases, and test assets are scattered across tools

RavenAIService is built to turn those fragmented steps into a more complete intelligent testing flow:

- unify test log intake and issue context
- automate protocol-stack processing and reduce waiting time
- bring AI into analysis, retrieval, and troubleshooting collaboration
- connect platform and device capabilities into a closed-loop workflow
- centralize rebuild packages, patches, and client releases for better governance

## Platform Value

- Higher testing efficiency: logs, AI, devices, and admin workflows live in one place
- Faster issue turnaround: teams move from upload to analysis with fewer handoffs
- Better asset reuse: logs, analysis results, package data, and actions become reusable knowledge
- Stronger collaboration: testing, R&D, delivery, and operations work on shared context
- Better version governance: packages, patches, and releases are managed through one asset center

## Typical Scenarios

- Test teams ingest field or lab logs in batches for fast archiving, filtering, and investigation
- Different log types such as protocol-stack, antenna, and full logs can enter dedicated handling flows
- Test and R&D engineers can ask AI questions grounded in real log context
- The platform can forward AI instructions to a target device and wait for execution results
- Product versions, patches, and delivery packages can be managed through one traceable asset center

## Platform Overview

To support that end-to-end workflow, the repository includes these platform modules:

- `FastAPI` main service: core business flows for logs, AI, users, devices, and releases
- `Vue 3 + Vite` console: the unified web workspace for testers and administrators
- `Node.js package-server`: rebuild package center, semantic search, and download distribution
- `Celery + Redis`: asynchronous execution for protocol-stack processing, AI analysis, and maintenance jobs
- `Nginx`: a single external entry to simplify deployment and access

## Architecture

```text
Browser
  |
  | http://localhost:8085
  v
Nginx
  |-- /                -> FastAPI (8085)
  |-- /ws/device-link  -> FastAPI WebSocket
  |-- /raven           -> Node package-server (8083)

FastAPI
  |-- /health
  |-- /api/v1/logs/*
  |-- /api/v1/ai-chat/*
  |-- /api/v1/users/*
  |-- /api/v1/device-links/*
  |-- /api/v1/releases/*
  |-- /admin/*
  |-- frontend/dist static site

Celery + Redis
  |-- protocol-stack log processing
  |-- AI analysis jobs
  |-- scheduled cleanup jobs

Node package-server
  |-- /raven/api/packages/*
  |-- /raven/api/upload/*
  |-- /raven/api/download/*
  |-- /raven/api/search/*
  |-- FAISS vector index
```

## Capability Map

### 1. Turning Test Logs into Managed Assets

- Supports `upload-simple`, `upload`, and `upload-t04` entry points
- Detects `stack`, `oam_antenna`, and `full` log types automatically
- Extracts `metadata.json` from archives to enrich issue, environment, and version context
- Provides pagination, filtering, sorting, single download, batch download, and batch delete
- Supports manual issue description updates and manual analysis notes for knowledge retention

### 2. Automated Protocol-Stack Processing

- Runs protocol-stack log processing asynchronously through `Celery`
- Retries failed protocol-stack jobs on application startup
- Relies on the external `bin/tool_log_decompress` utility for private archive formats
- Can use `pigz` for faster parallel recompression, with automatic fallback

### 3. AI-Assisted Analysis and Test Conversation

- Exposes standard and streaming chat APIs
- Persists chat sessions and messages for authenticated users
- Writes AI analysis task state and results back into log metadata
- Can use repository URL and commit information embedded in metadata for deeper investigation
- Frontend supports package search and device-linked workflows inside AI Chat

### 4. Platform-to-Device Collaboration

- Devices register through `WebSocket /ws/device-link`
- The service tracks online state, capabilities, and last heartbeat
- AI Chat can forward prompts to a specific device and wait for the device response
- Devices can report MCP capabilities so prompts can better match real device-side abilities

### 5. Version Asset Center and Semantic Retrieval

- `package-server` handles upload, delete, detail, download, and batch download flows
- Package metadata is stored in JSON and cached in memory
- `LangChain + FAISS` is used for semantic search and suggestion generation
- Supports index rebuild and index status inspection
- Default package entry is `http://localhost:8085/raven`

### 6. Release Operations and Admin Management

- Admin UI can upload Linux / macOS / Windows client release artifacts
- Admin UI can edit `app/prompts/prompts_config.yaml`
- Admin UI can manage end-user accounts
- Admin authentication is configured in `app/admin_auth.yaml`

## Repository Layout

```text
RavenAIService/
├── app/                         # FastAPI main service
│   ├── api/                     # HTTP / WebSocket routes
│   ├── agents/                  # AI agents and toolchain
│   ├── middleware/              # request logging, file size limits, etc.
│   ├── models/                  # SQLAlchemy and Pydantic models
│   ├── services/                # service layer
│   ├── tasks/                   # Celery tasks
│   ├── tools/                   # log / metadata helpers
│   ├── prompts/                 # prompt configuration
│   ├── config.py                # main config entry
│   └── main.py                  # FastAPI app entry
├── frontend/                    # Vue 3 + Vite frontend
├── package-server/              # Node.js rebuild package service
├── data/                        # SQLite, releases, Raven data
├── logs/                        # application logs
├── nginx/                       # Nginx config
├── alembic/                     # database migrations
├── tests/                       # Python-side tests
├── docker-compose.yml           # standard deployment stack
├── Dockerfile                   # combined image build
├── start_all.sh                 # local FastAPI/Celery/Redis bootstrap script
└── start_combined.sh            # container entrypoint for FastAPI + package-server
```

## Quick Start

### Option 1: Docker, recommended

This is the fastest way to experience the full platform and the closest option to a production-style deployment.

```bash
cp .env.example .env
cp package-server/.env.example package-server/.env
./deploy.sh
```

After startup:

- Main entry: `http://localhost:8085`
- Log platform: `http://localhost:8085/`
- Rebuild package center: `http://localhost:8085/raven`
- AI Chat: `http://localhost:8085/ai-chat`
- Admin console: `http://localhost:8085/admin/prompts`
- Health check: `http://localhost:8085/health`
- Swagger docs: `http://localhost:8085/docs` in development only

Notes:

- `docker-compose.yml` only exposes `8085` publicly, through `nginx`
- `deploy.sh` handles stale container conflicts and may enable an optional `8083` compatibility entry when possible
- Inside the `app` container, `FastAPI` and `package-server` are started together

### Option 2: Native local development

This is suitable for engineering debugging and local validation, but you need to run Python, Redis, Celery, and the Node subservice separately.

#### 1. Prerequisites

Recommended versions:

- Python `3.11`
- Node.js `20+`, minimum `18+`
- Redis `7+`

#### 2. Initialize config files

```bash
cp .env.example .env
cp package-server/.env.example package-server/.env
```

#### 3. Install Python dependencies

```bash
python3 -m venv venv
source venv/bin/activate
pip install -U pip
pip install -r requirements.txt
```

#### 4. Run database migrations

```bash
alembic upgrade head
```

#### 5. Start Redis

If Redis is not already available locally, use the repo helper:

```bash
./start_redis.sh
```

#### 6. Start Celery worker

```bash
celery -A app.celery_app worker \
  --loglevel=info \
  --concurrency=2 \
  --queues=log_processing,ai_analysis,maintenance,default
```

#### 7. Start Celery beat

```bash
celery -A app.celery_app beat --loglevel=info
```

#### 8. Build the frontend

```bash
cd frontend
npm install
npm run build
cd ..
```

#### 9. Start package-server

```bash
cd package-server
npm install
PORT=8083 node src/index.js
```

#### 10. Start FastAPI

```bash
uvicorn app.main:app --host 0.0.0.0 --port 8085 --reload
```

### Local bootstrap helper

The repository includes `start_all.sh`, which helps bring up most of the local development environment automatically:

- create/activate `venv`
- install Python dependencies
- start Redis
- run Alembic migrations
- start Celery worker and beat
- build frontend
- start FastAPI

Run it with:

```bash
./start_all.sh
```

Important: `start_all.sh` currently does **not** start `package-server`, so `/raven` package and RAG features still require a separate Node process.

## Configuration

### Main config files

- `.env`: FastAPI, database, Redis, Celery, LLM, and base service config
- `package-server/.env`: package management and RAG config
- `app/prompts/prompts_config.yaml`: AI prompt configuration
- `app/admin_auth.yaml`: admin accounts and token TTL settings

### Important settings

#### FastAPI / base service

- `ENVIRONMENT`: `development` or `production`
- `PORT`: FastAPI port, default `8085`
- `MAX_FILE_SIZE`: upload limit, default `1GB`
- `SQLITE_FILE`: default development database path, default `data/logs.db`
- `DATABASE_URL`: preferred if explicitly set
- `CELERY_BROKER_URL` / `CELERY_RESULT_BACKEND`: Celery / Redis setup

#### LLM / AI

- `LLM_PROVIDER`
- `DEEPSEEK_BASE_URL`
- `LLM_MODEL_NAME`
- `LLM_REASONING_MODEL`
- `PROMPTS_CONFIG_PATH`

#### package-server / RAG

- `RAVEN_BASE_PATH`: default `/raven`
- `RAVEN_DATA_DIR`: default `data/raven`
- `RAG_EMBEDDING_PROVIDER`: `local | tongyi | openai_compatible`
- `RAG_EMBEDDING_MODEL`
- `ALIBABA_API_KEY`
- `OPENAI_API_KEY`
- `OPENAI_BASE_URL`

## Main Product Entrypoints

| Path | Purpose |
| --- | --- |
| `/` | main log list and log workflow UI |
| `/upload` | log upload |
| `/log/:id` | log detail |
| `/ai-chat` | AI chat |
| `/devices` | device list |
| `/download` | client download page |
| `/admin/prompts` | prompt admin page |
| `/admin/users` | user admin page |
| `/admin/releases` | release admin page |
| `/raven` | rebuild package center |
| `/raven/package/:id` | rebuild package detail |

## API Overview

### FastAPI main service

#### Health and operations

- `GET /health`
- `POST /cleanup/temp-directories`

#### Logs

- `POST /api/v1/logs/upload-simple`
- `POST /api/v1/logs/upload`
- `POST /api/v1/logs/upload-t04`
- `GET /api/v1/logs`
- `GET /api/v1/logs/{log_id}`
- `DELETE /api/v1/logs/{log_id}`
- `GET /api/v1/logs/{log_id}/download`
- `POST /api/v1/logs/{log_id}/download-count`
- `POST /api/v1/logs/batch/delete`
- `POST /api/v1/logs/batch/download`
- `POST /api/v1/logs/{log_id}/analyze`
- `GET /api/v1/logs/{log_id}/analysis/status`
- `PUT /api/v1/logs/{log_id}/issue-description`
- `POST /api/v1/logs/{log_id}/manual-analysis`

#### AI Chat

- `POST /api/v1/ai-chat/chat`
- `POST /api/v1/ai-chat/chat/stream`

#### Device link

- `WS /ws/device-link`
- `GET /api/v1/device-links`
- `GET /api/v1/device-links/{device_id}/ping`
- `DELETE /api/v1/device-links/{device_id}`

#### Users and sessions

- `POST /api/v1/users/auth/login`
- `GET /api/v1/users/auth/me`
- `GET /api/v1/users/chat-sessions`
- `GET /api/v1/users/chat-sessions/{session_id}/messages`
- `DELETE /api/v1/users/chat-sessions/{session_id}`

#### Admin

- `POST /admin/auth/login`
- `POST /admin/auth/logout`
- `GET /admin/auth/me`
- `GET /admin/prompts/config`
- `PUT /admin/prompts/config`
- `GET /admin/releases`
- `POST /admin/releases`
- `POST /admin/releases/upload`
- `DELETE /admin/releases/{release_id}`

#### Public releases

- `GET /api/v1/releases`
- `GET /api/v1/releases/{release_id}/download`

### package-server

By default, the Node subservice is exposed under `/raven/api/*`, with optional legacy compatibility under `/api/*`.

Its main responsibilities are:

- package list, filters, detail, delete
- single download, batch download, type-based download
- single and batch upload
- semantic search, suggestions, vector index status, index rebuild

For deeper subservice details, see [package-server/README.md](package-server/README.md).

## Data and Persistence

Main data locations in this repository:

| Path | Content |
| --- | --- |
| `data/logs.db` | main SQLite database |
| `logs/` | FastAPI / Celery logs |
| `temp/` | temporary processing workspace |
| `data/releases/` | client release files |
| `data/releases.json` | release metadata |
| `data/device_links.json` | last persisted device snapshots |
| `data/raven/package-metadata.json` | rebuild package metadata |
| `data/raven/vector-store*` | RAG vector index |
| `package-server/data/` | fallback package-server data directory |

In Docker deployment, these are persisted through volumes, especially:

- `app_logs`
- `app_temp`
- `app_data`
- `redis_data`

## Development and Testing

### Python

```bash
pytest
```

Or run the bundled helper:

```bash
python tests/run_tests.py
```

### Frontend

```bash
cd frontend
npm run type-check
npm run build
```

### package-server

```bash
cd package-server
npm start
```

## Operational Notes

- Protocol-stack processing depends on `tool_log_decompress`. The Docker image installs it automatically into `/usr/local/bin`; for native development you must make sure it is executable and available in `PATH`.
- Development defaults to SQLite. For production, PostgreSQL is the safer choice, configured through `DATABASE_URL` or the PG-specific variables.
- `frontend/dist` is reused by both FastAPI and `package-server`, so frontend changes must be rebuilt before they are reflected in the integrated UI.
- Admin accounts are defined in `app/admin_auth.yaml`. Replace default credentials and use hashed passwords before any real deployment.
- Example configuration files are for development reference only. Do not reuse exposed API keys, default passwords, or permissive CORS settings in production.

## Related Documents

- [PROJECT_SETUP.md](PROJECT_SETUP.md)
- [DEPLOY_USAGE.md](DEPLOY_USAGE.md)
- [docs/DATABASE_USAGE.md](docs/DATABASE_USAGE.md)
- [docs/API_SUMMARY.md](docs/API_SUMMARY.md)
- [package-server/README.md](package-server/README.md)
- [frontend/README.md](frontend/README.md)
