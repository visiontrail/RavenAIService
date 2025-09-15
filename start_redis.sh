#!/bin/bash

# Redis启动脚本（用于本地开发）

echo "Starting Redis server for Celery broker..."

# 检查Redis是否已安装
if ! command -v redis-server &> /dev/null; then
    echo "Redis is not installed. Please install Redis first:"
    echo "  macOS: brew install redis"
    echo "  Ubuntu: sudo apt-get install redis-server"
    echo "  CentOS: sudo yum install redis"
    exit 1
fi

# 检查Redis是否已经在运行
if pgrep -x "redis-server" > /dev/null; then
    echo "Redis is already running"
    redis-cli ping
else
    echo "Starting Redis server..."
    redis-server --daemonize yes --port 6379 --logfile logs/redis.log
    
    # 等待Redis启动
    sleep 2
    
    # 检查Redis是否成功启动
    if redis-cli ping > /dev/null 2>&1; then
        echo "Redis started successfully"
    else
        echo "Failed to start Redis"
        exit 1
    fi
fi

echo "Redis is running on port 6379"