#!/bin/bash

# LogStagingService 快速启动脚本
# 用于快速启动开发环境

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

# 检查Docker是否运行
check_docker() {
    if ! docker info >/dev/null 2>&1; then
        log_error "Docker未运行，请启动Docker"
        exit 1
    fi
}

# 设置环境变量
setup_env() {
    if [ ! -f ".env" ]; then
        log_info "创建环境变量文件..."
        if [ -f ".env.development" ]; then
            cp .env.development .env
        elif [ -f ".env.template" ]; then
            cp .env.template .env
        else
            log_error "找不到环境变量模板文件"
            exit 1
        fi
        log_success "环境变量文件已创建"
    fi
}

# 创建必要目录
create_dirs() {
    log_info "创建必要目录..."
    mkdir -p logs temp uploads backups
    chmod 755 logs temp uploads backups
}

# 快速启动
quick_start() {
    log_info "快速启动 LogStagingService 开发环境..."
    
    check_docker
    setup_env
    create_dirs
    
    log_info "启动服务..."
    docker-compose up -d
    
    log_info "等待服务就绪..."
    sleep 15
    
    # 检查服务状态
    if curl -f http://localhost:8085/health >/dev/null 2>&1; then
        log_success "服务启动成功！"
        
        echo ""
        echo "🎉 LogStagingService 已启动！"
        echo ""
        echo "📋 服务访问地址："
        echo "  🌐 主应用: http://localhost:8085"
        echo "  📚 API文档: http://localhost:8085/docs"
        echo "  ❤️  健康检查: http://localhost:8085/health"
        echo "  🔧 数据库管理: http://localhost:8080"
        echo "  🔴 Redis管理: http://localhost:8081"
        echo "  🌍 Nginx代理: http://localhost"
        echo ""
        echo "📊 查看服务状态: docker-compose ps"
        echo "📝 查看日志: ./scripts/logs.sh"
        echo "🔄 重启服务: ./scripts/restart.sh"
        echo "⏹️  停止服务: ./scripts/stop.sh"
        echo ""
    else
        log_warning "服务可能还在启动中，请稍后检查"
        echo "使用以下命令检查状态："
        echo "  docker-compose ps"
        echo "  ./scripts/logs.sh"
    fi
}

# 主函数
main() {
    case ${1:-start} in
        start)
            quick_start
            ;;
        stop)
            log_info "停止所有服务..."
            docker-compose down
            log_success "服务已停止"
            ;;
        restart)
            log_info "重启所有服务..."
            docker-compose restart
            log_success "服务已重启"
            ;;
        status)
            log_info "服务状态："
            docker-compose ps
            ;;
        logs)
            docker-compose logs -f
            ;;
        clean)
            log_warning "清理所有容器和数据..."
            read -p "确定要清理所有数据吗？(y/N): " -n 1 -r
            echo
            if [[ $REPLY =~ ^[Yy]$ ]]; then
                docker-compose down -v --remove-orphans
                docker system prune -f
                log_success "清理完成"
            else
                log_info "操作已取消"
            fi
            ;;
        -h|--help)
            echo "LogStagingService 快速启动脚本"
            echo ""
            echo "用法: $0 [命令]"
            echo ""
            echo "命令:"
            echo "  start     - 启动服务（默认）"
            echo "  stop      - 停止服务"
            echo "  restart   - 重启服务"
            echo "  status    - 查看服务状态"
            echo "  logs      - 查看实时日志"
            echo "  clean     - 清理所有容器和数据"
            echo "  -h, --help - 显示帮助信息"
            ;;
        *)
            log_error "未知命令: $1"
            echo "使用 '$0 --help' 查看帮助信息"
            exit 1
            ;;
    esac
}

# 执行主函数
main "$@"