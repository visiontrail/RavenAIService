# LogStagingService Docker 部署指南

## 概述

本文档提供了 LogStagingService 的完整 Docker 容器化部署方案，包括开发环境和生产环境的部署配置。

## 系统要求

- Docker 20.10+
- Docker Compose 2.0+
- 至少 4GB 可用内存
- 至少 10GB 可用磁盘空间

## 快速开始

### 1. 克隆项目并进入目录

```bash
cd /path/to/LogStagingService
```

### 2. 快速启动开发环境

```bash
# 使用快速启动脚本
./quick-start.sh

# 或者手动启动
docker-compose up -d
```

### 3. 访问服务

- 主应用: http://localhost:8085
- API文档: http://localhost:8085/docs
- 健康检查: http://localhost:8085/health
- 数据库管理: http://localhost:8080
- Redis管理: http://localhost:8081
- Nginx代理: http://localhost

## 详细部署步骤

### 开发环境部署

1. **环境配置**
   ```bash
   # 复制开发环境配置
   cp .env.development .env
   
   # 根据需要修改配置
   vim .env
   ```

2. **启动服务**
   ```bash
   # 使用开发配置启动
   docker-compose -f docker-compose.yml -f docker-compose.dev.yml up -d
   
   # 或使用快速启动脚本
   ./quick-start.sh
   ```

3. **查看服务状态**
   ```bash
   docker-compose ps
   ./scripts/logs.sh
   ```

### 生产环境部署

1. **环境配置**
   ```bash
   # 复制生产环境配置
   cp .env.production .env
   
   # 修改生产环境配置
   vim .env
   ```

2. **SSL证书配置**
   ```bash
   # 生成自签名证书（测试用）
   ./scripts/deploy.sh ssl
   
   # 或使用Let's Encrypt证书
   # 将证书文件放置到 docker/nginx/ssl/ 目录
   ```

3. **部署服务**
   ```bash
   # 完整部署
   ./scripts/deploy.sh
   
   # 或分步部署
   ./scripts/deploy.sh build
   ./scripts/deploy.sh start
   ```

## 服务架构

### 核心服务

- **app**: 主应用服务（FastAPI）
- **nginx**: 反向代理和负载均衡
- **postgres**: PostgreSQL 数据库
- **redis**: Redis 缓存和消息队列
- **celery_worker**: Celery 异步任务处理器

### 开发工具（仅开发环境）

- **adminer**: 数据库管理界面
- **redis_commander**: Redis 管理界面

## 配置文件说明

### Docker Compose 文件

- `docker-compose.yml`: 基础服务配置
- `docker-compose.dev.yml`: 开发环境特定配置
- `docker-compose.override.yml`: 本地开发覆盖配置

### 环境变量文件

- `.env.template`: 环境变量模板
- `.env.development`: 开发环境配置
- `.env.production`: 生产环境配置

### Nginx 配置

- `docker/nginx/nginx.conf`: Nginx 主配置
- `docker/nginx/conf.d/default.conf`: HTTP 站点配置
- `docker/nginx/conf.d/ssl.conf`: HTTPS 站点配置

## 管理脚本

### 部署脚本

```bash
# 完整部署
./scripts/deploy.sh

# 构建镜像
./scripts/deploy.sh build

# 启动服务
./scripts/deploy.sh start

# 生成SSL证书
./scripts/deploy.sh ssl
```

### 服务管理

```bash
# 重启服务
./scripts/restart.sh [service_name]

# 停止服务
./scripts/stop.sh [service_name]

# 查看日志
./scripts/logs.sh [service_name]
```

### 数据管理

```bash
# 备份数据
./scripts/backup.sh

# 恢复数据
./scripts/backup.sh restore backup_file.tar.gz

# 列出备份
./scripts/backup.sh list
```

### 快速操作

```bash
# 快速启动
./quick-start.sh

# 查看状态
./quick-start.sh status

# 查看日志
./quick-start.sh logs

# 停止服务
./quick-start.sh stop

# 清理数据
./quick-start.sh clean
```

## 监控和日志

### 健康检查

```bash
# 检查应用健康状态
curl http://localhost:8085/health

# 检查所有服务状态
docker-compose ps
```

### 日志查看

```bash
# 查看所有服务日志
./scripts/logs.sh

# 查看特定服务日志
./scripts/logs.sh app

# 实时监控日志
./scripts/logs.sh monitor

# 导出日志
./scripts/logs.sh export
```

### 性能监控

- 应用指标: http://localhost:8085/metrics
- 容器状态: `docker stats`
- 资源使用: `docker system df`

## 故障排除

### 常见问题

1. **端口冲突**
   ```bash
   # 检查端口占用
   lsof -i :8085
   
   # 修改端口配置
   vim .env
   ```

2. **内存不足**
   ```bash
   # 检查内存使用
   docker stats
   
   # 清理未使用的容器和镜像
   docker system prune -f
   ```

3. **数据库连接失败**
   ```bash
   # 检查数据库服务
   docker-compose logs postgres
   
   # 重启数据库服务
   ./scripts/restart.sh postgres
   ```

4. **SSL证书问题**
   ```bash
   # 重新生成证书
   ./scripts/deploy.sh ssl
   
   # 检查证书文件
   ls -la docker/nginx/ssl/
   ```

### 调试模式

```bash
# 启用调试模式
export DEBUG=true
export LOG_LEVEL=DEBUG

# 重启服务
./scripts/restart.sh app
```

## 安全配置

### 生产环境安全检查

1. **更改默认密码**
   - 数据库密码
   - Redis密码
   - 应用密钥

2. **配置防火墙**
   ```bash
   # 只开放必要端口
   ufw allow 80
   ufw allow 443
   ufw enable
   ```

3. **SSL/TLS配置**
   - 使用有效的SSL证书
   - 配置HSTS
   - 禁用不安全的协议

4. **定期更新**
   ```bash
   # 更新镜像
   docker-compose pull
   docker-compose up -d
   ```

## 备份和恢复

### 自动备份

```bash
# 设置定时备份（crontab）
0 2 * * * /path/to/LogStagingService/scripts/backup.sh
```

### 手动备份

```bash
# 创建备份
./scripts/backup.sh

# 恢复备份
./scripts/backup.sh restore backup_20240101_020000.tar.gz
```

## 扩展和优化

### 水平扩展

```bash
# 扩展Celery Worker
docker-compose up -d --scale celery_worker=3

# 扩展应用实例
docker-compose up -d --scale app=2
```

### 性能优化

1. **数据库优化**
   - 调整PostgreSQL配置
   - 添加适当的索引
   - 定期VACUUM

2. **缓存优化**
   - 调整Redis内存配置
   - 配置缓存策略

3. **应用优化**
   - 调整worker数量
   - 配置连接池
   - 启用压缩

## 支持和维护

### 日常维护

```bash
# 清理旧日志
./scripts/logs.sh cleanup

# 清理旧备份
./scripts/backup.sh cleanup

# 更新系统
docker-compose pull
./scripts/restart.sh
```

### 获取帮助

- 查看脚本帮助: `./quick-start.sh --help`
- 查看日志: `./scripts/logs.sh`
- 检查配置: `docker-compose config`

---

## 附录

### 目录结构

```
LogStagingService/
├── docker/
│   ├── nginx/
│   │   ├── nginx.conf
│   │   ├── conf.d/
│   │   └── ssl/
│   └── postgres/
│       └── init.sql
├── scripts/
│   ├── deploy.sh
│   ├── restart.sh
│   ├── stop.sh
│   ├── logs.sh
│   └── backup.sh
├── docker-compose.yml
├── docker-compose.dev.yml
├── docker-compose.override.yml
├── Dockerfile
├── Dockerfile.dev
├── quick-start.sh
├── .env.template
├── .env.development
├── .env.production
└── DEPLOYMENT.md
```

### 端口映射

| 服务 | 内部端口 | 外部端口 | 说明 |
|------|----------|----------|------|
| app | 8000 | 8085 | 主应用 |
| nginx | 80/443 | 80/443 | 反向代理 |
| postgres | 5432 | 5432 | 数据库 |
| redis | 6379 | 6379 | 缓存 |
| adminer | 8080 | 8080 | 数据库管理 |
| redis_commander | 8081 | 8081 | Redis管理 |

### 环境变量参考

详细的环境变量配置请参考 `.env.template` 文件。