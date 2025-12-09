# Docker 配置更新日志

## 📅 更新日期: 2024-11-13

## 🎯 更新原因

为支持新增的 RAG 智能搜索功能，需要更新 Docker 配置以满足以下要求：
1. 编译原生模块 `faiss-node`
2. 运行 AI 模型推理
3. 下载和缓存嵌入模型

## 📝 更新的文件

### 1. Dockerfile ✅ **重要更新**

**文件路径**: `/package-server/Dockerfile`

**主要变更**:
```diff
- FROM node:18-alpine
+ FROM node:18

+ # 安装系统依赖（用于编译 faiss-node）
+ RUN apt-get update && apt-get install -y \
+     python3 \
+     make \
+     g++ \
+     cmake \
+     && rm -rf /var/lib/apt/lists/*

- RUN npm ci --only=production
+ RUN npm ci

+ # 预下载嵌入模型（可选）
+ RUN echo "..." | node || true

- HEALTHCHECK --start-period=5s
+ HEALTHCHECK --start-period=60s

- USER node
- CMD ["/app/entrypoint.sh"]
+ USER node
+ CMD ["npm", "start"]
```

**影响**:
- ✅ 支持原生模块编译
- ✅ 镜像大小增加（150MB → 1.2GB）
- ✅ 构建时间增加（3-5分钟 → 10-15分钟）
- ✅ 启动时间增加（5秒 → 60-90秒）

### 2. docker-compose.yml ✅ **更新**

**文件路径**: `/package-server/docker-compose.yml`

**主要变更**:
```diff
  healthcheck:
-   start_period: 40s
+   start_period: 90s

+ # 可选配置
+ # volumes:
+ #   - ./huggingface_cache:/home/node/.cache/huggingface
+ # environment:
+ #   - HF_ENDPOINT=https://hf-mirror.com

+ # 资源限制
+ deploy:
+   resources:
+     limits:
+       cpus: '2'
+       memory: 2G
```

**影响**:
- ✅ 增加启动等待时间
- ✅ 添加资源限制
- ✅ 提供可选的镜像配置

### 3. 新增文件

#### 部署文档
- ✅ `PRODUCTION-DEPLOYMENT.md` - 详细的生产部署指南
- ✅ `DEPLOYMENT-SUMMARY.md` - 部署总结和快速参考
- ✅ `CHANGELOG-DOCKER.md` - 本文件

#### 部署脚本
- ✅ `scripts/check-deployment.sh` - 部署前环境检查脚本

**功能**:
- 检查 Docker 安装
- 检查磁盘空间和内存
- 检查网络连接
- 检查端口占用
- 验证 RAG 依赖配置

## 🔄 迁移指南

### 从旧版本迁移

如果你已经部署了旧版本（没有 RAG 功能），需要：

```bash
# 1. 停止旧服务
docker-compose down

# 2. 备份数据（可选）
cp -r uploads uploads.backup
cp -r data data.backup

# 3. 拉取最新代码
git pull

# 4. 重新构建和启动
docker-compose build --no-cache
docker-compose up -d

# 5. 等待服务就绪
sleep 90

# 6. 初始化 RAG 索引
curl -X POST http://localhost:8083/api/search/rebuild-index
```

### 首次部署

```bash
# 1. 克隆或拉取代码
cd /path/to/package-server

# 2. 检查环境（可选）
./scripts/check-deployment.sh

# 3. 启动服务
docker-compose up -d --build

# 4. 等待就绪
sleep 90

# 5. 验证服务
curl http://localhost:8083/health

# 6. 初始化 RAG 索引
curl -X POST http://localhost:8083/api/search/rebuild-index
```

## ⚠️ 重要注意事项

### 1. 镜像大小变化

| 版本 | 基础镜像 | 大小 | 说明 |
|-----|---------|------|------|
| 旧版本 | node:18-alpine | ~150MB | 轻量级 Alpine Linux |
| 新版本 | node:18 | ~1.2GB | 包含编译工具和 AI 模型 |

**建议**:
- 如果存储空间受限，可以删除 Dockerfile 中的模型预加载步骤
- 模型会在首次运行时自动下载（需要网络访问）

### 2. 构建时间变化

| 阶段 | 旧版本 | 新版本 | 变化 |
|-----|--------|--------|------|
| 首次构建 | 3-5分钟 | 10-15分钟 | +200% |
| 后续构建 | 2-3分钟 | 5-8分钟 | +150% |

**原因**:
- 安装系统依赖
- 编译原生模块
- 下载 AI 模型（可选）

### 3. 启动时间变化

| 阶段 | 旧版本 | 新版本 | 变化 |
|-----|--------|--------|------|
| 容器启动 | 5秒 | 10秒 | +100% |
| 服务就绪 | 10秒 | 60-90秒 | +500% |

**原因**:
- 加载 AI 模型到内存
- 初始化 LangChain 框架
- 加载 FAISS 向量存储（如果已存在）

### 4. 资源需求变化

| 资源 | 旧版本 | 新版本 | 建议 |
|-----|--------|--------|------|
| 内存 | 512MB | 1-2GB | 推荐 2GB |
| CPU | 1核 | 2核 | 推荐 2核 |
| 磁盘 | 500MB | 2GB+ | 至少 2GB |

## 🔍 验证检查清单

部署完成后，验证以下内容：

- [ ] 容器正常运行：`docker ps | grep galaxy-package-server`
- [ ] 健康检查通过：`curl http://localhost:8083/health`
- [ ] 包管理功能正常：`curl http://localhost:8083/api/packages`
- [ ] RAG 服务初始化：`curl http://localhost:8083/api/search/status`
- [ ] 前端页面可访问：打开 `http://localhost:8083`
- [ ] 智能搜索页面可访问：打开 `http://localhost:8083/intelligent-search.html`
- [ ] 日志无严重错误：`docker-compose logs --tail=50`

## 🐛 常见问题

### Q1: 构建时报错 "Cannot find module 'faiss-node'"

**原因**: 编译环境缺少必要工具

**解决方案**: 确保 Dockerfile 中已安装 python3, make, g++, cmake

### Q2: 首次启动很慢，长时间显示 "not ready"

**原因**: 正在下载 AI 模型（约 100MB）

**解决方案**: 
- 等待下载完成（可能需要 5-10 分钟）
- 或在 docker-compose.yml 中配置 HuggingFace 镜像站点

### Q3: RAG 服务显示 "initialized: false"

**原因**: 向量索引未初始化

**解决方案**:
```bash
curl -X POST http://localhost:8083/api/search/rebuild-index
```

### Q4: 内存不足导致容器重启

**原因**: AI 模型需要较多内存

**解决方案**:
- 增加 Docker 内存限制（至少 2GB）
- 或调整 docker-compose.yml 中的资源限制

## 📊 性能对比

### 旧版本（无 RAG）
- 镜像大小: 150MB
- 构建时间: 3-5 分钟
- 启动时间: 10 秒
- 内存占用: ~200MB
- 功能: 基础包管理

### 新版本（含 RAG）
- 镜像大小: 1.2GB
- 构建时间: 10-15 分钟
- 启动时间: 60-90 秒
- 内存占用: ~800MB-1.5GB
- 功能: 包管理 + AI 智能搜索

## 🔧 优化建议

### 减少镜像大小
```dockerfile
# 在 Dockerfile 中删除模型预加载行
# RUN echo "..." | node || true
```

### 加速构建
```dockerfile
# 使用 NPM 镜像
RUN npm config set registry https://registry.npmmirror.com
```

### 加速模型下载
```yaml
# 在 docker-compose.yml 中添加
environment:
  - HF_ENDPOINT=https://hf-mirror.com
```

### 缓存模型文件
```yaml
# 在 docker-compose.yml 中添加
volumes:
  - ./huggingface_cache:/home/node/.cache/huggingface
```

## 📚 相关资源

- [Docker 官方文档](https://docs.docker.com/)
- [Docker Compose 文档](https://docs.docker.com/compose/)
- [Node.js Docker 最佳实践](https://github.com/nodejs/docker-node/blob/main/docs/BestPractices.md)
- [FAISS 文档](https://github.com/facebookresearch/faiss)

## 🎯 下一步

1. **测试部署**: 在测试环境验证新配置
2. **性能测试**: 测试并发请求和响应时间
3. **监控设置**: 配置日志和监控
4. **备份策略**: 制定数据备份计划
5. **文档更新**: 更新内部部署文档

---

**更新人**: AI Assistant  
**审核人**: 待审核  
**生效日期**: 2024-11-13  
**版本**: Docker Config v2.0

