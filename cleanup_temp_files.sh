#!/bin/bash

# 临时文件清理脚本
# 用于诊断和清理残留的临时文件

set -e

# 颜色定义
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# 容器名称
CONTAINER_NAME="log-staging-service"

echo -e "${BLUE}================================${NC}"
echo -e "${BLUE}临时文件清理脚本${NC}"
echo -e "${BLUE}================================${NC}"
echo ""

# 检查 Docker 容器是否运行
if ! docker ps | grep -q "$CONTAINER_NAME"; then
    echo -e "${RED}错误: Docker 容器 $CONTAINER_NAME 未运行${NC}"
    exit 1
fi

# 功能1: 检查临时目录状态
check_temp_directories() {
    echo -e "${BLUE}[1] 检查临时目录状态...${NC}"
    echo ""
    
    echo -e "${YELLOW}临时目录总大小:${NC}"
    docker exec $CONTAINER_NAME du -sh /app/temp
    echo ""
    
    echo -e "${YELLOW}各子目录大小:${NC}"
    docker exec $CONTAINER_NAME du -sh /app/temp/* 2>/dev/null || echo "  (空目录)"
    echo ""
    
    echo -e "${YELLOW}processing_* 目录数量:${NC}"
    count=$(docker exec $CONTAINER_NAME sh -c "ls -d /app/temp/processing_* 2>/dev/null | wc -l" || echo "0")
    echo "  $count 个"
    
    if [ "$count" -gt 0 ]; then
        echo ""
        echo -e "${YELLOW}processing_* 目录列表:${NC}"
        docker exec $CONTAINER_NAME ls -lh /app/temp/ | grep processing_ || true
    fi
    echo ""
}

# 功能2: 通过 API 清理
cleanup_via_api() {
    echo -e "${BLUE}[2] 通过 API 清理临时文件...${NC}"
    echo ""
    
    read -p "输入 processing_* 目录保留时间（小时，默认24）: " processing_age
    processing_age=${processing_age:-24}
    
    read -p "输入 extracted 目录保留时间（小时，默认48）: " extracted_age
    extracted_age=${extracted_age:-48}
    
    echo ""
    echo -e "${YELLOW}调用清理 API...${NC}"
    
    # 获取容器内的端口
    PORT=$(docker exec $CONTAINER_NAME sh -c 'echo $PORT' 2>/dev/null || echo "8085")
    
    result=$(docker exec $CONTAINER_NAME curl -s -X POST \
        "http://localhost:${PORT}/cleanup/temp-directories?processing_max_age=${processing_age}&extracted_max_age=${extracted_age}")
    
    echo "$result" | python3 -m json.tool 2>/dev/null || echo "$result"
    echo ""
}

# 功能3: 手动强制清理
force_cleanup() {
    echo -e "${BLUE}[3] 手动强制清理（危险操作）${NC}"
    echo ""
    echo -e "${RED}警告: 此操作将删除所有 processing_* 目录，包括正在处理的任务！${NC}"
    echo -e "${RED}请确保没有正在运行的日志处理任务。${NC}"
    echo ""
    
    read -p "是否继续？(输入 YES 确认): " confirm
    
    if [ "$confirm" != "YES" ]; then
        echo "已取消"
        return
    fi
    
    echo ""
    echo -e "${YELLOW}删除所有 processing_* 目录...${NC}"
    docker exec $CONTAINER_NAME sh -c "rm -rf /app/temp/processing_*" && \
        echo -e "${GREEN}✓ 清理完成${NC}" || \
        echo -e "${RED}✗ 清理失败${NC}"
    
    echo ""
    echo -e "${YELLOW}删除后的临时目录大小:${NC}"
    docker exec $CONTAINER_NAME du -sh /app/temp
    echo ""
}

# 功能4: 检查正在运行的任务
check_running_tasks() {
    echo -e "${BLUE}[4] 检查正在运行的任务...${NC}"
    echo ""
    
    echo -e "${YELLOW}Celery worker 进程:${NC}"
    docker exec $CONTAINER_NAME ps aux | grep "celery worker" | grep -v grep || echo "  (无)"
    echo ""
    
    echo -e "${YELLOW}tool_log_decompress 进程:${NC}"
    docker exec $CONTAINER_NAME ps aux | grep "tool_log_decompress" | grep -v grep || echo "  (无)"
    echo ""
    
    echo -e "${YELLOW}Python 处理进程:${NC}"
    docker exec $CONTAINER_NAME ps aux | grep "python.*processing" | grep -v grep || echo "  (无)"
    echo ""
}

# 功能5: 查看最近的日志
view_logs() {
    echo -e "${BLUE}[5] 查看最近的清理相关日志...${NC}"
    echo ""
    
    docker logs --tail 50 $CONTAINER_NAME 2>&1 | grep -i "清理\|cleanup\|delete" || echo "  (无相关日志)"
    echo ""
}

# 功能6: 显示详细的目录信息
detailed_directory_info() {
    echo -e "${BLUE}[6] 显示详细的目录信息...${NC}"
    echo ""
    
    echo -e "${YELLOW}查找所有 processing_* 目录的详细信息:${NC}"
    docker exec $CONTAINER_NAME find /app/temp -type d -name "processing_*" -exec sh -c '
        for dir; do
            echo "----------------------------------------"
            echo "目录: $dir"
            echo "大小: $(du -sh "$dir" | cut -f1)"
            echo "修改时间: $(stat -c %y "$dir" 2>/dev/null || stat -f %Sm "$dir")"
            echo "文件数量: $(find "$dir" -type f | wc -l)"
            echo ""
        done
    ' sh {} +
    echo ""
}

# 主菜单
show_menu() {
    echo -e "${GREEN}请选择操作:${NC}"
    echo "  1. 检查临时目录状态"
    echo "  2. 通过 API 清理（推荐）"
    echo "  3. 手动强制清理（危险）"
    echo "  4. 检查正在运行的任务"
    echo "  5. 查看最近的日志"
    echo "  6. 显示详细的目录信息"
    echo "  7. 执行全部检查"
    echo "  0. 退出"
    echo ""
}

# 执行全部检查
run_all_checks() {
    check_temp_directories
    check_running_tasks
    view_logs
    
    echo -e "${GREEN}全部检查完成${NC}"
    echo ""
    
    read -p "是否执行 API 清理？(y/N): " do_cleanup
    if [ "$do_cleanup" = "y" ] || [ "$do_cleanup" = "Y" ]; then
        cleanup_via_api
    fi
}

# 主循环
while true; do
    show_menu
    read -p "请输入选项 (0-7): " choice
    echo ""
    
    case $choice in
        1)
            check_temp_directories
            ;;
        2)
            cleanup_via_api
            ;;
        3)
            force_cleanup
            ;;
        4)
            check_running_tasks
            ;;
        5)
            view_logs
            ;;
        6)
            detailed_directory_info
            ;;
        7)
            run_all_checks
            ;;
        0)
            echo "退出"
            exit 0
            ;;
        *)
            echo -e "${RED}无效的选项${NC}"
            echo ""
            ;;
    esac
    
    read -p "按 Enter 继续..."
    echo ""
    echo ""
done

