#!/bin/bash

# LogStagingService 重启脚本
# 用于重启所有服务

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

# 重启指定服务
restart_service() {
    local service=$1
    log_info "重启服务: $service"
    
    docker-compose restart $service
    
    # 等待服务就绪
    sleep 5
    
    log_success "服务 $service 重启完成"
}

# 重启所有服务
restart_all() {
    log_info "重启所有服务..."
    
    docker-compose restart
    
    # 等待服务就绪
    log_info "等待服务就绪..."
    sleep 10
    
    # 检查应用服务健康状态
    max_attempts=20
    attempt=0
    
    while [ $attempt -lt $max_attempts ]; do
        if curl -f http://localhost:8085/health &> /dev/null; then
            log_success "应用服务就绪"
            break
        fi
        
        attempt=$((attempt + 1))
        log_info "等待应用服务就绪... ($attempt/$max_attempts)"
        sleep 3
    done
    
    if [ $attempt -eq $max_attempts ]; then
        log_warning "应用服务健康检查超时，请手动检查"
    fi
    
    log_success "所有服务重启完成"
}

# 显示服务状态
show_status() {
    log_info "当前服务状态："
    docker-compose ps
}

# 主函数
main() {
    if [ $# -eq 0 ]; then
        restart_all
    else
        case $1 in
            app|redis|postgres|nginx|celery_worker|celery_beat)
                restart_service $1
                ;;
            all)
                restart_all
                ;;
            status)
                show_status
                exit 0
                ;;
            -h|--help)
                echo "用法: $0 [服务名称|all|status]"
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
                echo "  all           - 重启所有服务（默认）"
                echo "  status        - 显示服务状态"
                echo "  -h, --help    - 显示帮助信息"
                exit 0
                ;;
            *)
                log_error "未知服务: $1"
                echo "使用 '$0 --help' 查看可用服务"
                exit 1
                ;;
        esac
    fi
    
    show_status
}

# 执行主函数
main "$@"