#!/bin/bash

# Galaxy Space Package Server - Stop Script
# 停止包管理服务器容器

set -e

echo "🛑 停止 Galaxy Space 包管理服务器..."

# 配置变量
CONTAINER_NAME="galaxy-package-server"

# 检查容器是否正在运行
if [ "$(docker ps -q -f name=$CONTAINER_NAME)" ]; then
    echo "🔍 找到运行中的容器: $CONTAINER_NAME"
    echo "🛑 停止容器..."
    docker stop $CONTAINER_NAME
    echo "✅ 容器已停止"
else
    echo "ℹ️  容器 $CONTAINER_NAME 未在运行"
fi

# 检查是否需要删除容器
if [ "$(docker ps -aq -f name=$CONTAINER_NAME)" ]; then
    read -p "🗑️  是否删除容器? (y/N): " -n 1 -r
    echo
    if [[ $REPLY =~ ^[Yy]$ ]]; then
        docker rm $CONTAINER_NAME
        echo "✅ 容器已删除"
    else
        echo "ℹ️  容器已保留，可使用 'docker start $CONTAINER_NAME' 重新启动"
    fi
fi

echo "🎉 操作完成！"