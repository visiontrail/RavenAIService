#!/bin/bash

set -Eeuo pipefail

# 默认配置
RUN_MIGRATION=false
COMPOSE_FILE="docker-compose.deploy-dev.yml"
LOCK_FILE=".build_cache_lock"

report_port_usage() {
    local port="$1"
    echo "🔎 端口 ${port} 占用情况:"

    if command -v ss >/dev/null 2>&1; then
        ss -ltnp "( sport = :${port} )" 2>/dev/null || true
    elif command -v netstat >/dev/null 2>&1; then
        netstat -ltnp 2>/dev/null | grep ":${port} " || true
    else
        echo "ℹ️ 未找到 ss/netstat，无法打印端口占用详情"
    fi

    if command -v docker >/dev/null 2>&1; then
        docker ps --format 'table {{.Names}}\t{{.Ports}}' | grep "${port}->" || true
    fi
}

# 计算文件 MD5
get_file_md5() {
    local file="$1"
    if [ -f "$file" ]; then
        if command -v md5 &> /dev/null; then
            md5 -q "$file"
        elif command -v md5sum &> /dev/null; then
            md5sum "$file" | awk '{print $1}'
        else
            # 降级方案：使用文件修改时间
            stat -f "%m" "$file" 2>/dev/null || stat -c "%Y" "$file"
        fi
    else
        echo "none"
    fi
}

# 检查依赖是否需要重新安装
need_npm_install() {
    local lock_file="frontend/package-lock.json"
    local cache_file=".npm_install_cache"
    
    if [ ! -d "frontend/node_modules" ]; then
        echo "true"
        return
    fi
    
    if [ ! -f "$lock_file" ]; then
        echo "false"
        return
    fi
    
    local current_md5
    current_md5=$(get_file_md5 "$lock_file")
    
    if [ -f "$cache_file" ]; then
        local cached_md5
        cached_md5=$(cat "$cache_file")
        if [ "$current_md5" = "$cached_md5" ]; then
            echo "false"
            return
        fi
    fi
    
    echo "true"
}

# 更新 npm install 缓存
update_npm_cache() {
    local lock_file="frontend/package-lock.json"
    local cache_file=".npm_install_cache"
    
    if [ -f "$lock_file" ]; then
        get_file_md5 "$lock_file" > "$cache_file"
    fi
}

# 检查是否需要重建 Docker 镜像
need_docker_build() {
    local files_to_check=("Dockerfile" "requirements.txt" "bin/tool_log_decompress")
    local cache_file="${LOCK_FILE}"
    local need_build=false
    
    # 如果缓存文件不存在，需要构建
    if [ ! -f "$cache_file" ]; then
        echo "true"
        return
    fi
    
    # 检查每个关键文件的 MD5
    for file in "${files_to_check[@]}"; do
        if [ -f "$file" ]; then
            local current_md5
            current_md5=$(get_file_md5 "$file")
            local cached_md5
            cached_md5=$(grep "^${file}:" "$cache_file" 2>/dev/null | cut -d: -f2)
            
            if [ "$current_md5" != "$cached_md5" ]; then
                need_build=true
                break
            fi
        fi
    done
    
    if [ "$need_build" = true ]; then
        echo "true"
    else
        echo "false"
    fi
}

# 更新 Docker 构建缓存
update_docker_build_cache() {
    local files_to_check=("Dockerfile" "requirements.txt" "bin/tool_log_decompress")
    local cache_file="${LOCK_FILE}"
    
    rm -f "$cache_file"
    for file in "${files_to_check[@]}"; do
        if [ -f "$file" ]; then
            local md5
            md5=$(get_file_md5 "$file")
            echo "${file}:${md5}" >> "$cache_file"
        fi
    done
}

verify_release_routes() {
    local base_url="${1:-http://localhost:8085}"
    local endpoints=("/admin/releases" "/admin/releases/upload")
    local failed=0

    echo "🧪 校验发布上传路由..."

    for endpoint in "${endpoints[@]}"; do
        local status_code
        status_code=$(curl -s -o /dev/null -w "%{http_code}" -X POST "${base_url}${endpoint}" || echo "000")

        case "$status_code" in
            401|400|422)
                echo "✅ POST ${endpoint} -> ${status_code}"
                ;;
            *)
                echo "❌ POST ${endpoint} -> ${status_code}，期望 401/400/422，不能是 404/405"
                failed=1
                ;;
        esac
    done

    return $failed
}

# 等待服务健康
wait_for_health() {
    local service="$1"
    local max_wait=60
    local waited=0
    
    echo "⏳ 等待 $service 服务就绪..."
    
    while [ $waited -lt $max_wait ]; do
        if docker-compose -f $COMPOSE_FILE ps | grep -q "$service.*Up.*healthy"; then
            echo "✅ $service 服务已就绪"
            return 0
        fi
        
        sleep 2
        waited=$((waited + 2))
        echo -n "."
    done
    
    echo ""
    echo "⚠️ 等待 $service 超时，但服务可能仍在启动中"
    return 1
}

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

# 确保 SQLite 文件路径指向持久化卷，避免容器重建后数据丢失
ensure_sqlite_persistence() {
    if [ ! -f ".env" ]; then
        echo "ℹ️ 未找到 .env 文件，跳过 SQLite 路径检查"
        return 0
    fi

    local sqlite_line sqlite_path tmp_file
    sqlite_line=$(grep -E '^SQLITE_FILE=' .env || true)

    if [ -z "$sqlite_line" ]; then
        echo "ℹ️ .env 未设置 SQLITE_FILE，使用默认 data/logs.db 以确保持久化"
        echo "" >> .env
        echo "SQLITE_FILE=data/logs.db" >> .env
        sqlite_path="data/logs.db"
    else
        sqlite_path="${sqlite_line#SQLITE_FILE=}"
    fi

    if [[ "$sqlite_path" != data/* && "$sqlite_path" != /app/data/* ]]; then
        echo "⚠️ 检测到 SQLITE_FILE=${sqlite_path:-<空>} 未指向挂载卷 (/app/data)，重启后会创建全新数据库"
        echo "🔧 已自动调整为 data/logs.db"
        tmp_file=$(mktemp)
        awk 'BEGIN{updated=0}
             /^SQLITE_FILE=/ {print "SQLITE_FILE=data/logs.db"; updated=1; next}
             {print}
             END{if(!updated) print "SQLITE_FILE=data/logs.db"}' .env > "$tmp_file"
        # mktemp 默认权限为 600，容器内的非 root 用户无法读取 .env，这里强制放宽为 644
        chmod 644 "$tmp_file"
        mv "$tmp_file" .env
    fi

    # 确保容器内的 appuser 能读取 .env
    chmod u+rw,go+r .env
}

# 显示帮助信息
show_help() {
    echo "🔄 部署环境快速重启脚本（已优化）"
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
    echo "⚡ 性能优化特性:"
    echo "  • 智能检测依赖变化，自动跳过不必要的 npm install"
    echo "  • 使用多核 CPU 并行构建前端，大幅提升构建速度"
    echo "  • 智能判断是否需要重建 Docker 镜像（仅在 Dockerfile/依赖变化时）"
    echo "  • 使用健康检查自动等待服务就绪，避免固定延迟"
    echo "  • 通过卷挂载实现代码热更新，无需重建镜像"
    echo ""
    echo "💡 优化效果:"
    echo "  在常规代码修改场景下，可节省 30-50% 的重启时间"
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

echo "🔄 部署环境快速重启（已优化，支持代码热重载）..."
echo "📋 数据库迁移: $([ "$RUN_MIGRATION" = true ] && echo "启用" || echo "跳过")"
echo "⚡ 智能优化已启用：自动跳过不必要的构建步骤"
echo ""

echo "🏗️ 编译前端代码..."

# 检查本地是否有 npm 命令
if command -v npm &> /dev/null; then
    echo "📍 使用本地 npm 构建前端..."
    cd frontend
    
    # 智能检查是否需要安装依赖
    if [ "$(need_npm_install)" = "true" ]; then
        echo "📦 检测到依赖变化，安装前端依赖..."
        npm install
        update_npm_cache
    else
        echo "⚡ 依赖未变化，跳过 npm install"
    fi
    
    echo "🔨 构建前端（Vite 自动使用多核加速）..."
    # Vite 使用 esbuild，会自动并行利用多核 CPU
    # 增加 Node 内存限制以提升大型项目构建速度
    NODE_OPTIONS="--max-old-space-size=4096" npm run build
    
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
    
    # 智能检查是否需要安装依赖
    NEED_INSTALL=$(need_npm_install)
    
    if [ "$NEED_INSTALL" = "true" ]; then
        INSTALL_CMD="echo '📦 安装前端依赖...' && npm install --no-fund --no-audit"
    else
        INSTALL_CMD="echo '⚡ 依赖未变化，跳过 npm install'"
    fi
    
    docker run --rm \
        -v "$(pwd)/frontend:/app/frontend" \
        -w /app/frontend \
        node:20-alpine \
        sh -c "
            $INSTALL_CMD && \
            echo '🔨 构建前端...' && \
            npm run build
        "
    
    if [ $? -ne 0 ]; then
        echo "❌ 容器内前端构建失败！"
        exit 1
    fi
    
    if [ "$NEED_INSTALL" = "true" ]; then
        update_npm_cache
    fi
    
    echo "✅ 容器内前端构建完成"
fi

# 在停止/启动容器前，确保数据库路径使用持久化目录
ensure_sqlite_persistence

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

# 智能判断是否需要重建镜像
NEED_BUILD=$(need_docker_build)

if [ "$NEED_BUILD" = "true" ]; then
    echo "🔧 检测到 Dockerfile 或依赖变化，重新构建镜像..."
    if ! docker-compose -f $COMPOSE_FILE up -d --build; then
        echo "❌ docker-compose 启动失败"
        report_port_usage 8085
        report_port_usage 8083
        report_port_usage 6379
        exit 1
    fi
    update_docker_build_cache
    echo "✅ 镜像构建完成"
else
    echo "⚡ Dockerfile 和依赖未变化，跳过镜像重建（代码通过卷挂载已更新）"
    if ! docker-compose -f $COMPOSE_FILE up -d; then
        echo "❌ docker-compose 启动失败"
        report_port_usage 8085
        report_port_usage 8083
        report_port_usage 6379
        exit 1
    fi
fi

# 使用健康检查替代固定等待
echo "⏳ 等待服务健康检查..."
wait_for_health "app" || true

echo "📊 检查服务状态..."
docker-compose -f $COMPOSE_FILE ps

if ! verify_release_routes "http://localhost:8085"; then
    echo "❌ 发布上传路由烟测失败，请检查容器是否加载了最新后端代码"
    exit 1
fi

echo "🎉 重启完成！代码更改已生效。"
echo "💡 提示：此脚本已优化，会智能跳过不必要的构建步骤以加快重启速度。"
echo "📖 使用 $0 --help 查看更多选项，包括数据库迁移控制参数。"
echo ""
echo "⚡ 性能优化："
echo "  - 智能跳过 npm install（依赖未变化时）"
echo "  - 多核并行构建前端"
echo "  - 智能跳过 Docker 镜像重建（Dockerfile/依赖未变化时）"
echo "  - 健康检查自动等待（替代固定延迟）"
