#!/bin/bash

echo "🔄 部署环境快速重启（支持代码热重载）..."

# 使用部署开发配置
COMPOSE_FILE="docker-compose.deploy-dev.yml"

echo "📋 停止服务..."
docker-compose -f $COMPOSE_FILE down

echo "🔧 重启服务（无需重新构建）..."
docker-compose -f $COMPOSE_FILE up -d

echo "⏳ 等待服务启动..."
sleep 3

echo "📊 检查服务状态..."
docker-compose -f $COMPOSE_FILE ps

echo "🎉 重启完成！代码更改已生效。"
echo "💡 提示：现在修改 Python 代码后，只需重启容器服务即可，无需重新构建镜像。"