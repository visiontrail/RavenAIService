#!/bin/bash

# Galaxy Space Package Server - Restart Script
# 重启包管理服务器容器（支持代码更新）

set -e

echo "🔄 重启 Galaxy Space 包管理服务器（应用代码更新）..."

# 配置变量
CONTAINER_NAME="galaxy-package-server"
IMAGE_NAME="galaxy-package-server"

# 获取脚本所在目录的父目录（项目根目录）
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"

echo "📁 项目目录: $PROJECT_DIR"

# 切换到项目目录
cd "$PROJECT_DIR"

# 检查是否存在 docker-compose.yml
if [ -f "docker-compose.yml" ]; then
    echo "🐳 使用 Docker Compose 重新部署..."
    
    # 停止并删除现有容器
    echo "🛑 停止现有服务..."
    docker-compose down
    
    # 重新构建镜像（不使用缓存以确保代码更新）
    echo "🔨 重新构建镜像（应用代码更新）..."
    docker-compose build --no-cache
    
    # 启动服务
    echo "🚀 启动服务..."
    docker-compose up -d
    
    # 等待服务启动
    echo "⏳ 等待服务启动..."
    sleep 10
    
    # 检查服务状态
    if [ "$(docker-compose ps -q)" ]; then
        echo "✅ 服务重启成功！"
        echo "📊 服务状态:"
        docker-compose ps
        echo ""
        echo "🌐 服务地址: http://localhost:8083"
        echo "🔍 健康检查: http://localhost:8083/health"
        echo "📋 查看日志: docker-compose logs -f"
    else
        echo "❌ 服务启动失败！"
        echo "📋 查看错误日志: docker-compose logs"
        exit 1
    fi
    
else
    echo "🐳 使用 Docker 命令重新部署..."
    
    # 停止并删除现有容器
    if [ "$(docker ps -aq -f name=$CONTAINER_NAME)" ]; then
        echo "🛑 停止并删除现有容器..."
        docker stop $CONTAINER_NAME 2>/dev/null || true
        docker rm $CONTAINER_NAME 2>/dev/null || true
    fi
    
    # 删除现有镜像（可选，确保使用最新代码）
    if [ "$(docker images -q $IMAGE_NAME)" ]; then
        echo "🗑️  删除旧镜像..."
        docker rmi $IMAGE_NAME 2>/dev/null || true
    fi
    
    # 重新构建镜像
    echo "🔨 重新构建镜像（应用代码更新）..."
    docker build -t $IMAGE_NAME .
    
    # 启动新容器
    echo "🚀 启动新容器..."
    docker run -d \
        --name $CONTAINER_NAME \
        -p 8083:8083 \
        -v "$(pwd)/uploads:/app/uploads" \
        -v "$(pwd)/data:/app/data" \
        -e NODE_ENV=production \
        -e PORT=8083 \
        --restart unless-stopped \
        $IMAGE_NAME
    
    # 等待服务启动
    echo "⏳ 等待服务启动..."
    sleep 10
    
    # 检查容器状态
    if [ "$(docker ps -q -f name=$CONTAINER_NAME)" ]; then
        echo "✅ 容器重启成功！"
        echo "📊 容器状态:"
        docker ps -f name=$CONTAINER_NAME
        echo ""
        echo "🌐 服务地址: http://localhost:8083"
        echo "🔍 健康检查: http://localhost:8083/health"
        echo "📋 查看日志: docker logs -f $CONTAINER_NAME"
    else
        echo "❌ 容器启动失败！"
        echo "📋 查看错误日志: docker logs $CONTAINER_NAME"
        exit 1
    fi
fi

echo ""
echo "🎉 重启完成！代码更新已应用。"
echo "💡 提示: 如果只是数据文件更改（如 package-metadata.json），可以使用快速重启："
echo "   docker restart $CONTAINER_NAME"