#!/bin/bash

# LogStagingService 日志查看脚本
# 用于查看各种服务的日志

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

# 查看指定服务日志
show_service_logs() {
    local service=$1
    local follow=${2:-false}
    local lines=${3:-100}
    
    log_info "查看服务日志: $service"
    
    if [ "$follow" = true ]; then
        docker-compose logs -f --tail=$lines $service
    else
        docker-compose logs --tail=$lines $service
    fi
}

# 查看所有服务日志
show_all_logs() {
    local follow=${1:-false}
    local lines=${2:-100}
    
    log_info "查看所有服务日志"
    
    if [ "$follow" = true ]; then
        docker-compose logs -f --tail=$lines
    else
        docker-compose logs --tail=$lines
    fi
}

# 查看应用日志文件
show_app_log_files() {
    log_info "查看应用日志文件："
    
    if [ -d "logs" ]; then
        echo "日志文件列表："
        ls -la logs/
        echo ""
        
        if [ -f "logs/app.log" ]; then
            echo "最新应用日志（最后50行）："
            tail -n 50 logs/app.log
        else
            log_warning "应用日志文件不存在"
        fi
    else
        log_warning "日志目录不存在"
    fi
}

# 查看Nginx日志
show_nginx_logs() {
    log_info "查看Nginx访问日志："
    
    # 从容器中获取Nginx日志
    if docker-compose ps nginx | grep -q "Up"; then
        echo "Nginx访问日志（最后50行）："
        docker-compose exec nginx tail -n 50 /var/log/nginx/access.log || true
        
        echo ""
        echo "Nginx错误日志（最后20行）："
        docker-compose exec nginx tail -n 20 /var/log/nginx/error.log || true
    else
        log_warning "Nginx服务未运行"
    fi
}

# 查看数据库日志
show_db_logs() {
    log_info "查看PostgreSQL日志："
    
    if docker-compose ps postgres | grep -q "Up"; then
        docker-compose logs --tail=50 postgres
    else
        log_warning "PostgreSQL服务未运行"
    fi
}

# 查看Redis日志
show_redis_logs() {
    log_info "查看Redis日志："
    
    if docker-compose ps redis | grep -q "Up"; then
        docker-compose logs --tail=50 redis
    else
        log_warning "Redis服务未运行"
    fi
}

# 查看Celery日志
show_celery_logs() {
    log_info "查看Celery Worker日志："
    
    if docker-compose ps celery_worker | grep -q "Up"; then
        docker-compose logs --tail=50 celery_worker
    else
        log_warning "Celery Worker服务未运行"
    fi
    
    echo ""
    log_info "查看Celery Beat日志："
    
    if docker-compose ps celery_beat | grep -q "Up"; then
        docker-compose logs --tail=50 celery_beat
    else
        log_warning "Celery Beat服务未运行"
    fi
}

# 实时监控所有日志
monitor_logs() {
    log_info "实时监控所有服务日志（按Ctrl+C退出）..."
    docker-compose logs -f
}

# 导出日志
export_logs() {
    local output_dir="logs_export_$(date +%Y%m%d_%H%M%S)"
    
    log_info "导出日志到目录: $output_dir"
    
    mkdir -p $output_dir
    
    # 导出Docker Compose日志
    docker-compose logs > $output_dir/docker_compose.log
    
    # 导出各服务日志
    for service in app redis postgres nginx celery_worker celery_beat; do
        if docker-compose ps $service | grep -q "Up"; then
            docker-compose logs $service > $output_dir/${service}.log
        fi
    done
    
    # 复制应用日志文件
    if [ -d "logs" ]; then
        cp -r logs $output_dir/app_logs
    fi
    
    # 创建日志摘要
    cat > $output_dir/README.md << EOF
# 日志导出摘要

导出时间: $(date)
导出目录: $output_dir

## 文件说明

- docker_compose.log: Docker Compose所有服务日志
- app.log: 主应用服务日志
- redis.log: Redis服务日志
- postgres.log: PostgreSQL服务日志
- nginx.log: Nginx服务日志
- celery_worker.log: Celery Worker服务日志
- celery_beat.log: Celery Beat服务日志
- app_logs/: 应用程序日志文件目录

## 服务状态

\`\`\`
$(docker-compose ps)
\`\`\`
EOF
    
    log_success "日志导出完成: $output_dir"
}

# 清理旧日志
clean_logs() {
    log_warning "清理应用日志文件..."
    
    read -p "确定要清理日志文件吗？(y/N): " -n 1 -r
    echo
    
    if [[ $REPLY =~ ^[Yy]$ ]]; then
        if [ -d "logs" ]; then
            find logs -name "*.log" -type f -exec truncate -s 0 {} \;
            log_success "日志文件已清理"
        else
            log_warning "日志目录不存在"
        fi
    else
        log_info "操作已取消"
    fi
}

# 主函数
main() {
    local follow=false
    local lines=100
    
    # 解析参数
    while [[ $# -gt 0 ]]; do
        case $1 in
            -f|--follow)
                follow=true
                shift
                ;;
            -n|--lines)
                lines=$2
                shift 2
                ;;
            app|redis|postgres|nginx|celery_worker|celery_beat)
                show_service_logs $1 $follow $lines
                exit 0
                ;;
            all)
                show_all_logs $follow $lines
                exit 0
                ;;
            files)
                show_app_log_files
                exit 0
                ;;
            nginx)
                show_nginx_logs
                exit 0
                ;;
            db)
                show_db_logs
                exit 0
                ;;
            celery)
                show_celery_logs
                exit 0
                ;;
            monitor)
                monitor_logs
                exit 0
                ;;
            export)
                export_logs
                exit 0
                ;;
            clean)
                clean_logs
                exit 0
                ;;
            -h|--help)
                echo "用法: $0 [选项] [服务名称|命令]"
                echo ""
                echo "服务名称:"
                echo "  app           - 主应用服务"
                echo "  redis         - Redis服务"
                echo "  postgres      - PostgreSQL服务"
                echo "  nginx         - Nginx服务"
                echo "  celery_worker - Celery Worker服务"
                echo "  celery_beat   - Celery Beat服务"
                echo ""
                echo "命令:"
                echo "  all           - 所有服务日志（默认）"
                echo "  files         - 应用日志文件"
                echo "  db            - 数据库日志"
                echo "  celery        - Celery相关日志"
                echo "  monitor       - 实时监控所有日志"
                echo "  export        - 导出所有日志"
                echo "  clean         - 清理日志文件"
                echo ""
                echo "选项:"
                echo "  -f, --follow  - 实时跟踪日志"
                echo "  -n, --lines   - 显示行数（默认100）"
                echo "  -h, --help    - 显示帮助信息"
                echo ""
                echo "示例:"
                echo "  $0 app -f              # 实时查看应用日志"
                echo "  $0 all -n 200          # 查看所有服务最后200行日志"
                echo "  $0 monitor             # 实时监控所有日志"
                exit 0
                ;;
            *)
                log_error "未知选项: $1"
                echo "使用 '$0 --help' 查看帮助信息"
                exit 1
                ;;
        esac
    done
    
    # 默认显示所有服务日志
    show_all_logs $follow $lines
}

# 执行主函数
main "$@"