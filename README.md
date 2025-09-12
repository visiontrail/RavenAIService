# 日志暂存服务 | Log Staging Service

[English](README_EN.md) | 中文

## 项目简介

日志暂存服务是一个基于 FastAPI 的现代化 HTTP 服务，用于临时存储和管理日志文件。本项目采用模块化架构设计，支持环境配置、CORS、文件大小限制等功能。

## 当前状态

✅ **基础架构已完成** - 项目采用FastAPI框架，具备以下特性：
- 模块化项目结构
- 环境配置管理（开发/生产环境切换）
- 健康检查端点
- 日志记录系统
- CORS 支持
- 文件大小限制（1GB）

🚧 **业务功能开发中** - 后续将实现完整的日志上传、处理、下载和管理功能。

## 核心功能

### 📤 日志上传
- 支持通过 PUT/POST 方法上传 tar.gz 格式的日志包
- 智能识别日志类型并进行相应处理

### 📋 日志管理
- 直观的 Web 界面显示日志列表
- 支持批量选择和操作（删除、下载）
- 实时显示文件信息（名称、大小、创建时间）
- 智能标签系统（协议栈日志、OAM与天线日志）

### 🔄 协议栈日志处理
- 自动识别包含"stack"关键字的日志包
- 调用专用工具解压私有压缩格式的协议栈日志
- 异步处理，实时显示处理进度
- 生成人类可读的文本格式日志

### 📊 日志详情
- 独立的日志详情页面，支持 URL 分享
- 预留 AI 分析功能接口
- 完整的日志元数据展示

### 🗂️ 自动清理
- 智能存储管理：默认保留1个月的日志
- 空间不足时自动清理：仅保留最近1周的日志
- 磁盘空间阈值：100GB

## 技术特性

- 🐳 **Docker 容器化**：提供完整的 Docker 部署方案
- 🎨 **现代 UI**：简洁美观的 Web 界面
- ⚡ **异步处理**：大文件处理不阻塞用户操作
- 🔧 **快速部署**：提供 deploy.sh、restart.sh、stop.sh 脚本

## 快速开始

### 方法1: 使用启动脚本（推荐）

```bash
# 给脚本执行权限
chmod +x start.sh

# 运行启动脚本
./start.sh
```

### 方法2: 手动部署

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

## 访问地址

- **主页**: http://localhost:8085
- **API文档 (Swagger)**: http://localhost:8085/docs
- **健康检查**: http://localhost:8085/health

## 系统要求

- Python 3.8+
- 磁盘空间：推荐至少 10GB 可用空间
- 网络连接（用于安装依赖包）

## 配置说明

主要配置项：
- 日志存储路径
- 处理线程数（默认14）
- 自动清理策略
- 服务端口配置

## 当前可用的API接口

### 健康检查
```http
GET /health
```

返回服务状态、系统信息等。

示例响应：
```json
{
  "status": "healthy",
  "timestamp": "2025-09-12T17:08:20.299322",
  "version": "1.0.0",
  "environment": "development",
  "system_info": {
    "cpu_percent": 5.2,
    "memory_percent": 45.3,
    "disk_usage": {...},
    "directories": {...}
  }
}
```

## 项目结构

```
log-staging-service/
├── app/                    # 主应用目录
│   ├── api/               # API路由
│   ├── models/            # 数据模型
│   ├── services/          # 业务服务
│   ├── utils/             # 工具函数
│   ├── config.py          # 配置文件
│   └── main.py            # 应用入口
├── frontend/              # 前端目录（预留）
├── logs/                  # 日志存储目录
├── temp/                  # 临时文件目录
├── venv/                  # Python虚拟环境
├── .env.template          # 环境变量模板
├── requirements.txt       # Python依赖
├── start.sh              # 启动脚本
└── PROJECT_SETUP.md      # 详细设置文档
```

查看 [PROJECT_SETUP.md](PROJECT_SETUP.md) 获取详细的开发和配置说明。

## 贡献指南

欢迎提交 Issue 和 Pull Request 来改进这个项目。

## 许可证

[许可证信息]

## 联系方式

[联系信息]
