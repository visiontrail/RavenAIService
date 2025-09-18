#!/bin/bash

# LogStagingService 部署脚本
# 用于构建和部署整个应用栈

set -e  # 遇到错误立即退出

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

# 检查Docker和Docker Compose是否安装
check_dependencies() {
    log_info "检查依赖..."
    
    if ! command -v docker &> /dev/null; then
        log_error "Docker 未安装，请先安装 Docker"
        exit 1
    fi
    
    if ! command -v docker-compose &> /dev/null; then
        log_error "Docker Compose 未安装，请先安装 Docker Compose"
        exit 1
    fi
    
    log_success "依赖检查通过"
}

# 检查环境变量文件
check_env_file() {
    log_info "检查环境变量文件..."
    
    if [ ! -f ".env" ]; then
        if [ -f ".env.example" ]; then
            log_warning ".env 文件不存在，从 .env.example 复制"
            cp .env.example .env
            log_warning "请编辑 .env 文件设置正确的环境变量"
        else
            log_error ".env 和 .env.example 文件都不存在"
            exit 1
        fi
    fi
    
    log_success "环境变量文件检查完成"
}

# 创建必要的目录
create_directories() {
    log_info "创建必要的目录..."
    
    mkdir -p logs temp uploads
    mkdir -p docker/nginx/ssl
    
    # 设置目录权限
    chmod 755 logs temp uploads
    
    log_success "目录创建完成"
}

# 生成SSL证书（自签名，用于开发）
generate_ssl_cert() {
    log_info "检查SSL证书..."
    
    if [ ! -f "docker/nginx/ssl/cert.pem" ] || [ ! -f "docker/nginx/ssl/key.pem" ]; then
        log_warning "SSL证书不存在，生成自签名证书..."
        
        openssl req -x509 -nodes -days 365 -newkey rsa:2048 \
            -keyout docker/nginx/ssl/key.pem \
            -out docker/nginx/ssl/cert.pem \
            -subj "/C=CN/ST=Beijing/L=Beijing/O=LogStagingService/CN=localhost"
        
        log_success "SSL证书生成完成"
    else
        log_success "SSL证书已存在"
    fi
}

# 构建前端（如果存在）
build_frontend() {
    if [ -d "frontend" ]; then
        log_info "构建前端..."
        
        cd frontend
        
        if [ -f "package.json" ]; then
            npm install
            npm run build
            log_success "前端构建完成"
        else
            log_warning "前端 package.json 不存在，跳过前端构建"
        fi
        
        cd ..
    else
        log_warning "前端目录不存在，跳过前端构建"
    fi
}

# 停止现有服务
stop_services() {
    log_info "停止现有服务..."
    
    docker-compose down --remove-orphans || true
    
    log_success "现有服务已停止"
}

# 构建镜像
build_images() {
    log_info "构建Docker镜像..."
    
    docker-compose build --no-cache
    
    log_success "镜像构建完成"
}

# 启动服务
start_services() {
    log_info "启动服务..."
    
    docker-compose up -d
    
    log_success "服务启动完成"
}

# 等待服务就绪
wait_for_services() {
    log_info "等待服务就绪..."
    
    # 等待数据库就绪
    log_info "等待数据库启动..."
    sleep 10
    
    # 检查服务健康状态
    max_attempts=30
    attempt=0
    
    while [ $attempt -lt $max_attempts ]; do
        if curl -f http://localhost:8085/health &> /dev/null; then
            log_success "应用服务就绪"
            break
        fi
        
        attempt=$((attempt + 1))
        log_info "等待应用服务就绪... ($attempt/$max_attempts)"
        sleep 5
    done
    
    if [ $attempt -eq $max_attempts ]; then
        log_error "应用服务启动超时"
        exit 1
    fi
}

# 运行数据库迁移
run_migrations() {
    log_info "运行数据库迁移..."
    
    docker-compose exec app alembic upgrade head
    
    log_success "数据库迁移完成"
}

# 显示服务状态
show_status() {
    log_info "服务状态："
    docker-compose ps
    
    echo ""
    log_info "服务访问地址："
    echo "  - 应用服务: http://localhost:8085"
    echo "  - API文档: http://localhost:8085/docs"
    echo "  - 健康检查: http://localhost:8085/health"
    echo "  - Nginx代理: http://localhost"
    echo "  - HTTPS访问: https://localhost"
}

# 主函数
main() {
    log_info "开始部署 LogStagingService..."
    
    # 解析命令行参数
    SKIP_BUILD=false
    SKIP_FRONTEND=false
    
    while [[ $# -gt 0 ]]; do
        case $1 in
            --skip-build)
                SKIP_BUILD=true
                shift
                ;;
            --skip-frontend)
                SKIP_FRONTEND=true
                shift
                ;;
            -h|--help)
                echo "用法: $0 [选项]"
                echo "选项:"
                echo "  --skip-build     跳过镜像构建"
                echo "  --skip-frontend  跳过前端构建"
                echo "  -h, --help       显示帮助信息"
                exit 0
                ;;
            *)
                log_error "未知选项: $1"
                exit 1
                ;;
        esac
    done
    
    check_dependencies
    check_env_file
    create_directories
    generate_ssl_cert
    
    if [ "$SKIP_FRONTEND" = false ]; then
        build_frontend
    fi
    
    stop_services
    
    if [ "$SKIP_BUILD" = false ]; then
        build_images
    fi
    
    start_services
    wait_for_services
    run_migrations
    show_status
    
    log_success "部署完成！"
}

# 执行主函数
main "$@"