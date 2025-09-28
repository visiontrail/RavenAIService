#!/bin/bash

echo "🔄 部署环境快速重启（支持代码热重载）..."

# 使用部署开发配置
COMPOSE_FILE="docker-compose.deploy-dev.yml"

echo "🏗️ 编译前端代码..."

# 检查本地是否有 npm 命令
if command -v npm &> /dev/null; then
    echo "📍 使用本地 npm 构建前端..."
    cd frontend
    if [ ! -d "node_modules" ]; then
        echo "📦 安装前端依赖..."
        npm install
    fi
    echo "🔨 构建前端..."
    npm run build
    if [ $? -ne 0 ]; then
        echo "❌ 前端构建失败！"
        exit 1
    fi
    echo "✅ 前端构建完成"
    cd ..
else
    echo "📍 本地未找到 npm，使用 Docker 容器构建前端..."
    
    # 创建临时构建容器
    echo "🐳 创建临时构建容器（使用 Node.js 20）..."
    docker run --rm \
        -v "$(pwd)/frontend:/app/frontend" \
        -w /app/frontend \
        node:20-alpine \
        sh -c "
            echo '📦 安装前端依赖...' && \
            npm install --no-fund --no-audit && \
            echo '🔨 构建前端...' && \
            npm run build
        "
    
    if [ $? -ne 0 ]; then
        echo "❌ 容器内前端构建失败！"
        exit 1
    fi
    echo "✅ 容器内前端构建完成"
fi

echo "📋 停止服务..."
docker-compose -f $COMPOSE_FILE down

echo "🗄️ 运行数据库迁移..."
# 运行数据库迁移，确保数据库结构是最新的
docker-compose -f $COMPOSE_FILE run --rm app python -m alembic upgrade head
if [ $? -ne 0 ]; then
    echo "❌ 数据库迁移失败！"
    exit 1
fi
echo "✅ 数据库迁移完成"

echo "🔧 重启服务（无需重新构建）..."
docker-compose -f $COMPOSE_FILE up -d

echo "⏳ 等待服务启动..."
sleep 3

echo "📊 检查服务状态..."
docker-compose -f $COMPOSE_FILE ps

echo "🎉 重启完成！代码更改已生效。"
echo "💡 提示：此脚本会自动编译前端代码、运行数据库迁移并重启服务，支持前端和后端代码热重载。"