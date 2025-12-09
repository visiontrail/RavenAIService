#!/bin/bash

# Galaxy Space Package Server - 重建容器脚本
# 在修复代码后使用此脚本重建并重启容器

CONTAINER_NAME="galaxy-package-server"

echo "=========================================="
echo "  重建并重启容器"
echo "=========================================="
echo ""

echo "1️⃣ 停止并删除旧容器..."
docker-compose down
echo ""

echo "2️⃣ 清理旧镜像..."
docker rmi package-server-package-server 2>/dev/null || echo "旧镜像已清理或不存在"
echo ""

echo "3️⃣ 重新构建镜像（无缓存）..."
docker-compose build --no-cache
echo ""

echo "4️⃣ 启动新容器..."
docker-compose up -d
echo ""

echo "5️⃣ 等待容器启动（15秒）..."
for i in {15..1}; do
    echo -ne "⏳ $i 秒...\r"
    sleep 1
done
echo ""
echo ""

echo "6️⃣ 检查容器状态..."
docker ps -a | grep $CONTAINER_NAME
echo ""

echo "7️⃣ 查看启动日志..."
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
docker logs $CONTAINER_NAME --tail=50
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""

# 检查容器是否正常运行
if docker ps | grep -q $CONTAINER_NAME; then
    echo "=========================================="
    echo "  ✅ 容器启动成功！"
    echo "=========================================="
    echo ""
    echo "🌐 服务地址: http://localhost:8083"
    echo "🏥 健康检查: curl http://localhost:8083/health"
    echo "📋 查看实时日志: docker logs -f $CONTAINER_NAME"
else
    echo "=========================================="
    echo "  ❌ 容器启动失败"
    echo "=========================================="
    echo ""
    echo "请查看上面的日志信息，或运行："
    echo "  docker logs $CONTAINER_NAME"
    echo ""
    echo "如需诊断，请运行："
    echo "  ./diagnose.sh"
fi
echo ""

