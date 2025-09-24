# Deploy.sh 使用说明

## 概述

`deploy.sh` 脚本是 LogStagingService 的部署和管理工具，支持正常部署和数据清理功能。

## 使用方法

### 1. 正常部署服务

```bash
./deploy.sh
```

这将：
- 检查 Docker 和 docker-compose 依赖
- 构建并启动所有服务容器
- 显示服务状态和访问地址

### 2. 清理容器内运行时数据

```bash
./deploy.sh clean
```

这将：
- 检查容器是否运行（如未运行则先启动）
- 在 app 容器内执行 `cleanup_runtime_data.py` 脚本
- 清理所有运行时产生的数据：
  - 数据库中的日志记录
  - 临时文件和缓存
  - 应用程序日志
  - Python 缓存文件
- 重启相关服务以确保清理生效

### 3. 显示帮助信息

```bash
./deploy.sh --help
# 或
./deploy.sh -h
```

## 清理功能详细说明

当使用 `clean` 参数时，脚本会：

1. **检查容器状态**：如果容器未运行，会先启动容器
2. **确保清理脚本可用**：
   - 检查 `cleanup_runtime_data.py` 是否存在于容器中
   - 如果不存在，自动从本地拷贝到容器
   - 设置脚本的执行权限
3. **执行清理脚本**：在容器内运行 `python cleanup_runtime_data.py -f --verbose`
4. **重启服务**：清理完成后重启 app 和 worker 容器

### 清理的数据包括：

- **数据库文件**：`logs.db`
- **临时目录**：`/app/temp/` 下的所有文件
- **日志目录**：`/app/logs/` 下的所有文件  
- **数据目录**：`/app/data/` 下的所有文件
- **Python 缓存**：`__pycache__` 目录和 `.pyc` 文件
- **上传文件**：默认保留，可通过清理脚本参数控制

## 注意事项

1. **数据备份**：清理操作会删除所有运行时数据，请确保重要数据已备份
2. **服务中断**：清理过程中服务会短暂重启
3. **权限要求**：需要 Docker 和 docker-compose 的执行权限
4. **容器依赖**：清理功能需要容器环境，会自动启动容器如果未运行

## 错误处理

脚本包含完整的错误处理：
- 检查 Docker 和 docker-compose 是否安装
- 验证清理脚本执行结果
- 提供详细的错误信息和日志

## 示例输出

### 正常部署
```
[INFO] 开始部署 LogStagingService...
[SUCCESS] 服务部署成功
[INFO] 等待服务启动...
[INFO] 检查服务状态:
[INFO] 服务访问地址: http://localhost:8085
[INFO] 健康检查: http://localhost:8085/health
```

### 数据清理
```
[INFO] 开始清理容器内的运行时数据...
[INFO] 在容器内执行清理脚本...
[SUCCESS] 容器内数据清理完成
[INFO] 重启服务...
[SUCCESS] 清理操作完成，服务已重启
```