# Deploy.sh 使用说明

## 概述

`deploy.sh` 脚本是 LogStagingService 的部署和管理工具，支持正常部署和数据清理功能。

## 使用方法

### 1. 正常部署服务

```bash
./deploy.sh
```

这将：
- 检查 Docker 和 docker-compose 依赖
- 构建并启动所有服务容器
- 显示服务状态和访问地址

### 2. 清理容器内运行时数据

```bash
./deploy.sh clean
```

这将：
- 检查容器是否运行（如未运行则先启动）
- 在 app 容器内执行 `cleanup_runtime_data.py` 脚本
- 清理所有运行时产生的数据：
  - 数据库中的日志记录
  - 临时文件和缓存
  - 应用程序日志
  - Python 缓存文件
- 重启相关服务以确保清理生效

### 3. 显示帮助信息

```bash
./deploy.sh --help
# 或
./deploy.sh -h
```

## 清理功能详细说明

当使用 `clean` 参数时，脚本会：

1. **检查容器状态**：如果容器未运行，会先启动容器
2. **确保清理脚本可用**：
   - 检查 `cleanup_runtime_data.py` 是否存在于容器中
   - 如果不存在，自动从本地拷贝到容器
   - 设置脚本的执行权限
3. **执行清理脚本**：在容器内运行 `python cleanup_runtime_data.py -f --verbose`
4. **重启服务**：清理完成后重启 app 和 worker 容器

### 清理的数据包括：

- **数据库文件**：`logs.db`
- **临时目录**：`/app/temp/` 下的所有文件
- **日志目录**：`/app/logs/` 下的所有文件  
- **数据目录**：`/app/data/` 下的所有文件
- **Python 缓存**：`__pycache__` 目录和 `.pyc` 文件
- **上传文件**：默认保留，可通过清理脚本参数控制

## 注意事项

1. **数据备份**：清理操作会删除所有运行时数据，请确保重要数据已备份
2. **服务中断**：清理过程中服务会短暂重启
3. **权限要求**：需要 Docker 和 docker-compose 的执行权限
4. **容器依赖**：清理功能需要容器环境，会自动启动容器如果未运行

## 错误处理

脚本包含完整的错误处理：
- 检查 Docker 和 docker-compose 是否安装
- 验证清理脚本执行结果
- 提供详细的错误信息和日志

## 示例输出

### 正常部署
```
[INFO] 开始部署 LogStagingService...
[SUCCESS] 服务部署成功
[INFO] 等待服务启动...
[INFO] 检查服务状态:
[INFO] 服务访问地址: http://localhost:8085
[INFO] 健康检查: http://localhost:8085/health
```

### 数据清理
```
[INFO] 开始清理容器内的运行时数据...
[INFO] 在容器内执行清理脚本...
[SUCCESS] 容器内数据清理完成
[INFO] 重启服务...
[SUCCESS] 清理操作完成，服务已重启
```
---

## 配置 Anthropic 标准 LLM（Claude Agent SDK）

日志智能分析功能现已迁移到 Claude Agent SDK，需要配置 Anthropic 兼容 LLM 服务。

### 环境变量

| 变量名 | 必填 | 默认值 | 说明 |
|--------|------|--------|------|
| `ANTHROPIC_PROVIDER` | 否 | `deepseek` | provider 类型：`anthropic` / `deepseek` / `custom` |
| `ANTHROPIC_API_KEY` | **是** | — | LLM 服务 API Key |
| `ANTHROPIC_BASE_URL` | 否 | 由 provider 决定 | 自定义端点（仅 `provider=custom` 或覆盖默认值时需要）|
| `ANTHROPIC_MODEL` | 否 | 由 provider 决定 | 模型 ID（覆盖 provider 默认值时使用）|
| `ANTHROPIC_MAX_TURNS` | 否 | `30` | Agent 最大轮次 |
| `ANTHROPIC_REQUEST_TIMEOUT_SECONDS` | 否 | `600` | 单次分析超时（秒）|
| `AI_ANALYSIS_MAX_EXTRACT_BYTES` | 否 | `2147483648`（2 GiB）| 日志归档最大解压大小 |

### 接入示例

#### DeepSeek（默认，推荐国内部署）

```env
ANTHROPIC_PROVIDER=deepseek
ANTHROPIC_API_KEY=<your-deepseek-api-key>
# ANTHROPIC_BASE_URL 和 ANTHROPIC_MODEL 无需设置，使用 profile 默认值：
#   base_url = https://api.deepseek.com/anthropic
#   model    = deepseek-v4-pro
```

参考：https://api-docs.deepseek.com（搜索 "Anthropic compatible"）

#### Anthropic 官方

```env
ANTHROPIC_PROVIDER=anthropic
ANTHROPIC_API_KEY=sk-ant-xxxx
# 默认模型：claude-sonnet-4-6
# 如需指定：ANTHROPIC_MODEL=claude-opus-4-7
```

#### 自定义兼容端点

```env
ANTHROPIC_PROVIDER=custom
ANTHROPIC_API_KEY=<your-api-key>
ANTHROPIC_BASE_URL=https://your-gateway.example.com/anthropic
ANTHROPIC_MODEL=your-model-id
```

---

## Provider 能力矩阵

| 能力 | anthropic | deepseek | custom |
|------|-----------|----------|--------|
| 图像输入 | ✓ | ✗ | ✗ |
| 文档输入 | ✓ | ✗ | ✗ |
| MCP server 工具 | ✓ | ✗（但 in-process MCP 仍可用）| ✗ |
| `thinking.budget_tokens` | ✓ | ✗（参数被静默忽略，并产生 WARNING 日志）| ✗ |
| `disable_parallel_tool_use` | ✓ | ✗ | ✗ |

**注意**：DeepSeek 对未知 model 名会自动 fallback 到 `deepseek-v4-flash`，此行为不会报错。每次 Agent 运行时，实际使用的 `model` 会写入 `ai_analysis_result.model` 字段，便于事后审计。

---

## 项目仓库注册

日志分析 Agent 需要通过注册表将日志中的 `project_code` 解析为 git 仓库地址。

### Admin 页面操作步骤

1. 登录 Admin 页面 → 「项目仓库管理」
2. 点击「新增」，填写：
   - **项目代号 (project_code)**：与日志 `metadata.json` 中的 `project_info.project_code` 一致（系统自动小写+去空格）
   - **项目名称**：展示用，也可作为查询回退
   - **仓库 URL**：完整 git URL（不含 token）
   - **默认分支**：如 `main` / `develop`
   - **Git Token**（可选）：per-repo token，留空则使用全局 `CODE_REPO_GIT_TOKEN`
3. 点击「测试连接」验证 URL 和 token 是否正确
4. 保存

### `metadata.json` 字段约定

Agent 按以下优先级读取项目代号（首个非空值生效）：

```
project_info.project_code  →  project_code（顶层）  →  issue_info.service_name
```

项目名称（用于重试）：
```
project_info.project_name  →  project_name（顶层）
```

### `project_code` 规范化

系统在写入和查询时均做 `.strip().lower()`，因此 `"Foo "`, `"foo"`, `"FOO"` 等价。

---

## 升级流程

1. **备份** 当前数据库（特别是 `log_record` 表的 `metadata_json` 字段）。
2. 在 `.env` 中配置 `ANTHROPIC_API_KEY`（及可选的其他 `ANTHROPIC_*` 变量）。
3. **运行 alembic migration**：
   ```bash
   alembic upgrade head
   ```
   Migration 会自动将 `CODE_REPO_OAM_URL` / `CODE_REPO_STACK_URL` 的现有值 seed 为 `project_code='oam_antenna'` / `'stack'` 两行（已存在则跳过）。
4. 登录 Admin 页面，在「项目仓库管理」中**补录**其他项目仓库。
5. 重启 Celery worker（`celery -A app.celery_app worker`）使新代码生效。
6. 触发一条测试日志的 AI 分析，验证 `ai_analysis_result.engine == "claude-agent-sdk"`。
