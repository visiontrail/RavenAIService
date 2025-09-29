#!/bin/bash

# 默认配置
RUN_MIGRATION=false
COMPOSE_FILE="docker-compose.deploy-dev.yml"

# 同步 .env 到 .env.example（Compose 使用 .env.example 作为容器环境来源）
sync_env_file() {
    echo "🧩 同步环境变量文件 (.env → .env.example)..."
    if [ -f ".env" ]; then
        if [ -f ".env.example" ]; then
            if cmp -s ".env" ".env.example"; then
                echo "ℹ️ 检测到 .env 无变化，跳过同步"
                return 0
            fi
            local backup_name=".env.example.bak_$(date +%Y%m%d%H%M%S)"
            cp ".env.example" "$backup_name"
            echo "📦 已备份 .env.example 为 $backup_name"
        fi
        cp ".env" ".env.example"
        echo "✅ 已更新 .env.example（容器将使用最新环境变量）"
    else
        echo "ℹ️ 未找到 .env 文件，跳过环境变量同步"
    fi
}

# 显示帮助信息
show_help() {
    echo "🔄 部署环境快速重启脚本"
    echo ""
    echo "用法: $0 [选项]"
    echo ""
    echo "选项:"
    echo "  --migrate      强制执行数据库迁移"
    echo "  --no-migrate   跳过数据库迁移（默认行为）"
    echo "  -h, --help     显示此帮助信息"
    echo ""
    echo "说明:"
    echo "  此脚本会自动编译前端代码并重启服务，支持前端和后端代码热重载。"
    echo "  默认情况下会跳过数据库迁移以加快重启速度。"
    echo ""
    echo "示例:"
    echo "  $0                # 默认执行，跳过数据库迁移"
    echo "  $0 --migrate      # 明确指定执行数据库迁移"
    echo "  $0 --no-migrate   # 跳过数据库迁移（默认行为）"
    exit 0
}

# 解析命令行参数
while [[ $# -gt 0 ]]; do
    case $1 in
        --migrate)
            RUN_MIGRATION=true
            shift
            ;;
        --no-migrate)
            RUN_MIGRATION=false
            shift
            ;;
        -h|--help)
            show_help
            ;;
        *)
            echo "❌ 未知参数: $1"
            echo "使用 $0 --help 查看帮助信息"
            exit 1
            ;;
    esac
done

echo "🔄 部署环境快速重启（支持代码热重载）..."
echo "📋 数据库迁移: $([ "$RUN_MIGRATION" = true ] && echo "启用" || echo "跳过")"

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

# 在停止/启动容器前，同步环境变量文件，确保 .env 变更生效
sync_env_file

echo "📋 停止服务..."
docker-compose -f $COMPOSE_FILE down

# 根据参数决定是否执行数据库迁移
if [ "$RUN_MIGRATION" = true ]; then
    echo "🗄️ 运行数据库迁移..."
    # 运行数据库迁移，确保数据库结构是最新的
    docker-compose -f $COMPOSE_FILE run --rm app python -m alembic upgrade head
    if [ $? -ne 0 ]; then
        echo "❌ 数据库迁移失败！"
        exit 1
    fi
    echo "✅ 数据库迁移完成"
else
    echo "⏭️ 跳过数据库迁移（默认行为）"
fi

echo "🔧 重启服务（无需重新构建）..."
docker-compose -f $COMPOSE_FILE up -d

echo "⏳ 等待服务启动..."
sleep 3

echo "📊 检查服务状态..."
docker-compose -f $COMPOSE_FILE ps

echo "🎉 重启完成！代码更改已生效。"
echo "💡 提示：此脚本会自动编译前端代码并重启服务，支持前端和后端代码热重载。"
echo "📖 使用 $0 --help 查看更多选项，包括数据库迁移控制参数。"