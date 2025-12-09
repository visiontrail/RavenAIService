#!/bin/bash

# Galaxy Space Package Server - Deploy Script
# 部署 Docker 容器中的包管理服务器

set -e

echo "🚀 部署 Galaxy Space 包管理服务器..."

# 配置变量
CONTAINER_NAME="galaxy-package-server"
IMAGE_NAME="galaxy-package-server"
IMAGE_TAG="latest"
PORT="8083"
HOST_PORT="8083"

# 检查是否存在 .env 文件
if [ ! -f ".env" ]; then
    echo "⚠️  未找到 .env 文件，创建默认配置..."
    cat > .env << EOF
PORT=8083
NODE_ENV=production
UPLOAD_DIR=/app/uploads
DATA_DIR=/app/data
MAX_FILE_SIZE=500MB
ALLOWED_ORIGINS=*
EOF
    echo "✅ 已创建默认 .env 文件，请根据需要修改配置"
fi

# 停止并删除现有容器（如果存在）
echo "🔍 检查现有容器..."
if [ "$(docker ps -q -f name=$CONTAINER_NAME)" ]; then
    echo "🛑 停止现有容器: $CONTAINER_NAME"
    docker stop $CONTAINER_NAME
fi

if [ "$(docker ps -aq -f name=$CONTAINER_NAME)" ]; then
    echo "🗑️  删除现有容器: $CONTAINER_NAME"
    docker rm $CONTAINER_NAME
fi

# 构建 Docker 镜像
echo "🔨 构建 Docker 镜像: $IMAGE_NAME:$IMAGE_TAG"
docker build -t $IMAGE_NAME:$IMAGE_TAG ..

# 创建必要的目录
echo "📁 创建数据目录..."
mkdir -p ./uploads
mkdir -p ./data
mkdir -p ./logs

# 设置目录权限，确保容器内的node用户可以写入
echo "🔐 设置目录权限..."
chmod 755 ./uploads ./data ./logs
# 如果以root身份运行，设置所有者为当前用户
if [ "$(id -u)" = "0" ]; then
    chown -R 1000:1000 ./uploads ./data ./logs
fi

# 启动容器
echo "🐳 启动 Docker 容器: $CONTAINER_NAME"
docker run -d \
  --name $CONTAINER_NAME \
  --restart unless-stopped \
  -p $HOST_PORT:$PORT \
  --env-file .env \
  -v "$(pwd)/uploads:/app/uploads" \
  -v "$(pwd)/data:/app/data" \
  -v "$(pwd)/logs:/app/logs" \
  $IMAGE_NAME:$IMAGE_TAG

# 等待服务启动
echo "⏳ 等待服务启动..."
sleep 5

# 检查容器状态
if [ "$(docker ps -q -f name=$CONTAINER_NAME)" ]; then
    echo "✅ 容器启动成功！"
    echo "📊 容器状态:"
    docker ps -f name=$CONTAINER_NAME
    echo ""
    echo "🌐 服务地址: http://localhost:$HOST_PORT"
    echo "🔍 健康检查: http://localhost:$HOST_PORT/health"
    echo "📋 查看日志: docker logs $CONTAINER_NAME"
    echo "📦 包管理界面: http://localhost:$HOST_PORT"
else
    echo "❌ 容器启动失败！"
    echo "📋 查看错误日志: docker logs $CONTAINER_NAME"
    exit 1
fi

echo "🎉 Galaxy Space 包管理服务器部署完成！"