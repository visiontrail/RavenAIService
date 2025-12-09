# 生产环境 Docker 部署指南

## 🚨 重要变更说明

由于新增了 RAG 智能搜索功能，Dockerfile 已更新：

### 主要变更
1. ✅ **基础镜像**: `node:18-alpine` → `node:18` (完整版)
   - 原因: `faiss-node` 需要编译，需要完整的构建工具链

2. ✅ **系统依赖**: 新增 `python3, make, g++, cmake`
   - 原因: 编译原生 Node.js 模块需要

3. ✅ **模型预加载**: 可选在构建时预下载嵌入模型
   - 好处: 减少首次启动时间
   - 缺点: 增加镜像大小约 100MB

4. ✅ **健康检查**: 启动等待时间增加到 60 秒
   - 原因: 首次启动需要加载 AI 模型

## 📦 部署准备

### 1. 检查依赖变更

新增的依赖包：
```json
{
  "langchain": "^0.1.0",
  "@langchain/openai": "^0.0.14",
  "@langchain/community": "^0.0.20",
  "faiss-node": "^0.5.1",
  "@xenova/transformers": "^2.17.2"
}
```

### 2. 镜像大小变化

- **旧版本**: ~150MB (Alpine 基础)
- **新版本**: ~1.2GB (完整版 + AI 模型)

如果存储空间受限，可以：
- 删除 Dockerfile 中的模型预加载行
- 首次启动时会自动下载（需要网络访问 HuggingFace）

## 🚀 部署方式

### 方式一：使用 Docker Compose（推荐）

#### 首次部署

```bash
# 1. 进入项目目录
cd /path/to/package-server

# 2. 使用 Docker Compose 构建和启动
docker-compose up -d --build

# 3. 查看日志
docker-compose logs -f

# 4. 检查服务状态
curl http://localhost:8083/health
curl http://localhost:8083/api/search/status
```

#### 重启服务（代码更新后）

```bash
# 使用提供的重启脚本
./scripts/restart.sh

# 或手动执行
docker-compose down
docker-compose build --no-cache
docker-compose up -d
```

### 方式二：使用 Docker 命令

#### 首次部署

```bash
# 1. 进入项目目录
cd /path/to/package-server

# 2. 构建镜像
docker build -t galaxy-package-server:latest .

# 3. 创建数据目录
mkdir -p uploads data

# 4. 启动容器
docker run -d \
  --name galaxy-package-server \
  -p 8083:8083 \
  -v "$(pwd)/uploads:/app/uploads" \
  -v "$(pwd)/data:/app/data" \
  -e NODE_ENV=production \
  -e PORT=8083 \
  --restart unless-stopped \
  galaxy-package-server:latest

# 5. 查看日志
docker logs -f galaxy-package-server
```

#### 重启服务

```bash
# 停止并删除旧容器
docker stop galaxy-package-server
docker rm galaxy-package-server

# 重新构建镜像
docker build -t galaxy-package-server:latest .

# 启动新容器（使用与首次部署相同的命令）
```

## ⚙️ 构建时间和资源需求

### 构建时间
- **首次构建**: 10-15 分钟（取决于网络速度）
  - 下载基础镜像: ~2 分钟
  - 安装系统依赖: ~1 分钟
  - 安装 npm 包: ~5 分钟
  - 编译 faiss-node: ~2 分钟
  - 下载 AI 模型: ~3 分钟（可选）

- **后续构建**: 5-8 分钟（利用 Docker 缓存）

### 运行时资源需求
- **内存**: 最低 1GB，推荐 2GB
- **CPU**: 2 核心（推荐）
- **存储**: 至少 2GB 可用空间

## 🔧 首次启动配置

### 1. 初始化向量索引

首次启动后，需要初始化 RAG 向量索引：

**方法 1: 通过前端页面**
- 访问: http://your-server:8083/intelligent-search.html
- 点击 "重建索引" 按钮

**方法 2: 通过 API**
```bash
curl -X POST http://your-server:8083/api/search/rebuild-index
```

**方法 3: 进入容器手动执行**
```bash
# 进入容器
docker exec -it galaxy-package-server sh

# 执行重建索引（通过 API）
node -e "
const http = require('http');
const options = {
  hostname: 'localhost',
  port: 8083,
  path: '/api/search/rebuild-index',
  method: 'POST'
};
const req = http.request(options, (res) => {
  res.on('data', (d) => process.stdout.write(d));
});
req.end();
"
```

### 2. 验证服务

```bash
# 检查基础服务
curl http://your-server:8083/health

# 检查 RAG 服务状态
curl http://your-server:8083/api/search/status

# 测试智能搜索
curl -X POST http://your-server:8083/api/search/intelligent \
  -H "Content-Type: application/json" \
  -d '{"query": "测试查询", "limit": 3}'
```

## 📋 推荐的部署脚本

在生产服务器上执行：

```bash
#!/bin/bash

echo "🚀 开始部署 Raven 包管理系统（含 RAG 功能）"

# 1. 拉取最新代码
cd /path/to/package-server
git pull

# 2. 停止旧服务
docker-compose down

# 3. 重新构建镜像（不使用缓存）
echo "🔨 构建 Docker 镜像（这可能需要 10-15 分钟）..."
docker-compose build --no-cache

# 4. 启动服务
echo "🚀 启动服务..."
docker-compose up -d

# 5. 等待服务就绪
echo "⏳ 等待服务启动（60秒）..."
sleep 60

# 6. 检查服务状态
echo "🔍 检查服务状态..."
curl -f http://localhost:8083/health || {
  echo "❌ 服务启动失败！查看日志："
  docker-compose logs --tail=50
  exit 1
}

# 7. 检查 RAG 服务
echo "🤖 检查 RAG 服务..."
curl -s http://localhost:8083/api/search/status | grep -q '"initialized":true' && {
  echo "✅ RAG 服务已初始化"
} || {
  echo "⚠️  RAG 服务未初始化，需要重建索引"
  echo "💡 提示：访问 http://localhost:8083/intelligent-search.html 点击 '重建索引' 按钮"
}

echo "🎉 部署完成！"
echo "📦 服务地址: http://localhost:8083"
echo "🤖 智能搜索: http://localhost:8083/intelligent-search.html"
```

## 🔍 故障排查

### 问题 1: 构建时间过长

**原因**: 
- 下载依赖包慢
- 编译 faiss-node 慢
- 下载 AI 模型慢

**解决方案**:
```dockerfile
# 在 Dockerfile 中添加 npm 镜像
RUN npm config set registry https://registry.npmmirror.com && \
    npm ci
```

### 问题 2: 容器启动失败

**排查步骤**:
```bash
# 1. 查看容器日志
docker logs galaxy-package-server --tail=100

# 2. 检查是否是端口占用
lsof -i :8083

# 3. 检查磁盘空间
df -h

# 4. 检查内存
free -h
```

### 问题 3: RAG 功能不工作

**排查步骤**:
```bash
# 1. 检查 RAG 服务状态
curl http://localhost:8083/api/search/status

# 2. 检查容器日志中是否有模型加载失败的信息
docker logs galaxy-package-server | grep -i "model\|embedding\|faiss"

# 3. 进入容器检查模型文件
docker exec -it galaxy-package-server sh
ls -la ~/.cache/huggingface/
```

### 问题 4: 模型下载失败（网络问题）

**解决方案**:
```bash
# 方法 1: 使用镜像站点
# 在容器启动前设置环境变量
docker run -d \
  -e HF_ENDPOINT=https://hf-mirror.com \
  ...

# 方法 2: 手动下载模型并挂载
# 1. 在宿主机下载模型
mkdir -p huggingface_cache
# 手动下载到这个目录

# 2. 启动时挂载
docker run -d \
  -v "$(pwd)/huggingface_cache:/home/node/.cache/huggingface" \
  ...
```

### 问题 5: 权限错误 EACCES: permission denied

**错误信息**:
```
Error: EACCES: permission denied, open '/app/uploads/xxx.tgz'
```

**原因**: 
- Docker 容器以 `node` 用户（UID 1000）运行
- 宿主机挂载的 `uploads` 或 `data` 目录权限不匹配
- 卷挂载时，容器内的权限设置会被宿主机目录权限覆盖

**解决方案**:

**方法 1: 使用修复脚本（推荐）**
```bash
# 进入项目目录
cd /path/to/package-server

# 运行权限修复脚本
sudo ./scripts/fix-permissions.sh

# 如果容器内用户 UID 不是 1000，可以指定
sudo ./scripts/fix-permissions.sh 1001 1001
```

**方法 2: 手动修复权限**
```bash
# 1. 检查容器内用户 UID
docker exec galaxy-package-server id
# 输出示例: uid=1000(node) gid=1000(node) groups=1000(node)

# 2. 修复宿主机目录权限（使用容器内的 UID/GID）
sudo chown -R 1000:1000 uploads data
sudo chmod -R 755 uploads data

# 3. 验证权限
ls -ld uploads data
```

**方法 3: 使用宽松权限（不推荐，安全性较低）**
```bash
# 如果无法修改所有者，可以使用宽松权限
chmod -R 777 uploads data
```

**方法 4: 在 docker-compose.yml 中添加用户映射（高级）**
```yaml
services:
  package-server:
    # ... 其他配置 ...
    user: "${UID:-1000}:${GID:-1000}"  # 使用环境变量或默认值
```

然后设置环境变量：
```bash
export UID=$(id -u)
export GID=$(id -g)
docker-compose up -d
```

**验证修复**:
```bash
# 1. 重启容器
docker-compose restart

# 2. 检查日志，确认没有权限错误
docker logs galaxy-package-server --tail=50

# 3. 测试上传功能
curl -X POST http://localhost:8083/api/upload \
  -F "file=@test.tgz"
```

## 📊 监控建议

### 日志监控
```bash
# 实时查看日志
docker logs -f galaxy-package-server

# 只看错误日志
docker logs galaxy-package-server 2>&1 | grep -i error

# 查看最近的日志
docker logs --tail=100 galaxy-package-server
```

### 性能监控
```bash
# 查看容器资源使用
docker stats galaxy-package-server

# 查看容器内存使用详情
docker exec galaxy-package-server sh -c "ps aux | head -n 20"
```

### 健康检查
```bash
# 定期检查服务健康状态
watch -n 30 'curl -s http://localhost:8083/health | jq'
```

## 🔒 安全建议

1. **API 密钥管理**: 
   - 不要在代码中硬编码 API 密钥
   - 使用环境变量或 Docker secrets

2. **网络隔离**:
   - 使用 Docker 网络隔离
   - 只暴露必要的端口

3. **定期更新**:
   - 定期更新基础镜像
   - 及时更新依赖包

## 📝 更新日志

### 2024-11-13 - RAG 功能上线
- ✅ 新增 RAG 智能搜索功能
- ✅ 更新 Dockerfile 支持原生模块编译
- ✅ 增加 AI 模型预加载（可选）
- ✅ 调整健康检查等待时间

## 🎯 执行命令总结

**生产环境重启 Docker 服务的推荐命令：**

```bash
# 方法 1: 使用提供的脚本（推荐）
cd /path/to/package-server
./scripts/restart.sh

# 方法 2: 使用 Docker Compose（推荐）
cd /path/to/package-server
docker-compose down
docker-compose build --no-cache
docker-compose up -d

# 方法 3: 查看构建和启动日志
docker-compose up --build
```

**首次部署使用：**
```bash
cd /path/to/package-server
docker-compose up -d --build
```

选择哪个？
- **首次部署**: 使用 `docker-compose up -d --build`
- **代码更新**: 使用 `./scripts/restart.sh` 或 `docker-compose` 命令
- **快速重启**（仅重启，不重建）: `docker-compose restart`

---

**状态**: ✅ 已验证  
**最后更新**: 2024-11-13  
**适用版本**: 1.0.0+RAG

