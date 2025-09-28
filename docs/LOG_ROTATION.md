# Docker日志滚动配置说明

## 当前配置

我已经为你的Docker Compose配置添加了日志滚动功能，具体配置如下：

### 日志滚动参数
- **max-size**: 10m (单个日志文件最大10MB)
- **max-file**: 3 (最多保留3个日志文件)
- **总日志大小**: 最多30MB (10MB × 3个文件)

### 配置的服务
- `app` - 主应用服务
- `redis` - Redis数据库
- `worker` - Celery工作进程
- `nginx` - 反向代理

## 使用方法

### 1. 查看实时日志
```bash
./logs.sh
```

### 2. 清空所有日志
```bash
./logs.sh clean
```

### 3. 检查日志配置和大小
```bash
./logs.sh config
```

## 日志滚动工作原理

1. **自动滚动**: 当单个日志文件达到10MB时，Docker会自动创建新的日志文件
2. **文件轮转**: 保留最新的3个日志文件，自动删除更早的文件
3. **空间控制**: 总日志大小不会超过30MB

## 高级配置选项

如果需要调整日志滚动参数，可以修改 `docker-compose.yml` 中的 `logging` 配置：

```yaml
logging:
  driver: "json-file"
  options:
    max-size: "50m"    # 单个文件最大50MB
    max-file: "5"      # 保留5个文件
```

## 全局Docker配置

如果需要为所有Docker容器设置全局日志滚动，可以将 `docker-daemon.json` 文件复制到Docker配置目录：

```bash
# macOS
sudo cp docker-daemon.json /etc/docker/daemon.json

# 然后重启Docker服务
sudo systemctl restart docker  # Linux
# 或重启Docker Desktop (macOS)
```

## 监控日志大小

使用以下命令监控日志文件大小：

```bash
# 查看所有容器日志文件大小
docker system df -v

# 查看特定容器的日志
docker logs --tail 100 <container_name>
```
