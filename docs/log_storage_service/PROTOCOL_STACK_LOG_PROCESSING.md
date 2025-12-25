# 协议栈日志异步处理服务文档

## 概述

本服务实现了完整的协议栈日志异步处理功能，包括自动检测、任务队列、进度跟踪和错误处理。当用户上传包含"stack"关键字的日志文件时，系统会自动触发异步处理流程。

## 功能特性

### 1. 自动检测触发
- 文件上传后自动检测日志类型
- 如果文件名包含"stack"，自动触发协议栈日志处理
- 使用Celery + Redis异步任务队列

### 2. 处理工作流程
- **解压阶段**：解压上传的tar.gz文件到临时目录
- **处理阶段**：调用外部工具 `tool_log_decompress [log_path] [thread_num]`
- **重打包阶段**：重新打包处理后的文件
- **完成阶段**：更新数据库状态和进度，清理临时文件

### 3. 进度估算
- 基于文件大小估算处理时间
- 假设处理速度：100MB/s
- 进度公式：`progress = (elapsed_time * 100MB/s) / total_file_size * 100%`
- 最大进度限制：95%（完成后设为100%）

### 4. 状态管理
- `pending`：等待处理
- `processing`：正在处理
- `completed`：处理完成
- `failed`：处理失败

### 5. 错误处理
- 解压失败处理
- 工具调用失败处理
- 重打包失败处理
- 自动重试机制（最多3次，指数退避）

## API接口

### 任务状态查询

#### 1. 根据任务ID查询状态
```http
GET /api/v1/tasks/status/{task_id}
```

**响应示例：**
```json
{
  "success": true,
  "message": "Task status retrieved successfully",
  "data": {
    "task_id": "abc123-def456",
    "log_id": "log-uuid",
    "status": "processing",
    "progress": 45.5,
    "retry_count": 0,
    "error_message": null,
    "processing_started_at": "2024-01-01T10:00:00Z",
    "processed_at": null,
    "celery_task_state": "PROGRESS",
    "celery_task_info": {}
  }
}
```

#### 2. 根据日志ID查询任务状态
```http
GET /api/v1/tasks/log/{log_id}/status
```

#### 3. 获取任务列表
```http
GET /api/v1/tasks/list?status_filter=processing&limit=20&offset=0
```

#### 4. 取消任务
```http
POST /api/v1/tasks/cancel/{task_id}
```

#### 5. 重试任务
```http
POST /api/v1/tasks/retry/{log_id}
```

## 部署和启动

### 1. 环境要求
- Python 3.8+
- Redis 6.0+
- 外部工具：`tool_log_decompress`

### 2. 安装依赖
```bash
pip install -r requirements.txt
```

### 3. 配置环境变量
创建 `.env` 文件：
```env
# Redis配置
CELERY_BROKER_URL=redis://localhost:6379/0
CELERY_RESULT_BACKEND=redis://localhost:6379/0
REDIS_HOST=localhost
REDIS_PORT=6379
REDIS_DB=0

# 处理配置
LOG_PROCESSING_SPEED_MB_PER_SEC=100
MAX_RETRY_ATTEMPTS=3
TASK_TIMEOUT=3600
THREAD_NUM_FOR_DECOMPRESS=4
```

### 4. 数据库迁移
```bash
alembic upgrade head
```

### 5. 启动服务

#### 方式一：使用综合启动脚本（推荐）
```bash
./start_all.sh
```

#### 方式二：分别启动各个服务
```bash
# 启动Redis
./start_redis.sh

# 启动Celery Worker
./start_celery.sh

# 启动FastAPI应用
python -m uvicorn app.main:app --reload --host 0.0.0.0 --port 8085
```

## 使用示例

### 1. 上传协议栈日志
```bash
curl -X POST "http://localhost:8085/api/v1/logs/upload" \
  -H "Content-Type: multipart/form-data" \
  -F "file=@protocol_stack_log.tar.gz" \
  -F "log_type=stack"
```

### 2. 查询处理进度
```bash
# 使用返回的log_id查询状态
curl "http://localhost:8085/api/v1/tasks/log/{log_id}/status"
```

### 3. 监控任务列表
```bash
curl "http://localhost:8085/api/v1/tasks/list?status_filter=processing"
```

## 配置说明

### Celery配置
- **队列**：`log_processing`（专用队列）和 `default`（默认队列）
- **并发数**：默认4个worker进程
- **任务超时**：1小时
- **重试策略**：最多3次，指数退避（1分钟、2分钟、4分钟）

### 进度计算
```python
# 进度估算公式
elapsed_time = current_time - start_time
estimated_progress = min(
    (elapsed_time * processing_speed) / total_file_size * 100,
    95.0  # 最大95%，完成后设为100%
)
```

### 外部工具集成
系统调用外部工具进行日志处理：
```bash
tool_log_decompress [input_directory] [thread_count]
```

## 错误处理

### 常见错误类型
1. **文件解压失败**：检查文件格式和完整性
2. **外部工具调用失败**：确保 `tool_log_decompress` 已安装并在PATH中
3. **重打包失败**：检查磁盘空间和权限
4. **数据库连接失败**：检查数据库配置
5. **Redis连接失败**：确保Redis服务正在运行

### 重试机制
- 自动重试：最多3次
- 重试间隔：指数退避（1分钟、2分钟、4分钟）
- 手动重试：通过API接口触发

## 监控和日志

### 日志文件
- **应用日志**：`logs/app.log`
- **Celery日志**：`logs/celery_worker.log`
- **Redis日志**：`logs/redis.log`

### 监控指标
- 任务处理时间
- 成功/失败率
- 队列长度
- Worker状态

## 故障排除

### 1. 任务卡在pending状态
- 检查Celery worker是否运行
- 检查Redis连接
- 查看Celery日志

### 2. 处理失败
- 检查外部工具是否可用
- 查看错误日志
- 检查文件权限和磁盘空间

### 3. 进度不更新
- 检查数据库连接
- 查看任务日志
- 确认任务状态

## 性能优化

### 1. Celery优化
- 调整worker并发数
- 配置任务路由
- 使用专用队列

### 2. Redis优化
- 配置内存限制
- 启用持久化
- 监控连接数

### 3. 文件处理优化
- 使用SSD存储
- 调整线程数
- 优化临时目录位置

## 安全考虑

1. **文件验证**：上传文件类型和大小限制
2. **路径安全**：防止路径遍历攻击
3. **权限控制**：临时文件权限设置
4. **资源限制**：任务超时和内存限制
5. **日志安全**：避免敏感信息泄露