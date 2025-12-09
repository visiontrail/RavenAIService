#!/bin/bash

# Galaxy Space Package Server - Quick Restart Script
# 快速重启包管理服务器容器（不重新构建镜像）
# 适用于：数据文件更改、配置更改等不涉及代码的情况

set -e

echo "⚡ 快速重启 Galaxy Space 包管理服务器..."

# 配置变量
CONTAINER_NAME="galaxy-package-server"

# 获取脚本所在目录的父目录（项目根目录）
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"

echo "📁 项目目录: $PROJECT_DIR"

# 切换到项目目录
cd "$PROJECT_DIR"

# 检查是否存在 docker-compose.yml
if [ -f "docker-compose.yml" ]; then
    echo "🐳 使用 Docker Compose 快速重启..."
    
    # 重启服务
    docker-compose restart
    
    # 等待服务启动
    echo "⏳ 等待服务启动..."
    sleep 5
    
    # 检查服务状态
    if [ "$(docker-compose ps -q)" ]; then
        echo "✅ 服务重启成功！"
        echo "📊 服务状态:"
        docker-compose ps
    else
        echo "❌ 服务启动失败！"
        echo "📋 查看错误日志: docker-compose logs"
        exit 1
    fi
    
else
    # 检查容器是否存在
    if [ "$(docker ps -aq -f name=$CONTAINER_NAME)" ]; then
        echo "🔍 找到容器: $CONTAINER_NAME"
        
        # 重启容器
        echo "🔄 重启容器..."
        docker restart $CONTAINER_NAME
        
        # 等待服务启动
        echo "⏳ 等待服务启动..."
        sleep 5
        
        # 检查容器状态
        if [ "$(docker ps -q -f name=$CONTAINER_NAME)" ]; then
            echo "✅ 容器重启成功！"
            echo "📊 容器状态:"
            docker ps -f name=$CONTAINER_NAME
        else
            echo "❌ 容器启动失败！"
            echo "📋 查看错误日志: docker logs $CONTAINER_NAME"
            exit 1
        fi
    else
        echo "❌ 未找到容器 $CONTAINER_NAME"
        echo "💡 请先运行部署脚本或完整重启脚本"
        exit 1
    fi
fi

echo ""
echo "🌐 服务地址: http://localhost:8083"
echo "🔍 健康检查: http://localhost:8083/health"
echo "📋 查看日志: docker logs -f $CONTAINER_NAME"
echo ""
echo "⚡ 快速重启完成！"
echo "💡 注意: 此脚本不会应用代码更改，如需应用代码更改请使用 ./restart.sh"