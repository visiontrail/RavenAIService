#!/bin/bash

# 检查参数
if [ "$1" = "clean" ]; then
    echo "正在清空Docker容器日志..."
    # 停止所有服务
    docker-compose down
    # 清理容器日志
    docker system prune -f
    # 清理Docker日志文件
    sudo truncate -s 0 /var/lib/docker/containers/*/*-json.log 2>/dev/null || true
    echo "日志清理完成"
    # 重新启动服务
    docker-compose up -d
    echo "服务已重新启动"
elif [ "$1" = "config" ]; then
    echo "=== Docker日志滚动配置检查 ==="
    echo "当前Docker日志驱动: $(docker info --format '{{.LoggingDriver}}')"
    echo ""
    echo "=== 容器日志配置 ==="
    docker-compose config --services | while read service; do
        echo "服务: $service"
        docker-compose config | grep -A 5 "logging:" | grep -A 5 "$service" || echo "  未配置日志滚动"
    done
    echo ""
    echo "=== 日志文件大小 ==="
    docker-compose ps -q | while read container; do
        if [ ! -z "$container" ]; then
            echo "容器: $container"
            echo "  日志文件: $(docker inspect $container --format='{{.LogPath}}')"
            echo "  文件大小: $(ls -lh $(docker inspect $container --format='{{.LogPath}}') 2>/dev/null | awk '{print $5}' || echo 'N/A')"
        fi
    done
else
    # 默认行为：显示实时日志
    docker-compose logs -f
fi