# 数据库与存储架构使用说明

## 概述

本项目采用**混合存储架构**，根据数据特性选择最合适的存储方式：

- **SQL数据库**：用户信息、会话历史、日志元数据（支持SQLite/PostgreSQL）
- **文件系统**：日志文件、重构包文件（Docker Volume持久化）
- **JSON文件**：重构包元数据（内存Map加速）
- **向量数据库**：FAISS向量索引（支持智能语义搜索）
- **Redis缓存**：任务队列和结果缓存

本文档详细说明SQL数据库部分的使用方法和最佳实践。

## 数据位置速查表

| 数据类型 | 存储方式 | 存储位置 | 代码文件 | 说明 |
|---------|---------|---------|---------|------|
| **用户账户** | SQL数据库 | `users` 表 | [app/models/user.py](../app/models/user.py) | 用户名、密码、邮箱等基础信息 |
| **聊天会话** | SQL数据库 | `chat_sessions` 表 | [app/models/user.py](../app/models/user.py) | 会话标题、最近消息时间、消息数量 |
| **聊天消息** | SQL数据库 | `chat_messages` 表 | [app/models/user.py](../app/models/user.py) | 用户和AI的完整对话内容 |
| **日志元数据** | SQL数据库 | `log_records` 表 | [app/models/log.py](../app/models/log.py) | 文件名、大小、类型、处理状态等 |
| **日志文件** | 文件系统 | `/app/logs/` | Docker Volume `app_logs` | 实际的日志文件内容（.tar.gz等） |
| **临时文件** | 文件系统 | `/app/temp/` | Docker Volume `app_temp` | 解压缩、处理过程中的临时文件 |
| **SQLite数据库** | 文件系统 | `/app/data/logs.db` | Docker Volume `app_data` | 开发环境和Docker默认数据库文件 |
| **重构包文件** | 文件系统 | `package-server/uploads/` | 本地目录（非Docker Volume） | 实际的重构包文件（.bin等） |
| **重构包元数据** | JSON文件 | `package-server/data/package-metadata.json` | [package-server/src/services/PackageService.js](../package-server/src/services/PackageService.js) | 重构包名称、版本、描述等元信息 |
| **向量索引** | FAISS文件 | `package-server/data/vector-store/*.faiss` | [package-server/src/services/IntelligentSearchService.js](../package-server/src/services/IntelligentSearchService.js) | 用于智能语义搜索的向量数据 |
| **向量文档** | JSON文件 | `package-server/data/vector-store/docstore.json` | [package-server/src/services/IntelligentSearchService.js](../package-server/src/services/IntelligentSearchService.js) | 向量对应的文档内容 |
| **Celery任务队列** | Redis | Redis DB 0 | Celery配置 | 异步任务队列 |
| **Celery任务结果** | Redis | Redis DB 0 | Celery配置 | 任务执行结果缓存 |

### Docker部署数据位置

使用 `deploy.sh` 部署的Docker环境中：

```bash
# 进入容器
docker exec -it raven-app-1 sh

# 数据库文件位置
/app/data/logs.db

# 日志文件位置
/app/logs/

# 临时文件位置
/app/temp/

# 查看卷挂载
docker volume ls | grep raven
docker volume inspect raven_app_data
```

## SQL数据库模型详解

### User 模型（用户账户）

定义位置：[app/models/user.py](../app/models/user.py)

```python
class User(Base, TimestampMixin):
    __tablename__ = "users"

    id: str                          # 用户ID（UUID）
    username: str                    # 用户名（唯一）
    display_name: str | None         # 显示名称
    email: str | None                # 邮箱
    password_hash: str               # 密码哈希
    is_active: bool                  # 是否启用
    last_login_at: datetime | None   # 最后登录时间
    created_at: datetime             # 创建时间
    updated_at: datetime             # 更新时间
```

### ChatSession 模型（聊天会话）

定义位置：[app/models/user.py](../app/models/user.py)

```python
class ChatSession(Base, TimestampMixin):
    __tablename__ = "chat_sessions"

    id: str                          # 会话ID（UUID）
    user_id: str                     # 所属用户ID（外键）
    title: str                       # 会话标题
    last_message_at: datetime        # 最近消息时间
    message_count: int               # 消息数量
    is_deleted: bool                 # 是否已删除（软删除）
    created_at: datetime             # 创建时间
    updated_at: datetime             # 更新时间
```

### ChatMessage 模型（聊天消息）

定义位置：[app/models/user.py](../app/models/user.py)

```python
class ChatMessage(Base, TimestampMixin):
    __tablename__ = "chat_messages"

    id: str                          # 消息ID（UUID）
    session_id: str                  # 所属会话ID（外键）
    role: str                        # 角色（user/ai/system）
    content: str                     # 消息内容（文本）
    created_at: datetime             # 创建时间
    updated_at: datetime             # 更新时间
```

### LogRecord 模型（日志元数据）

定义位置：[app/models/log.py](../app/models/log.py)

日志记录的核心数据库模型，包含以下字段：

- `id`: 主键，UUID类型
- `filename`: 存储文件名
- `original_filename`: 原始文件名
- `file_size`: 文件大小（字节）
- `file_path`: 文件存储路径
- `log_type`: 日志类型（stack/oam_antenna/full）
- `status`: 处理状态（pending/processing/completed/failed）
- `progress`: 处理进度（0-100）
- `download_count`: 下载次数
- `task_id`: Celery任务ID
- `retry_count`: 重试次数
- `processing_started_at`: 处理开始时间
- `created_at`: 创建时间
- `updated_at`: 更新时间
- `processed_at`: 处理完成时间
- `checksum`: 文件校验和
- `mime_type`: MIME类型
- `log_level`: 日志级别
- `metadata_json`: 元数据（JSON格式）
- `error_message`: 错误信息
- `issue_description`: 问题描述
- `is_deleted`: 是否已删除（软删除）
- `deleted_at`: 删除时间

### 表关系图

```
users (用户表)
  ├─ id (PK)
  └─ chat_sessions (一对多)
       ├─ id (PK)
       ├─ user_id (FK → users.id)
       └─ chat_messages (一对多)
            ├─ id (PK)
            ├─ session_id (FK → chat_sessions.id)
            ├─ role
            └─ content

log_records (日志元数据表)
  ├─ id (PK)
  ├─ filename
  ├─ file_path (→ 指向文件系统中的实际文件)
  └─ status
```

## 混合存储架构详解

### 为什么使用混合存储？

| 存储类型 | 适用场景 | 优势 | 劣势 |
|---------|---------|------|------|
| **SQL数据库** | 结构化数据、关系查询、事务操作 | 事务保证、关系查询、数据完整性 | 不适合大文件、存储成本高 |
| **文件系统** | 大文件、二进制数据 | 存储成本低、读写快速 | 无关系查询、无事务保证 |
| **JSON文件** | 配置数据、元数据 | 易读易写、快速加载到内存 | 无索引、无并发控制 |
| **向量数据库** | 语义搜索、相似度查询 | 智能搜索、支持多语言 | 需要额外维护、重建成本高 |
| **Redis** | 临时数据、缓存、队列 | 高性能、支持过期 | 内存限制、数据不持久 |

### 典型数据流示例

#### 示例1：日志上传与处理

```
1. 用户上传日志文件（协议栈日志 .tar.gz）
   ↓
2. 文件保存到文件系统：/app/logs/abc123.tar.gz
   ↓
3. 创建SQL记录：log_records表（存储元数据和文件路径）
   {
     "id": "abc123",
     "filename": "abc123.tar.gz",
     "file_path": "/app/logs/abc123.tar.gz",
     "status": "pending",
     "log_type": "stack"
   }
   ↓
4. 创建Celery异步任务（存储到Redis队列）
   task_id: "celery-task-xyz"
   ↓
5. Worker处理：解压到 /app/temp/abc123/
   ↓
6. 更新SQL记录：status = "completed", progress = 100
   ↓
7. 用户下载时：从 file_path 读取文件系统中的文件
```

#### 示例2：重构包上传与搜索

```
1. 用户上传重构包文件（.bin）
   ↓
2. 文件保存到：package-server/uploads/pkg-xyz.bin
   ↓
3. 元数据写入JSON：package-server/data/package-metadata.json
   {
     "id": "pkg-xyz",
     "name": "无线配置v3.2",
     "file_path": "uploads/pkg-xyz.bin"
   }
   ↓
4. 加载到内存Map：PackageService.packages.set("pkg-xyz", {...})
   ↓
5. 构建向量索引：
   - 使用LangChain + FAISS
   - 保存到 vector-store/index.faiss
   - 文档保存到 vector-store/docstore.json
   ↓
6. 用户搜索"无线配置"时：
   a. 向量检索：在FAISS中查找相似向量
   b. 获取匹配ID
   c. 从内存Map中读取完整元数据
   d. 返回搜索结果
```

#### 示例3：AI聊天会话保存（新增功能）

```
1. 用户在AI聊天界面发送消息："帮我分析这个日志"
   ↓
2. 前端调用后端API：POST /api/v1/ai/chat
   payload: {
     "content": "帮我分析这个日志",
     "session_id": "session-123",
     "history": []  # 登录用户为空
   }
   ↓
3. 后端加载历史记录（三级策略）：
   a. 优先从SQL查询：chat_messages表（session_id = "session-123"）
   b. 如未登录，使用前端传入的history
   c. 最后从服务器内存缓存读取
   ↓
4. 构建完整上下文，发送给LLM
   ↓
5. 获得AI回复："这是一个网络超时错误..."
   ↓
6. 保存对话到数据库：
   - 创建/更新 chat_sessions 记录
   - 插入两条 chat_messages 记录：
     * role="user", content="帮我分析这个日志"
     * role="ai", content="这是一个网络超时错误..."
   ↓
7. 返回给前端，显示AI回复
   ↓
8. 下次对话时，完整历史可从SQL加载
```

#### 示例4：重构包配置管理员对话保存（新增功能）

```
1. 用户在AI聊天界面输入："请帮我找支持5G的重构包"
   ↓
2. 前端检测到"重构包"关键词，调用PackageAgent
   ↓
3. PackageAgent执行智能搜索：
   - 调用FAISS向量检索
   - 找到6个匹配的重构包
   - 格式化为Markdown回复
   ↓
4. 前端保存对话到数据库（新增逻辑）：
   - 如果没有session_id，创建新的UUID
   - 调用 POST /api/v1/users/chat-sessions/{session_id}/messages
   - 传入：
     * user_content: "请帮我找支持5G的重构包"
     * ai_content: "找到以下重构包..."
     * title_hint: "请帮我找支持5G的重构包"
   ↓
5. 后端保存：
   - 创建/更新 chat_sessions（标题自动生成）
   - 插入两条 chat_messages 记录
   ↓
6. 刷新会话列表，用户可在历史中看到此对话
   ↓
7. 下次对话时，PackageAgent的上下文也会加载到LLM
```

## 数据库配置

### 环境变量配置

可以通过以下环境变量配置数据库连接：

```bash
# 数据库配置
DATABASE_URL=sqlite+aiosqlite:///data/logs.db  # 或 PostgreSQL URL
DATABASE_ECHO=false
DATABASE_POOL_SIZE=5
DATABASE_MAX_OVERFLOW=10
DATABASE_POOL_TIMEOUT=30
DATABASE_POOL_RECYCLE=3600

# SQLite配置（开发环境）
SQLITE_FILE=data/logs.db

# PostgreSQL配置（生产环境）
POSTGRES_HOST=localhost
POSTGRES_PORT=5432
POSTGRES_DB=log_staging
POSTGRES_USER=postgres
POSTGRES_PASSWORD=password
```

### Docker环境数据库类型

使用 `deploy.sh` 脚本部署的Docker服务**默认使用SQLite**，原因如下：

1. `.env.example` 中设置 `ENVIRONMENT=development`
2. `app/config.py` 根据环境变量选择数据库：
   - `development` → SQLite (`data/logs.db`)
   - `production` → PostgreSQL

### 在Docker中查询数据库

#### 方法1：使用SQLite CLI（推荐）

```bash
# 进入容器
docker exec -it raven-app-1 sh

# 使用sqlite3命令（如果容器中已安装）
sqlite3 /app/data/logs.db

# SQLite命令示例
.tables                    # 查看所有表
.schema users              # 查看表结构
SELECT * FROM users;       # 查询用户
SELECT * FROM chat_sessions WHERE user_id='xxx';  # 查询会话
SELECT * FROM chat_messages WHERE session_id='xxx' ORDER BY created_at;  # 查询消息
.quit                      # 退出
```

#### 方法2：使用Python脚本

```bash
# 在容器中执行Python脚本
docker exec -it raven-app-1 python3 -c "
import sqlite3
conn = sqlite3.connect('/app/data/logs.db')
cursor = conn.cursor()
cursor.execute('SELECT * FROM users')
for row in cursor.fetchall():
    print(row)
conn.close()
"
```

#### 方法3：复制数据库文件到本地

```bash
# 复制数据库文件到本地
docker cp raven-app-1:/app/data/logs.db ./logs.db

# 使用本地SQLite工具查看（如DB Browser for SQLite）
# macOS安装: brew install --cask db-browser-for-sqlite
# Windows: 从官网下载 https://sqlitebrowser.org/
```

#### 方法4：使用Docker Volume直接访问

```bash
# 查看volume位置
docker volume inspect raven_app_data

# 输出示例：
# "Mountpoint": "/var/lib/docker/volumes/raven_app_data/_data"

# 直接访问（需要root权限）
sudo ls -la /var/lib/docker/volumes/raven_app_data/_data/
sudo sqlite3 /var/lib/docker/volumes/raven_app_data/_data/logs.db
```

### 常用SQL查询示例

```sql
-- 查看所有用户
SELECT id, username, email, is_active, created_at FROM users;

-- 查看某个用户的所有会话
SELECT id, title, message_count, last_message_at
FROM chat_sessions
WHERE user_id='your-user-id' AND is_deleted=0
ORDER BY last_message_at DESC;

-- 查看某个会话的所有消息
SELECT role, content, created_at
FROM chat_messages
WHERE session_id='your-session-id'
ORDER BY created_at ASC;

-- 查看所有日志记录（包含处理状态）
SELECT id, original_filename, log_type, status, progress, created_at
FROM log_records
WHERE is_deleted=0
ORDER BY created_at DESC
LIMIT 20;

-- 统计每个用户的会话数量
SELECT u.username, COUNT(cs.id) as session_count
FROM users u
LEFT JOIN chat_sessions cs ON u.id = cs.user_id
WHERE cs.is_deleted=0
GROUP BY u.id, u.username;

-- 查找某个重构包相关的对话
SELECT cm.role, cm.content, cm.created_at
FROM chat_messages cm
WHERE cm.content LIKE '%重构包%'
ORDER BY cm.created_at DESC
LIMIT 10;
```

### SQLite vs PostgreSQL 对比

| 特性 | SQLite | PostgreSQL |
|-----|--------|------------|
| **部署方式** | 单文件，无需服务器 | 需要独立数据库服务器 |
| **并发性** | 读并发好，写并发差 | 读写并发都很好 |
| **适用场景** | 开发、测试、小规模部署 | 生产环境、大规模部署 |
| **事务支持** | 支持，但有限制 | 完整ACID支持 |
| **性能** | 小数据量快，大数据量慢 | 大数据量性能优秀 |
| **备份** | 直接复制文件 | 需要pg_dump工具 |
| **维护成本** | 几乎无需维护 | 需要定期维护 |
| **数据大小限制** | 建议 < 1GB | 无明显限制 |
| **连接数** | 同时只能一个写连接 | 支持大量并发连接 |

**选择建议**：
- **开发/测试环境**：使用SQLite（当前Docker默认）
- **生产环境**：建议切换到PostgreSQL
- **小团队/低流量**：SQLite足够
- **大团队/高并发**：必须使用PostgreSQL

## 数据库初始化

### 1. 使用管理脚本

```bash
# 完整设置（推荐）
python scripts/manage-db.py setup

# 或分步执行
python scripts/manage-db.py init      # 初始化数据库
python scripts/manage-db.py check     # 检查连接
python scripts/manage-db.py info      # 查看配置信息
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
python scripts/manage-db.py make-migration

# 或直接使用alembic
alembic revision --autogenerate -m "描述信息"
```

### 应用迁移

```bash
# 应用迁移
python scripts/manage-db.py migrate

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


## 数据迁移到生产环境

### 从SQLite迁移到PostgreSQL

```bash
# 1. 备份SQLite数据库
docker cp raven-app-1:/app/data/logs.db ./logs_backup.db

# 2. 修改环境变量（生产环境）
ENVIRONMENT=production
POSTGRES_HOST=your-postgres-host
POSTGRES_PORT=5432
POSTGRES_DB=raven_production
POSTGRES_USER=raven_user
POSTGRES_PASSWORD=your-secure-password

# 3. 初始化PostgreSQL表结构
python scripts/manage-db.py migrate

# 4. 数据迁移（需要自定义脚本）
python scripts/migrate_sqlite_to_postgres.py

# 5. 验证数据完整性
python scripts/verify_migration.py
```

## 常见问题

### Q1: 如何备份数据库？

**SQLite**:
```bash
# 复制数据库文件
docker cp raven-app-1:/app/data/logs.db ./backup/logs_$(date +%Y%m%d).db

# 或使用SQLite内置命令
sqlite3 /app/data/logs.db ".backup '/backup/logs.db'"
```

**PostgreSQL**:
```bash
# 使用pg_dump
pg_dump -h localhost -U raven_user raven_production > backup.sql

# 恢复
psql -h localhost -U raven_user raven_production < backup.sql
```

### Q2: 如何清理过期数据？

```sql
-- 软删除30天前的日志记录
UPDATE log_records
SET is_deleted = 1, deleted_at = CURRENT_TIMESTAMP
WHERE created_at < datetime('now', '-30 days')
  AND is_deleted = 0;

-- 物理删除90天前的软删除记录
DELETE FROM log_records
WHERE is_deleted = 1
  AND deleted_at < datetime('now', '-90 days');
```


## 相关文档

- [SQLAlchemy 2.0 文档](https://docs.sqlalchemy.org/en/20/)
- [FastAPI 数据库文档](https://fastapi.tiangolo.com/tutorial/sql-databases/)
- [Alembic 迁移文档](https://alembic.sqlalchemy.org/)
- [SQLite 文档](https://www.sqlite.org/docs.html)
- [PostgreSQL 文档](https://www.postgresql.org/docs/)
