# Raven 包管理系统

> 该服务已纳入仓库根目录 `docker-compose.yml` 统一编排，请使用根目录 [QUICKSTART.md](../QUICKSTART.md) 中的 `scripts/docker-start.sh` 和 `scripts/docker-publish.sh`。本目录不再维护单独的 Compose/部署脚本。

一个现代化的包管理Web应用，用于管理和分发Galaxy Space升级包。

## 功能特性

- 📦 **包浏览与管理** - 查看所有已上传的升级包
- 🔍 **智能搜索** - 支持按包名称、版本号、类型等多维度搜索
- 📊 **详细信息** - 查看包的详细元数据和组件信息
- ⬆️ **文件上传** - 支持单个和批量上传.tgz/.tar.gz格式的包文件
- ⬇️ **快速下载** - 一键下载包文件
- 🗑️ **包管理** - 删除不需要的包文件
- 📈 **统计信息** - 实时显示包数量、总大小等统计数据
- 🎨 **现代化界面** - 响应式设计，支持移动端访问

## 支持的包类型

- LingXi-10
- LingXi-07A
- LingXi-06-TRD
- 配置包
- 其他自定义类型

## 快速开始

### 使用Docker部署（推荐）

1. **克隆项目**

   ```bash
   cd /path/to/package-server
   ```

2. **从仓库根目录启动统一 Docker 编排**

   ```bash
   cd ..
   ./scripts/docker-start.sh
   ```

3. **访问应用**
   - 直接端口：`http://localhost:8083`（保留旧版入口 `/api/*`）
   - 统一入口（容器内）：`/raven`，API 路径 `/raven/api/*`

### 使用Docker Compose

```bash
# 启动服务
cd ..
./scripts/docker-start.sh

# 查看日志
./scripts/docker-logs.sh package-server

# 停止服务
./scripts/docker-stop.sh
```

### 本地开发

1. **安装依赖**

   ```bash
   npm install
   ```

2. **启动开发服务器**

   ```bash
   npm run dev
   ```

3. **访问应用**
   打开浏览器访问: http://localhost:8083

## 项目结构

```
package-server/
├── src/
│   ├── index.js              # 主服务器文件
│   ├── routes/               # API路由
│   │   ├── packages.js       # 包管理路由
│   │   ├── upload.js         # 上传路由
│   │   └── download.js       # 下载路由
│   └── services/
│       └── PackageService.js # 包服务逻辑
├── public/                   # 前端静态文件
│   ├── index.html           # 主页面
│   └── app.js               # 前端JavaScript
├── scripts/                 # 部署脚本
│   ├── deploy.sh           # 部署脚本
│   ├── stop.sh             # 停止脚本
│   └── restart.sh          # 重启脚本
├── uploads/                 # 上传文件存储目录
├── data/                    # 数据存储目录
├── Dockerfile              # Docker配置
├── docker-compose.yml      # Docker Compose配置
└── package.json            # 项目配置
```

## API接口

### 包管理

- `GET /raven/api/packages`（兼容：`/api/packages`）- 获取包列表（支持搜索和分页）
- `GET /raven/api/packages/:id`（兼容：`/api/packages/:id`）- 获取包详情
- `DELETE /raven/api/packages/:id`（兼容：`/api/packages/:id`）- 删除包
- `GET /raven/api/packages/stats`（兼容：`/api/packages/stats`）- 获取统计信息

### 文件上传

- `POST /raven/api/upload`（兼容：`/api/upload`）- 单文件上传
- `POST /raven/api/upload/batch`（兼容：`/api/upload/batch`）- 批量文件上传

### 文件下载

- `GET /raven/api/download/:id`（兼容：`/api/download/:id`）- 下载单个包
- `POST /raven/api/download/batch`（兼容：`/api/download/batch`）- 批量下载（ZIP格式）

## 配置说明

### 环境变量

- `PORT` - 服务端口（默认: 8083）
- `NODE_ENV` - 运行环境（development/production）
- `UPLOAD_DIR` - 上传文件存储目录
- `DATA_DIR` - 数据存储目录
- `MAX_FILE_SIZE` - 最大文件大小限制
- `ALLOWED_ORIGINS` - 允许的跨域来源

### 文件格式支持

- 支持的文件格式: `.tgz`, `.tar.gz`
- 最大文件大小: 500MB
- 文件命名规范: `ProductName-Version-Date-Components.tgz`

## 管理脚本

### 启动

```bash
../scripts/docker-start.sh
```

### 停止服务

```bash
../scripts/docker-stop.sh
```

### 重启服务

```bash
../scripts/docker-restart.sh
```

## 故障排除

### 查看日志

```bash
# Docker容器日志
docker logs galaxy-package-server

# 实时日志
docker logs -f galaxy-package-server
```

### 常见问题

1. **端口被占用**
   - 检查端口8083是否被其他服务占用
   - 修改docker-compose.yml中的端口映射

2. **文件上传失败**
   - 检查文件格式是否为.tgz或.tar.gz
   - 确认文件大小不超过500MB限制
   - 检查uploads目录权限

3. **容器启动失败**
   - 检查Docker是否正常运行
   - 查看容器日志排查具体错误
   - 确认所需端口未被占用

## 技术栈

- **后端**: Node.js + Express
- **前端**: HTML5 + Bootstrap 5 + Vanilla JavaScript
- **容器化**: Docker + Docker Compose
- **文件处理**: Multer + tar
- **安全**: Helmet + CORS + Rate Limiting

## 许可证

本项目为内部使用项目，版权归Galaxy Space所有。

## 支持

如有问题或建议，请联系开发团队。
