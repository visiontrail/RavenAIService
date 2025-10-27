#!/bin/bash

# LogStagingService 停止脚本
# 完全停止服务并清理容器

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

log_info "停止所有服务..."
docker-compose down

log_info "删除旧的镜像以确保下次重新构建..."
docker-compose down --rmi local 2>/dev/null || true

log_success "服务已完全停止"