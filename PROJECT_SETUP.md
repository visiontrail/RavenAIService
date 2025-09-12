# 日志暂存服务 - 项目基础架构

## 📋 项目概述

这是一个基于FastAPI的日志暂存服务，用于临时存储和管理日志文件。项目采用现代Python架构，支持环境配置、CORS、文件大小限制等功能。

## 🏗️ 项目结构

```
log-staging-service/
├── app/                    # 主应用目录
│   ├── api/               # API路由
│   │   ├── __init__.py
│   │   └── health.py      # 健康检查端点
│   ├── models/            # 数据模型
│   │   ├── __init__.py
│   │   └── base.py        # 基础模型
│   ├── services/          # 业务服务
│   │   ├── __init__.py
│   │   └── base.py        # 基础服务类
│   ├── utils/             # 工具函数
│   │   ├── __init__.py
│   │   └── file_utils.py  # 文件操作工具
│   ├── __init__.py
│   ├── config.py          # 配置文件
│   └── main.py            # 应用入口
├── frontend/              # 前端目录（预留）
├── logs/                  # 日志存储目录
│   ├── .gitkeep
│   └── app.log           # 应用日志文件
├── temp/                  # 临时文件目录
│   └── .gitkeep
├── venv/                  # Python虚拟环境
├── docs/                  # 文档目录
├── .env.template          # 环境变量模板
├── .gitignore            # Git忽略文件
├── requirements.txt       # Python依赖
├── start.sh              # 启动脚本
└── PROJECT_SETUP.md      # 本文档
```

## 🚀 快速启动

### 方法1: 使用启动脚本（推荐）

```bash
# 给脚本执行权限（如果还没有）
chmod +x start.sh

# 运行启动脚本
./start.sh
```

启动脚本会自动完成以下操作：
- 检查并创建虚拟环境
- 安装所需依赖包
- 创建必要目录
- 复制环境变量文件（如需要）
- 启动FastAPI应用

### 方法2: 手动启动

```bash
# 1. 创建虚拟环境
python3 -m venv venv

# 2. 激活虚拟环境
source venv/bin/activate

# 3. 安装依赖
pip install fastapi uvicorn python-dotenv psutil pydantic pydantic-settings starlette python-multipart click h11 --upgrade --prefer-binary

# 4. 创建环境文件
cp .env.template .env

# 5. 启动应用
uvicorn app.main:app --host 0.0.0.0 --port 8085 --reload
```

## 🔗 访问地址

服务启动后，可以通过以下地址访问：

- **主页**: http://localhost:8085
- **API文档 (Swagger)**: http://localhost:8085/docs
- **API文档 (ReDoc)**: http://localhost:8085/redoc
- **健康检查**: http://localhost:8085/health

## 📝 健康检查示例

```bash
curl http://localhost:8085/health
```

响应示例：
```json
{
  "status": "healthy",
  "timestamp": "2025-09-12T17:08:20.299322",
  "version": "1.0.0",
  "environment": "development",
  "system_info": {
    "cpu_percent": 5.2,
    "memory_percent": 45.3,
    "disk_usage": {
      "total": 245107195904,
      "used": 11635646464,
      "free": 6368976896,
      "percent": 64.6
    },
    "directories": {
      "logs_dir": true,
      "temp_dir": true
    }
  }
}
```

## ⚙️ 配置说明

### 环境变量配置

复制 `.env.template` 为 `.env` 并根据需要修改：

```bash
# 环境配置
ENVIRONMENT=development  # development/production

# 服务配置
HOST=0.0.0.0
PORT=8085

# 日志配置
LOG_LEVEL=INFO          # DEBUG/INFO/WARNING/ERROR
LOG_FILE_PATH=logs/app.log

# 文件配置
MAX_FILE_SIZE=1073741824  # 1GB in bytes
TEMP_DIR=temp
LOGS_DIR=logs

# CORS配置
CORS_ORIGINS=*
CORS_CREDENTIALS=true
CORS_METHODS=*
CORS_HEADERS=*

# 安全配置
SECRET_KEY=your-secret-key-here
```

### 开发环境 vs 生产环境

- **开发环境**: 
  - 启用API文档 (`/docs`, `/redoc`)
  - 日志级别：DEBUG
  - 允许所有CORS源

- **生产环境**:
  - 禁用API文档
  - 日志级别：WARNING
  - 需要配置具体的CORS源

## 🛠️ 开发指南

### 添加新的API端点

1. 在 `app/api/` 目录下创建新的路由文件
2. 在 `app/main.py` 中注册路由：

```python
from app.api import your_new_router
app.include_router(your_new_router.router, prefix="/api/v1", tags=["标签"])
```

### 添加新的数据模型

在 `app/models/` 目录下创建新的模型文件，继承 `BaseModel`：

```python
from pydantic import BaseModel
from app.models.base import BaseResponse

class YourModel(BaseModel):
    field1: str
    field2: int

class YourResponse(BaseResponse):
    data: YourModel
```

### 添加新的业务服务

在 `app/services/` 目录下创建新的服务文件，继承 `BaseService`：

```python
from app.services.base import BaseService

class YourService(BaseService):
    def your_method(self):
        self.log_info("执行某个操作")
        # 业务逻辑
```

## 📦 依赖包说明

- **fastapi**: Web框架
- **uvicorn**: ASGI服务器
- **pydantic**: 数据验证和序列化
- **pydantic-settings**: 配置管理
- **python-dotenv**: 环境变量加载
- **psutil**: 系统信息获取
- **starlette**: FastAPI底层框架
- **python-multipart**: 文件上传支持

## 🔧 常见问题

### 1. 虚拟环境问题
如果遇到虚拟环境相关问题，删除 `venv` 目录重新创建：
```bash
rm -rf venv
python3 -m venv venv
source venv/bin/activate
```

### 2. 依赖安装问题
如果遇到依赖安装问题，尝试升级pip：
```bash
pip install --upgrade pip
```

### 3. 端口占用
如果8000端口被占用，修改 `.env` 文件中的 `PORT` 值或使用其他端口启动：
```bash
uvicorn app.main:app --port 8001
```

## 📋 待开发功能

基础架构已完成，后续可以基于此架构开发：

1. 日志文件上传API
2. 日志文件管理API
3. 日志文件搜索和查询
4. 用户认证和权限管理
5. 文件清理和归档功能
6. 前端界面开发

## 🤝 贡献指南

1. Fork 项目
2. 创建功能分支
3. 提交更改
4. 推送到分支
5. 创建 Pull Request

## 📄 许可证

本项目采用 MIT 许可证。
