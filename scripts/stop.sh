#!/bin/bash

# LogStagingService 停止脚本
# 用于停止所有或指定服务

set -e

# 颜色定义
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

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

# 停止指定服务
stop_service() {
    local service=$1
    log_info "停止服务: $service"
    
    docker-compose stop $service
    
    log_success "服务 $service 已停止"
}

# 停止所有服务
stop_all() {
    log_info "停止所有服务..."
    
    docker-compose down
    
    log_success "所有服务已停止"
}

# 停止所有服务并删除数据卷
stop_all_with_volumes() {
    log_warning "停止所有服务并删除数据卷..."
    log_warning "这将删除所有数据，包括数据库数据！"
    
    read -p "确定要继续吗？(y/N): " -n 1 -r
    echo
    
    if [[ $REPLY =~ ^[Yy]$ ]]; then
        docker-compose down -v --remove-orphans
        log_success "所有服务和数据卷已删除"
    else
        log_info "操作已取消"
    fi
}

# 停止所有服务并删除镜像
stop_all_with_images() {
    log_warning "停止所有服务并删除镜像..."
    
    read -p "确定要删除所有镜像吗？(y/N): " -n 1 -r
    echo
    
    if [[ $REPLY =~ ^[Yy]$ ]]; then
        docker-compose down --rmi all --remove-orphans
        log_success "所有服务和镜像已删除"
    else
        log_info "操作已取消"
    fi
}

# 强制停止所有容器
force_stop() {
    log_warning "强制停止所有相关容器..."
    
    # 获取项目名称
    PROJECT_NAME=$(basename $(pwd) | tr '[:upper:]' '[:lower:]')
    
    # 强制停止所有相关容器
    docker ps -a --filter "name=${PROJECT_NAME}" --format "{{.Names}}" | xargs -r docker stop
    docker ps -a --filter "name=${PROJECT_NAME}" --format "{{.Names}}" | xargs -r docker rm
    
    log_success "强制停止完成"
}

# 显示服务状态
show_status() {
    log_info "当前服务状态："
    docker-compose ps
}

# 主函数
main() {
    if [ $# -eq 0 ]; then
        stop_all
    else
        case $1 in
            app|redis|postgres|nginx|celery_worker|celery_beat)
                stop_service $1
                ;;
            all)
                stop_all
                ;;
            --with-volumes)
                stop_all_with_volumes
                ;;
            --with-images)
                stop_all_with_images
                ;;
            --force)
                force_stop
                ;;
            status)
                show_status
                exit 0
                ;;
            -h|--help)
                echo "用法: $0 [服务名称|选项]"
                echo ""
                echo "服务名称:"
                echo "  app           - 主应用服务"
                echo "  redis         - Redis服务"
                echo "  postgres      - PostgreSQL服务"
                echo "  nginx         - Nginx服务"
                echo "  celery_worker - Celery Worker服务"
                echo "  celery_beat   - Celery Beat服务"
                echo ""
                echo "选项:"
                echo "  all              - 停止所有服务（默认）"
                echo "  --with-volumes   - 停止服务并删除数据卷"
                echo "  --with-images    - 停止服务并删除镜像"
                echo "  --force          - 强制停止所有相关容器"
                echo "  status           - 显示服务状态"
                echo "  -h, --help       - 显示帮助信息"
                exit 0
                ;;
            *)
                log_error "未知选项: $1"
                echo "使用 '$0 --help' 查看可用选项"
                exit 1
                ;;
        esac
    fi
    
    show_status
}

# 执行主函数
main "$@"