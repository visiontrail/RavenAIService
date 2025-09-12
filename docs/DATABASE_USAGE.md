# 数据库模型使用说明

## 概述

本项目实现了完整的数据库模型设计，支持SQLite（开发环境）和PostgreSQL（生产环境），使用SQLAlchemy ORM和Alembic进行数据库迁移管理。

## 数据库模型

### LogRecord 模型

日志记录的核心数据库模型，包含以下字段：

- `id`: 主键，UUID类型
- `filename`: 存储文件名
- `original_filename`: 原始文件名
- `file_size`: 文件大小（字节）
- `file_path`: 文件存储路径
- `log_type`: 日志类型（stack/oam_antenna）
- `status`: 处理状态（pending/processing/completed/failed）
- `progress`: 处理进度（0-100）
- `created_at`: 创建时间
- `updated_at`: 更新时间
- `processed_at`: 处理完成时间
- `checksum`: 文件校验和
- `mime_type`: MIME类型
- `log_level`: 日志级别
- `metadata_json`: 元数据（JSON格式）
- `error_message`: 错误信息

## 数据库配置

### 环境变量配置

可以通过以下环境变量配置数据库连接：

```bash
# 数据库配置
DATABASE_URL=sqlite+aiosqlite:///logs.db  # 或 PostgreSQL URL
DATABASE_ECHO=false
DATABASE_POOL_SIZE=5
DATABASE_MAX_OVERFLOW=10
DATABASE_POOL_TIMEOUT=30
DATABASE_POOL_RECYCLE=3600

# SQLite配置（开发环境）
SQLITE_FILE=logs.db

# PostgreSQL配置（生产环境）
POSTGRES_HOST=localhost
POSTGRES_PORT=5432
POSTGRES_DB=log_staging
POSTGRES_USER=postgres
POSTGRES_PASSWORD=password
```

## 数据库初始化

### 1. 使用管理脚本

```bash
# 完整设置（推荐）
python manage_db.py setup

# 或分步执行
python manage_db.py init      # 初始化数据库
python manage_db.py check     # 检查连接
python manage_db.py info      # 查看配置信息
```

### 2. 手动初始化

```python
from app.database import init_database

# 异步初始化
await init_database()
```

## Alembic 迁移管理

### 创建迁移

```bash
# 生成迁移文件
python manage_db.py make-migration

# 或直接使用alembic
alembic revision --autogenerate -m "描述信息"
```

### 应用迁移

```bash
# 应用迁移
python manage_db.py migrate

# 或直接使用alembic
alembic upgrade head
```

### 其他迁移命令

```bash
# 查看迁移历史
alembic history

# 回滚到特定版本
alembic downgrade <revision>

# 查看当前版本
alembic current
```

## CRUD 操作示例

### 基础使用

```python
from app.models.database import get_db
from app.services.log_service import log_service
from app.models.log import LogStatus, LogType, LogLevel

# 获取数据库会话
async for db in get_db():
    # 创建日志记录
    log_record = await log_service.create(
        db=db,
        filename="test.log",
        original_filename="application.log",
        file_size=1024,
        file_path="/path/to/file",
        log_type=LogType.STACK,
        status=LogStatus.PENDING
    )
    
    # 查询日志记录
    log_record = await log_service.get_by_id(db, "log_id")
    
    # 更新状态
    await log_service.update_log_status(
        db=db,
        log_id="log_id",
        status=LogStatus.COMPLETED,
        progress=100.0
    )
    
    # 删除日志记录
    await log_service.delete_log(db, "log_id")
```

### 列表查询

```python
from app.models.log import LogListRequest

# 创建查询请求
request = LogListRequest(
    page=1,
    size=10,
    log_type=LogType.STACK,
    status=LogStatus.COMPLETED
)

# 获取列表
logs, total = await log_service.get_log_list(db, request)
```

## 数据验证

项目使用Pydantic模型进行数据验证：

- `LogFileInfo`: API响应模型
- `LogUploadRequest`: 上传请求模型
- `LogListRequest`: 列表查询模型
- `BatchDeleteRequest`: 批量删除请求模型
- `BatchDownloadRequest`: 批量下载请求模型

## 错误处理

数据库操作中的常见错误：

- `FileNotFoundError`: 文件或记录不存在
- `StorageError`: 存储操作失败
- `FileUploadError`: 文件上传失败
- `BatchOperationError`: 批量操作失败

## 性能优化建议

1. **索引优化**: 在高频查询字段上创建索引
2. **连接池**: 合理配置数据库连接池大小
3. **批量操作**: 使用批量插入/更新减少数据库往返
4. **分页查询**: 大数据量查询时使用分页
5. **异步操作**: 充分利用异步数据库操作

## 监控和维护

1. **日志监控**: 监控数据库操作日志
2. **性能监控**: 监控查询执行时间
3. **定期清理**: 定期清理过期日志记录
4. **备份策略**: 制定数据库备份和恢复策略

## 故障排除

### 常见问题

1. **连接失败**
   - 检查数据库服务是否运行
   - 验证连接参数
   - 检查网络连接

2. **迁移失败**
   - 检查数据库权限
   - 验证模型定义
   - 查看详细错误日志

3. **性能问题**
   - 检查索引使用情况
   - 优化查询语句
   - 调整连接池配置

### 调试工具

```bash
# 启用SQL日志
DATABASE_ECHO=true

# 检查数据库状态
python manage_db.py check

# 查看配置信息
python manage_db.py info
```
