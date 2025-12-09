#!/bin/bash

# Galaxy Space Package Server - 权限修复脚本
# 修复 Docker 卷挂载权限问题

echo "=========================================="
echo "  修复 Docker 卷挂载权限"
echo "=========================================="
echo ""

# 获取当前脚本所在目录的父目录（package-server目录）
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"

cd "$PROJECT_DIR"

echo "📁 项目目录: $PROJECT_DIR"
echo ""

# 检查目录是否存在
if [ ! -d "uploads" ]; then
    echo "📦 创建 uploads 目录..."
    mkdir -p uploads
fi

if [ ! -d "data" ]; then
    echo "📦 创建 data 目录..."
    mkdir -p data
fi

echo "🔧 修复目录权限..."

# 方法1: 使用 777 权限（简单但安全性较低）
if [ "$1" == "--permissive" ]; then
    echo "⚠️  使用宽松权限模式 (777)..."
    chmod -R 777 uploads data
    echo "✅ 已设置 uploads 和 data 目录为 777 权限"
else
    # 方法2: 查找 node 用户的 UID（推荐）
    # Docker 的 node 用户通常是 UID 1000
    NODE_UID=${2:-1000}
    NODE_GID=${3:-1000}
    
    echo "🔍 使用 UID/GID: $NODE_UID/$NODE_GID (node 用户)"
    echo ""
    
    # 检查当前用户是否有权限修改
    if [ "$EUID" -ne 0 ]; then
        echo "⚠️  需要 root 权限来修改文件所有者"
        echo "💡 请使用以下命令之一："
        echo ""
        echo "   方法 1: 使用 sudo 运行此脚本"
        echo "   sudo $0"
        echo ""
        echo "   方法 2: 手动执行（推荐）"
        echo "   sudo chown -R $NODE_UID:$NODE_GID uploads data"
        echo "   sudo chmod -R 755 uploads data"
        echo ""
        echo "   方法 3: 使用宽松权限（不推荐，安全性较低）"
        echo "   $0 --permissive"
        echo ""
        exit 1
    fi
    
    # 修改所有者和权限
    chown -R $NODE_UID:$NODE_GID uploads data
    chmod -R 755 uploads data
    
    echo "✅ 已设置 uploads 和 data 目录的所有者为 UID $NODE_UID"
    echo "✅ 已设置目录权限为 755"
fi

echo ""
echo "📋 验证权限设置..."
ls -ld uploads data 2>/dev/null || echo "⚠️  无法查看目录信息"

echo ""
echo "=========================================="
echo "  权限修复完成"
echo "=========================================="
echo ""
echo "💡 如果问题仍然存在，请检查："
echo "   1. 容器内的用户 UID 是否匹配"
echo "   2. 执行: docker exec galaxy-package-server id"
echo "   3. 如果 UID 不是 1000，请使用: $0 <uid> <gid>"
echo ""
echo "📋 查看容器内用户信息:"
echo "   docker exec galaxy-package-server id"
echo ""

