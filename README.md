# RavenAIService

中文 | [English](README_EN.md)

> 发布、打包、Docker 启停流程已经统一到 [QUICKSTART.md](QUICKSTART.md)。请优先使用 `scripts/docker-start.sh`、`scripts/docker-stop.sh`、`scripts/docker-publish.sh`，根目录旧脚本已移除。

RavenAIService 是 Raven 智能测试平台的核心服务仓库，面向通信行业复杂测试场景，围绕日志接入、智能分析、设备联动、版本资产管理与发布协同，提供一体化的平台能力。

它不只是一个“日志上传服务”，而是把测试数据、AI 能力、设备能力和版本资产串联起来的业务底座，服务于测试、研发、交付与运维之间的协同闭环。

## 项目定位

Raven 平台聚焦通信行业测试流程中的几类典型痛点：

- 日志来源多、格式杂，测试资产难沉淀
- 协议栈日志处理门槛高，问题定位周期长
- 人工排查依赖经验，知识难复用、难规模化
- 平台与设备割裂，测试执行和问题验证难闭环
- 包、补丁、版本与发布物分散，管理和追溯成本高

围绕这些问题，RavenAIService 希望交付的不只是若干功能模块，而是一条更完整的智能测试链路：

- 统一接入测试日志与问题上下文，减少人工整理成本
- 自动处理协议栈等复杂日志，缩短从上传到分析的等待时间
- 让 AI 参与问题研判、知识检索和对话协同，提升测试效率
- 打通平台与设备能力，实现“提问、执行、回传”的闭环联动
- 统一管理重构包、补丁包和客户端发布物，支撑版本运营与交付

## 平台价值

- 提升测试效率：把日志处理、AI 分析、设备联动集中到统一入口
- 缩短定位闭环：从上传、解析到问答分析，减少跨工具切换和人工反复确认
- 沉淀测试资产：让日志、分析结论、包信息和操作记录成为可复用资产
- 支撑团队协同：让测试、研发、交付和运维围绕同一平台共享上下文
- 强化版本治理：围绕包、补丁和发布物建立统一的管理与追溯能力

## 典型场景

- 测试团队批量接入现场或实验室日志，快速完成归档、筛选和分析
- 面向协议栈、天线、全量等不同日志类型，平台自动识别并进入对应处理流程
- 测试或研发人员基于日志上下文发起 AI 问答，获得更贴近问题现场的分析建议
- 平台将 AI 指令转发到目标设备，完成能力调用、结果回传与联动验证
- 围绕产品版本、补丁包和交付包形成统一资产中心，支撑发布与回溯

## 平台组成概览

为了支撑上述业务闭环，当前仓库集成了以下平台模块：

- `FastAPI` 主服务：承接日志、AI、用户、设备、发布等核心业务
- `Vue 3 + Vite` 控制台：提供统一的 Web 工作台与运营界面
- `Node.js package-server` 子服务：承载重构包中心、语义检索与下载分发
- `Celery + Redis` 异步任务：支撑协议栈日志处理、AI 分析和定时维护
- `Nginx` 网关：对外提供统一入口，降低部署和访问复杂度

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
  |-- frontend/dist 静态站点

Celery + Redis
  |-- 协议栈日志处理
  |-- AI 分析任务
  |-- 定时清理任务

Node package-server
  |-- /raven/api/packages/*
  |-- /raven/api/upload/*
  |-- /raven/api/download/*
  |-- /raven/api/search/*
  |-- FAISS 向量索引
```

## 平台能力地图

### 1. 测试日志资产化

- 支持 `upload-simple`、`upload`、`upload-t04` 等多种日志接入入口
- 自动识别 `stack`、`oam_antenna`、`full` 等日志类型，降低人工分拣成本
- 从压缩包中提取 `metadata.json`，自动补齐问题描述、环境信息与版本信息
- 提供分页查询、筛选、排序、单文件下载、批量下载和批量删除
- 支持人工补充 `issue_description` 与分析结论，让经验可以持续沉淀

### 2. 协议栈日志自动处理

- 通过 `Celery` 异步执行协议栈日志处理任务，避免人工长时间等待
- 服务启动时自动重试失败任务，提升复杂测试场景下的稳定性
- 依赖 `bin/tool_log_decompress` 处理私有压缩格式，打通协议栈日志可读化流程
- 支持使用 `pigz` 并行压缩回包，缺失时自动回退，兼顾效率与兼容性

### 3. AI 智能研判与测试问答

- 提供普通对话和流式对话接口，适配不同测试分析节奏
- 登录用户的聊天会话和消息历史持久化存储，便于持续追踪问题过程
- AI 分析任务会将任务状态与结果写回日志元数据，形成可追溯记录
- 支持结合日志包中的仓库地址、commit 等上下文做更深入的问题研判
- 前端支持在 AI Chat 中联动设备与重构包搜索能力，让问答更贴近实际测试场景

### 4. 平台与设备协同

- 设备通过 `WebSocket /ws/device-link` 注册到平台，形成统一连接入口
- 服务端维护设备在线状态、能力描述与最近心跳，方便实时掌握测试资源
- AI Chat 可将 prompt 转发到指定设备，并等待设备结果回传
- 支持设备 MCP 能力上报，帮助平台生成更匹配设备能力的提示词与动作链路

### 5. 版本资产中心与语义搜索

- `package-server` 负责重构包的上传、删除、详情、下载和批量下载
- 包元数据保存在 JSON 文件中，并同步加载到内存 `Map`，便于高频访问
- 通过 `LangChain + FAISS` 维护向量索引，支持语义检索和建议词
- 支持重建向量索引、查看索引状态，提升测试资产的可发现性
- 默认访问入口为 `http://localhost:8085/raven`

### 6. 发布运营与后台管理

- 后台可统一上传 Linux / macOS / Windows 客户端发布包
- 支持在线编辑 `app/prompts/prompts_config.yaml`，方便运营和策略调整
- 支持普通用户账户管理，满足平台运营和权限治理需求
- 管理员认证配置位于 `app/admin_auth.yaml`

## 仓库结构

```text
RavenAIService/
├── app/                         # FastAPI 主服务
│   ├── api/                     # HTTP / WebSocket 路由
│   ├── agents/                  # AI Agent 与工具链
│   ├── middleware/              # 请求日志、文件大小限制等中间件
│   ├── models/                  # SQLAlchemy 与 Pydantic 模型
│   ├── services/                # 业务服务层
│   ├── tasks/                   # Celery 任务
│   ├── tools/                   # 日志/元数据处理工具
│   ├── prompts/                 # Prompt 配置
│   ├── config.py                # 主配置入口
│   └── main.py                  # FastAPI 应用入口
├── frontend/                    # Vue 3 + Vite 前端
├── package-server/              # Node.js 重构包服务
├── data/                        # 本地占位目录，容器数据通过 Docker volumes 持久化
├── logs/                        # 本地占位目录，容器日志通过 Docker volumes 持久化
├── scripts/                     # Docker 启停、清理、发布脚本
├── alembic/                     # 数据库迁移
├── tests/                       # Python 侧测试
├── docker-compose.yml           # 前端/后端/任务/数据/包服务统一编排
├── Dockerfile                   # 后端与 Celery 镜像构建
└── QUICKSTART.md                # 发布、打包、容器启动规范
```

## 快速开始

完整的发布、打包、容器启动规范请阅读 [QUICKSTART.md](QUICKSTART.md)。常用入口如下：

```bash
./scripts/docker-start.sh
```

等服务就绪后访问：

- 主入口: `http://localhost:8085`
- 日志平台首页: `http://localhost:8085/`
- 重构包管理: `http://localhost:8085/raven`
- AI Chat: `http://localhost:8085/ai-chat`
- 管理后台: `http://localhost:8085/admin/prompts`
- 健康检查: `http://localhost:8085/health`
- Swagger 文档: `http://localhost:8085/docs` 仅在开发环境提供

常用脚本：

```bash
./scripts/docker-logs.sh
./scripts/docker-restart.sh
./scripts/docker-stop.sh
./scripts/docker-publish.sh <dockerhub_namespace> <tag>
```

## 配置说明

### 主配置文件

- `.env`: FastAPI、数据库、Redis、Celery、LLM 等主配置
- `package-server/.env`: 包管理服务与 RAG 检索配置
- `app/prompts/prompts_config.yaml`: AI Prompt 配置
- `app/admin_auth.yaml`: 管理员账户与 Token TTL 配置

### 关键配置项

#### FastAPI / 基础服务

- `ENVIRONMENT`: `development` 或 `production`
- `PORT`: FastAPI 端口，默认 `8085`
- `MAX_FILE_SIZE`: 上传大小限制，默认 `1GB`
- `SQLITE_FILE`: 开发环境默认数据库文件，默认 `data/logs.db`
- `DATABASE_URL`: 如果配置，将优先使用该数据库连接串
- `CELERY_BROKER_URL` / `CELERY_RESULT_BACKEND`: Celery 与 Redis 配置

#### LLM / AI

- `LLM_PROVIDER`
- `DEEPSEEK_BASE_URL`
- `LLM_MODEL_NAME`
- `LLM_REASONING_MODEL`
- `PROMPTS_CONFIG_PATH`

#### package-server / RAG

- `RAVEN_BASE_PATH`: 默认 `/raven`
- `RAVEN_DATA_DIR`: 默认 `data/raven`
- `RAG_EMBEDDING_PROVIDER`: `local | tongyi | openai_compatible`
- `RAG_EMBEDDING_MODEL`
- `ALIBABA_API_KEY`
- `OPENAI_API_KEY`
- `OPENAI_BASE_URL`

## 主要产品入口

| 入口 | 说明 |
| --- | --- |
| `/` | 日志列表与日志相关主界面 |
| `/upload` | 日志上传 |
| `/log/:id` | 日志详情 |
| `/ai-chat` | AI 对话 |
| `/devices` | 设备列表 |
| `/download` | 客户端下载页 |
| `/admin/prompts` | Prompt 后台管理 |
| `/admin/users` | 用户管理 |
| `/admin/releases` | 发布包管理 |
| `/raven` | 重构包管理主页 |
| `/raven/package/:id` | 重构包详情 |

## API 概览

### FastAPI 主服务

#### 健康检查与运维

- `GET /health`
- `POST /cleanup/temp-directories`

#### 日志

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

#### 设备联动

- `WS /ws/device-link`
- `GET /api/v1/device-links`
- `GET /api/v1/device-links/{device_id}/ping`
- `DELETE /api/v1/device-links/{device_id}`

#### 用户与会话

- `POST /api/v1/users/auth/login`
- `GET /api/v1/users/auth/me`
- `GET /api/v1/users/chat-sessions`
- `GET /api/v1/users/chat-sessions/{session_id}/messages`
- `DELETE /api/v1/users/chat-sessions/{session_id}`

#### 管理后台

- `POST /admin/auth/login`
- `POST /admin/auth/logout`
- `GET /admin/auth/me`
- `GET /admin/prompts/config`
- `PUT /admin/prompts/config`
- `GET /admin/releases`
- `POST /admin/releases`
- `POST /admin/releases/upload`
- `DELETE /admin/releases/{release_id}`

#### 发布包公开接口

- `GET /api/v1/releases`
- `GET /api/v1/releases/{release_id}/download`

### package-server

默认通过 `/raven/api/*` 暴露，兼容模式下也可走旧版 `/api/*`。

主要能力包括：

- 包列表、筛选、详情、删除
- 单个下载、批量下载、按类型下载
- 单文件/批量上传
- 智能语义搜索、建议词、向量索引状态、重建索引

更细的子服务说明见 [package-server/README.md](package-server/README.md)。

## 数据与持久化

当前仓库的数据主要落在以下位置：

| 路径 | 内容 |
| --- | --- |
| `data/logs.db` | SQLite 主数据库 |
| `logs/` | FastAPI / Celery 日志 |
| `temp/` | 临时处理目录 |
| `data/releases/` | 客户端发布包 |
| `data/releases.json` | 发布包元数据 |
| `data/device_links.json` | 最近一次设备注册快照 |
| `data/raven/package-metadata.json` | 重构包元数据 |
| `data/raven/vector-store*` | RAG 向量索引 |
| `package-server/data/` | package-server 兜底数据目录 |

Docker 部署下，这些目录会被卷持久化，尤其是：

- `app_logs`
- `app_temp`
- `app_data`
- `redis_data`

## 开发与测试

### Python

```bash
pytest
```

或运行仓库内测试脚本：

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

## 运行注意事项

- 协议栈日志处理依赖 `tool_log_decompress`。Docker 镜像已经自动复制到 `/usr/local/bin`；本地运行时要保证该工具在 `PATH` 中可执行。
- 开发环境默认使用 SQLite；生产环境建议改为 PostgreSQL，并显式配置 `DATABASE_URL` 或 PG 相关变量。
- `frontend/dist` 会同时被 FastAPI 和 `package-server` 复用，因此修改前端后要重新构建。
- 管理员账户定义在 `app/admin_auth.yaml`，上线前应修改默认凭据并改用哈希密码。
- 仓库中的示例配置仅适合作为开发参考，不应直接沿用到生产环境，尤其是 API Key、默认口令和开放 CORS 配置。

## 相关文档

- [PROJECT_SETUP.md](PROJECT_SETUP.md)
- [DEPLOY_USAGE.md](DEPLOY_USAGE.md)
- [docs/DATABASE_USAGE.md](docs/DATABASE_USAGE.md)
- [docs/API_SUMMARY.md](docs/API_SUMMARY.md)
- [package-server/README.md](package-server/README.md)
- [frontend/README.md](frontend/README.md)
