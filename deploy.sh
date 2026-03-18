#!/bin/bash

# LogStagingService 部署脚本
# 用法: ./deploy.sh [clean]
# clean: 在容器内执行数据清理

set -e

# 颜色定义
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color
COMPOSE_FILE="docker-compose.yml"
LEGACY_PORT_COMPOSE_FILE="docker-compose.legacy-port.yml"
LEGACY_PORT="8083"
REQUIRED_PORTS=(8085 8083 6379)
KNOWN_LEGACY_PREFIXES=("log-staging-service" "logstagingservice")
COMPOSE_ARGS=(-f "$COMPOSE_FILE")
LEGACY_PORT_ENABLED=false

compose() {
    docker-compose "${COMPOSE_ARGS[@]}" "$@"
}

# 日志函数
log_info() {
    echo -e "${BLUE}[INFO]${NC} $1"
}

log_success() {
    echo -e "${GREEN}[SUCCESS]${NC} $1"
}

log_warning() {
    echo -e "${YELLOW}[WARNING]${NC} $1"
}

log_error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

report_port_usage() {
    local port="$1"
    log_info "端口 ${port} 占用情况:"

    if command -v ss >/dev/null 2>&1; then
        ss -ltnp "( sport = :${port} )" 2>/dev/null || true
    elif command -v netstat >/dev/null 2>&1; then
        netstat -ltnp 2>/dev/null | grep ":${port} " || true
    else
        log_warning "未找到 ss/netstat，无法打印端口占用详情"
    fi

    if command -v docker >/dev/null 2>&1; then
        docker ps --format 'table {{.Names}}\t{{.Ports}}' | grep "${port}->" || true
    fi
}

is_host_port_in_use() {
    local port="$1"

    if command -v ss >/dev/null 2>&1; then
        ss -ltn "( sport = :${port} )" 2>/dev/null | awk 'NR > 1 { found=1 } END { exit(found ? 0 : 1) }'
        return $?
    fi

    if command -v lsof >/dev/null 2>&1; then
        lsof -Pi :"${port}" -sTCP:LISTEN -t >/dev/null 2>&1
        return $?
    fi

    if command -v netstat >/dev/null 2>&1; then
        netstat -ltn 2>/dev/null | awk -v port=":${port}" '$4 ~ port"$" { found=1 } END { exit(found ? 0 : 1) }'
        return $?
    fi

    return 1
}

list_port_containers() {
    local port="$1"

    if ! command -v docker >/dev/null 2>&1; then
        return 0
    fi

    docker ps --format '{{.Names}}\t{{.Ports}}' | awk -F '\t' -v port=":${port}->" '$2 ~ port {print $1}'
}

cleanup_known_legacy_conflicts() {
    if ! command -v docker >/dev/null 2>&1; then
        return 0
    fi

    local port prefix container
    local -a containers_to_remove=()
    declare -A seen=()

    for port in "${REQUIRED_PORTS[@]}"; do
        while IFS= read -r container; do
            [ -z "$container" ] && continue
            for prefix in "${KNOWN_LEGACY_PREFIXES[@]}"; do
                if [[ "$container" == "${prefix}-"* ]] && [ -z "${seen[$container]+x}" ]; then
                    containers_to_remove+=("$container")
                    seen["$container"]=1
                    break
                fi
            done
        done < <(list_port_containers "$port")
    done

    if [ "${#containers_to_remove[@]}" -eq 0 ]; then
        return 0
    fi

    log_info "检测到旧项目残留容器占用关键端口，准备清理:"
    printf '  - %s\n' "${containers_to_remove[@]}"

    if ! docker rm -f "${containers_to_remove[@]}"; then
        log_error "清理旧项目残留容器失败，请手动执行:"
        printf '  docker rm -f %s\n' "${containers_to_remove[@]}"
        exit 1
    fi

    for prefix in "${KNOWN_LEGACY_PREFIXES[@]}"; do
        docker network rm "${prefix}_default" >/dev/null 2>&1 || true
    done

    log_success "已清理旧项目残留容器，释放主端口供 Raven 使用"
}

configure_compose_args() {
    COMPOSE_ARGS=(-f "$COMPOSE_FILE")
    LEGACY_PORT_ENABLED=false

    if [ ! -f "$LEGACY_PORT_COMPOSE_FILE" ]; then
        return 0
    fi

    if is_host_port_in_use "$LEGACY_PORT"; then
        log_warning "宿主机端口 ${LEGACY_PORT} 已被其他服务占用，跳过旧版兼容端口映射"
        log_info "当前仍可通过 http://localhost:8085/raven 访问包管理入口"
        return 0
    fi

    COMPOSE_ARGS+=(-f "$LEGACY_PORT_COMPOSE_FILE")
    LEGACY_PORT_ENABLED=true
    export RAVEN_LEGACY_HOST_PORT="${RAVEN_LEGACY_HOST_PORT:-$LEGACY_PORT}"
    log_success "已启用旧版兼容端口映射: http://localhost:${RAVEN_LEGACY_HOST_PORT}"
}

# 检查 Docker 和 docker-compose 是否可用
check_dependencies() {
    if ! command -v docker &> /dev/null; then
        log_error "Docker 未安装或不在 PATH 中"
        exit 1
    fi

    if ! command -v docker-compose &> /dev/null; then
        log_error "docker-compose 未安装或不在 PATH 中"
        exit 1
    fi
}

# 同步 .env 到 .env.example（Compose 使用 .env.example 作为容器环境来源）
sync_env_file() {
    log_info "同步环境变量文件 (.env → .env.example)..."
    if [ -f ".env" ]; then
        if [ -f ".env.example" ]; then
            if cmp -s ".env" ".env.example"; then
                log_info "检测到 .env 无变化，跳过同步"
                return 0
            fi
            local backup_name=".env.example.bak_$(date +%Y%m%d%H%M%S)"
            cp ".env.example" "$backup_name"
            log_info "已备份 .env.example 为 $backup_name"
        fi
        cp ".env" ".env.example"
        log_success "已更新 .env.example（容器将使用最新环境变量）"
    else
        log_warning "未找到 .env 文件，跳过环境变量同步"
    fi
}

verify_release_routes() {
    log_info "校验发布上传路由是否已生效..."
    local base_url="${1:-http://localhost:8085}"
    local endpoints=("/admin/releases" "/admin/releases/upload")
    local failed=0

    for endpoint in "${endpoints[@]}"; do
        local status_code
        status_code=$(curl -s -o /dev/null -w "%{http_code}" -X POST "${base_url}${endpoint}" || echo "000")
        case "$status_code" in
            401|400|422)
                log_success "路由可用: POST ${endpoint} -> ${status_code}"
                ;;
            *)
                log_error "路由异常: POST ${endpoint} -> ${status_code} (期望 401/400/422，不能是 404/405)"
                failed=1
                ;;
        esac
    done

    return $failed
}

# 清理容器内的运行时数据
cleanup_container_data() {
    log_info "开始清理容器内的运行时数据..."
    cleanup_known_legacy_conflicts
    configure_compose_args
    
    # 检查容器是否运行
    if ! compose ps | grep -q "Up"; then
        log_warning "容器未运行，启动容器以执行清理..."
        compose up -d --build
        sleep 5
    fi
    
    # 确保清理脚本存在于容器中
    log_info "确保清理脚本在容器中可用..."
    if ! compose exec -T app test -f /app/cleanup_runtime_data.py; then
        log_info "拷贝清理脚本到容器..."
        if docker cp cleanup_runtime_data.py logstagingservice-app-1:/app/cleanup_runtime_data.py; then
            log_success "清理脚本已拷贝到容器"
        else
            log_error "拷贝清理脚本失败"
            exit 1
        fi
    fi
    
    # 设置清理脚本执行权限
    log_info "设置清理脚本执行权限..."
    if compose exec --user root app chmod +x /app/cleanup_runtime_data.py; then
        log_success "清理脚本权限设置完成"
    else
        log_error "设置清理脚本权限失败"
        exit 1
    fi
    
    # 在 app 容器内执行清理脚本
    log_info "在容器内执行清理脚本..."
    if compose exec -T app python cleanup_runtime_data.py -f --verbose; then
        log_success "容器内数据清理完成"
    else
        log_error "容器内数据清理失败"
        exit 1
    fi
    
    # 重启服务以确保清理生效
    log_info "重启服务..."
    compose restart app worker
    
    log_success "清理操作完成，服务已重启"
}

# 正常部署
deploy_services() {
    log_info "开始部署 LogStagingService..."
    
    # 同步环境变量文件，确保 .env 变更生效
    sync_env_file

    # 确保旧容器已停止
    log_info "确保旧容器已停止..."
    docker-compose -f "$COMPOSE_FILE" down 2>/dev/null || true
    cleanup_known_legacy_conflicts
    
    # 删除旧镜像以确保使用最新代码
    log_info "删除旧镜像以确保重新构建..."
    docker-compose -f "$COMPOSE_FILE" down --rmi local 2>/dev/null || true
    
    # 清理构建缓存（可选，但能确保完全重新构建）
    log_info "清理 Docker 构建缓存..."
    docker builder prune -f 2>/dev/null || true

    configure_compose_args
    
    # 强制重新构建并启动服务（使用 --no-cache 确保不使用缓存）
    log_info "重新构建镜像（不使用缓存）..."
    if compose build --no-cache; then
        log_success "镜像构建成功"
    else
        log_error "镜像构建失败"
        exit 1
    fi
    
    # 启动服务
    log_info "启动服务..."
    if compose up -d; then
        log_success "服务部署成功"
        
        # 等待服务启动
        log_info "等待服务启动..."
        sleep 10
        
        # 检查服务状态
        log_info "检查服务状态:"
        compose ps

        if verify_release_routes "http://localhost:8085"; then
            log_success "发布上传路由烟测通过"
        else
            log_error "发布上传路由烟测失败，请检查生产容器是否加载了最新后端代码"
            exit 1
        fi
        
        log_info "服务访问地址: http://localhost:8085"
        log_info "健康检查: http://localhost:8085/health"
        if [ "$LEGACY_PORT_ENABLED" = true ]; then
            log_info "旧版兼容端口: http://localhost:${RAVEN_LEGACY_HOST_PORT}"
        fi
    else
        log_error "服务部署失败"
        report_port_usage 8085
        report_port_usage 8083
        report_port_usage 6379
        exit 1
    fi
}

# 显示帮助信息
show_help() {
    echo "LogStagingService 部署脚本"
    echo ""
    echo "用法:"
    echo "  $0              # 正常部署服务"
    echo "  $0 clean        # 清理容器内运行时数据"
    echo "  $0 --help       # 显示此帮助信息"
    echo ""
    echo "说明:"
    echo "  clean 参数会在容器内执行 cleanup_runtime_data.py 脚本"
    echo "  清理所有运行时产生的数据，包括数据库、日志、临时文件等"
}

# 主函数
main() {
    # 检查依赖
    check_dependencies
    
    # 处理参数
    case "${1:-}" in
        "clean")
            cleanup_container_data
            ;;
        "--help"|"-h")
            show_help
            ;;
        "")
            deploy_services
            ;;
        *)
            log_error "未知参数: $1"
            echo ""
            show_help
            exit 1
            ;;
    esac
}

# 执行主函数
main "$@"
