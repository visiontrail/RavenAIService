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

# 清理容器内的运行时数据
cleanup_container_data() {
    log_info "开始清理容器内的运行时数据..."
    
    # 检查容器是否运行
    if ! docker-compose ps | grep -q "Up"; then
        log_warning "容器未运行，启动容器以执行清理..."
        docker-compose up -d --build
        sleep 5
    fi
    
    # 确保清理脚本存在于容器中
    log_info "确保清理脚本在容器中可用..."
    if ! docker-compose exec -T app test -f /app/cleanup_runtime_data.py; then
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
    if docker-compose exec --user root app chmod +x /app/cleanup_runtime_data.py; then
        log_success "清理脚本权限设置完成"
    else
        log_error "设置清理脚本权限失败"
        exit 1
    fi
    
    # 在 app 容器内执行清理脚本
    log_info "在容器内执行清理脚本..."
    if docker-compose exec -T app python cleanup_runtime_data.py -f --verbose; then
        log_success "容器内数据清理完成"
    else
        log_error "容器内数据清理失败"
        exit 1
    fi
    
    # 重启服务以确保清理生效
    log_info "重启服务..."
    docker-compose restart app worker
    
    log_success "清理操作完成，服务已重启"
}

# 正常部署
deploy_services() {
    log_info "开始部署 LogStagingService..."
    
    # 同步环境变量文件，确保 .env 变更生效
    sync_env_file
    
    # 确保旧容器已停止
    log_info "确保旧容器已停止..."
    docker-compose down 2>/dev/null || true
    
    # 删除旧镜像以确保使用最新代码
    log_info "删除旧镜像以确保重新构建..."
    docker-compose down --rmi local 2>/dev/null || true
    
    # 清理构建缓存（可选，但能确保完全重新构建）
    log_info "清理 Docker 构建缓存..."
    docker builder prune -f 2>/dev/null || true
    
    # 强制重新构建并启动服务（使用 --no-cache 确保不使用缓存）
    log_info "重新构建镜像（不使用缓存）..."
    if docker-compose build --no-cache; then
        log_success "镜像构建成功"
    else
        log_error "镜像构建失败"
        exit 1
    fi
    
    # 启动服务
    log_info "启动服务..."
    if docker-compose up -d; then
        log_success "服务部署成功"
        
        # 等待服务启动
        log_info "等待服务启动..."
        sleep 10
        
        # 检查服务状态
        log_info "检查服务状态:"
        docker-compose ps
        
        log_info "服务访问地址: http://localhost:8085"
        log_info "健康检查: http://localhost:8085/health"
    else
        log_error "服务部署失败"
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