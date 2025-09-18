#!/bin/bash

# LogStagingService 备份脚本
# 用于备份数据库、日志文件和配置

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

# 配置
BACKUP_DIR="backups"
TIMESTAMP=$(date +%Y%m%d_%H%M%S)
BACKUP_NAME="logstagingservice_backup_$TIMESTAMP"
BACKUP_PATH="$BACKUP_DIR/$BACKUP_NAME"

# 创建备份目录
create_backup_dir() {
    log_info "创建备份目录: $BACKUP_PATH"
    mkdir -p $BACKUP_PATH
}

# 备份数据库
backup_database() {
    log_info "备份PostgreSQL数据库..."
    
    if docker-compose ps postgres | grep -q "Up"; then
        # 获取数据库连接信息
        DB_NAME=${POSTGRES_DB:-logstagingservice}
        DB_USER=${POSTGRES_USER:-postgres}
        
        # 备份数据库
        docker-compose exec -T postgres pg_dump -U $DB_USER $DB_NAME > $BACKUP_PATH/database.sql
        
        # 压缩数据库备份
        gzip $BACKUP_PATH/database.sql
        
        log_success "数据库备份完成: database.sql.gz"
    else
        log_warning "PostgreSQL服务未运行，跳过数据库备份"
    fi
}

# 备份Redis数据
backup_redis() {
    log_info "备份Redis数据..."
    
    if docker-compose ps redis | grep -q "Up"; then
        # 触发Redis保存
        docker-compose exec redis redis-cli BGSAVE
        
        # 等待保存完成
        sleep 5
        
        # 复制Redis数据文件
        docker-compose exec redis cat /data/dump.rdb > $BACKUP_PATH/redis_dump.rdb
        
        log_success "Redis备份完成: redis_dump.rdb"
    else
        log_warning "Redis服务未运行，跳过Redis备份"
    fi
}

# 备份应用日志
backup_logs() {
    log_info "备份应用日志..."
    
    if [ -d "logs" ] && [ "$(ls -A logs)" ]; then
        cp -r logs $BACKUP_PATH/
        
        # 压缩日志文件
        tar -czf $BACKUP_PATH/logs.tar.gz -C $BACKUP_PATH logs
        rm -rf $BACKUP_PATH/logs
        
        log_success "日志备份完成: logs.tar.gz"
    else
        log_warning "日志目录为空或不存在，跳过日志备份"
    fi
}

# 备份上传文件
backup_uploads() {
    log_info "备份上传文件..."
    
    if [ -d "uploads" ] && [ "$(ls -A uploads)" ]; then
        cp -r uploads $BACKUP_PATH/
        
        # 压缩上传文件
        tar -czf $BACKUP_PATH/uploads.tar.gz -C $BACKUP_PATH uploads
        rm -rf $BACKUP_PATH/uploads
        
        log_success "上传文件备份完成: uploads.tar.gz"
    else
        log_warning "上传目录为空或不存在，跳过上传文件备份"
    fi
}

# 备份配置文件
backup_configs() {
    log_info "备份配置文件..."
    
    mkdir -p $BACKUP_PATH/configs
    
    # 备份环境配置
    if [ -f ".env" ]; then
        cp .env $BACKUP_PATH/configs/
    fi
    
    # 备份Docker配置
    if [ -f "docker-compose.yml" ]; then
        cp docker-compose.yml $BACKUP_PATH/configs/
    fi
    
    if [ -f "docker-compose.dev.yml" ]; then
        cp docker-compose.dev.yml $BACKUP_PATH/configs/
    fi
    
    # 备份Nginx配置
    if [ -d "docker/nginx" ]; then
        cp -r docker/nginx $BACKUP_PATH/configs/
    fi
    
    # 备份Alembic配置
    if [ -f "alembic.ini" ]; then
        cp alembic.ini $BACKUP_PATH/configs/
    fi
    
    if [ -d "alembic" ]; then
        cp -r alembic $BACKUP_PATH/configs/
    fi
    
    log_success "配置文件备份完成"
}

# 备份Docker数据卷
backup_volumes() {
    log_info "备份Docker数据卷..."
    
    mkdir -p $BACKUP_PATH/volumes
    
    # 获取项目名称
    PROJECT_NAME=$(basename $(pwd) | tr '[:upper:]' '[:lower:]')
    
    # 备份各个数据卷
    for volume in postgres_data redis_data app_data; do
        volume_name="${PROJECT_NAME}_${volume}"
        
        if docker volume ls | grep -q $volume_name; then
            log_info "备份数据卷: $volume_name"
            
            # 创建临时容器来备份数据卷
            docker run --rm -v $volume_name:/data -v $(pwd)/$BACKUP_PATH/volumes:/backup alpine \
                tar -czf /backup/${volume}.tar.gz -C /data .
            
            log_success "数据卷 $volume_name 备份完成"
        else
            log_warning "数据卷 $volume_name 不存在"
        fi
    done
}

# 创建备份信息文件
create_backup_info() {
    log_info "创建备份信息文件..."
    
    cat > $BACKUP_PATH/backup_info.txt << EOF
LogStagingService 备份信息
========================

备份时间: $(date)
备份名称: $BACKUP_NAME
备份路径: $BACKUP_PATH

系统信息:
- 操作系统: $(uname -s)
- 架构: $(uname -m)
- Docker版本: $(docker --version)
- Docker Compose版本: $(docker-compose --version)

服务状态:
$(docker-compose ps)

备份内容:
- database.sql.gz: PostgreSQL数据库备份
- redis_dump.rdb: Redis数据备份
- logs.tar.gz: 应用日志备份
- uploads.tar.gz: 上传文件备份
- configs/: 配置文件备份
- volumes/: Docker数据卷备份

恢复说明:
1. 恢复数据库: gunzip -c database.sql.gz | docker-compose exec -T postgres psql -U postgres -d logstagingservice
2. 恢复Redis: docker-compose exec redis redis-cli FLUSHALL && docker cp redis_dump.rdb container_name:/data/
3. 恢复日志: tar -xzf logs.tar.gz
4. 恢复上传文件: tar -xzf uploads.tar.gz
5. 恢复配置: 复制configs/目录下的文件到相应位置
6. 恢复数据卷: tar -xzf volumes/volume_name.tar.gz
EOF
    
    log_success "备份信息文件创建完成"
}

# 压缩整个备份
compress_backup() {
    log_info "压缩备份文件..."
    
    cd $BACKUP_DIR
    tar -czf ${BACKUP_NAME}.tar.gz $BACKUP_NAME
    rm -rf $BACKUP_NAME
    cd ..
    
    log_success "备份压缩完成: $BACKUP_DIR/${BACKUP_NAME}.tar.gz"
}

# 清理旧备份
cleanup_old_backups() {
    local keep_days=${1:-7}
    
    log_info "清理 $keep_days 天前的备份..."
    
    if [ -d "$BACKUP_DIR" ]; then
        find $BACKUP_DIR -name "logstagingservice_backup_*.tar.gz" -mtime +$keep_days -delete
        log_success "旧备份清理完成"
    fi
}

# 恢复备份
restore_backup() {
    local backup_file=$1
    
    if [ -z "$backup_file" ]; then
        log_error "请指定备份文件"
        echo "用法: $0 restore <backup_file.tar.gz>"
        exit 1
    fi
    
    if [ ! -f "$backup_file" ]; then
        log_error "备份文件不存在: $backup_file"
        exit 1
    fi
    
    log_warning "恢复备份将覆盖现有数据！"
    read -p "确定要继续吗？(y/N): " -n 1 -r
    echo
    
    if [[ ! $REPLY =~ ^[Yy]$ ]]; then
        log_info "操作已取消"
        exit 0
    fi
    
    log_info "恢复备份: $backup_file"
    
    # 解压备份文件
    local restore_dir="restore_$(date +%Y%m%d_%H%M%S)"
    mkdir -p $restore_dir
    tar -xzf $backup_file -C $restore_dir
    
    local backup_name=$(basename $backup_file .tar.gz)
    local backup_path="$restore_dir/$backup_name"
    
    # 恢复数据库
    if [ -f "$backup_path/database.sql.gz" ]; then
        log_info "恢复数据库..."
        gunzip -c $backup_path/database.sql.gz | docker-compose exec -T postgres psql -U postgres -d logstagingservice
        log_success "数据库恢复完成"
    fi
    
    # 恢复Redis
    if [ -f "$backup_path/redis_dump.rdb" ]; then
        log_info "恢复Redis数据..."
        docker-compose exec redis redis-cli FLUSHALL
        docker cp $backup_path/redis_dump.rdb $(docker-compose ps -q redis):/data/dump.rdb
        docker-compose restart redis
        log_success "Redis数据恢复完成"
    fi
    
    # 恢复日志
    if [ -f "$backup_path/logs.tar.gz" ]; then
        log_info "恢复日志文件..."
        tar -xzf $backup_path/logs.tar.gz
        log_success "日志文件恢复完成"
    fi
    
    # 恢复上传文件
    if [ -f "$backup_path/uploads.tar.gz" ]; then
        log_info "恢复上传文件..."
        tar -xzf $backup_path/uploads.tar.gz
        log_success "上传文件恢复完成"
    fi
    
    # 清理临时文件
    rm -rf $restore_dir
    
    log_success "备份恢复完成"
}

# 列出可用备份
list_backups() {
    log_info "可用备份列表："
    
    if [ -d "$BACKUP_DIR" ]; then
        ls -la $BACKUP_DIR/*.tar.gz 2>/dev/null || log_warning "没有找到备份文件"
    else
        log_warning "备份目录不存在"
    fi
}

# 主函数
main() {
    case ${1:-backup} in
        backup)
            log_info "开始备份 LogStagingService..."
            
            create_backup_dir
            backup_database
            backup_redis
            backup_logs
            backup_uploads
            backup_configs
            backup_volumes
            create_backup_info
            compress_backup
            
            # 清理旧备份（保留7天）
            cleanup_old_backups 7
            
            log_success "备份完成: $BACKUP_DIR/${BACKUP_NAME}.tar.gz"
            ;;
        restore)
            restore_backup $2
            ;;
        list)
            list_backups
            ;;
        cleanup)
            local days=${2:-7}
            cleanup_old_backups $days
            ;;
        -h|--help)
            echo "用法: $0 [命令] [选项]"
            echo ""
            echo "命令:"
            echo "  backup              - 创建完整备份（默认）"
            echo "  restore <file>      - 恢复指定备份"
            echo "  list                - 列出可用备份"
            echo "  cleanup [days]      - 清理旧备份（默认7天）"
            echo ""
            echo "示例:"
            echo "  $0                                    # 创建备份"
            echo "  $0 restore backups/backup.tar.gz     # 恢复备份"
            echo "  $0 list                               # 列出备份"
            echo "  $0 cleanup 30                         # 清理30天前的备份"
            exit 0
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