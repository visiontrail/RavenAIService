#!/bin/bash

# 协议栈日志处理服务完整启动脚本

echo "=== 协议栈日志处理服务启动 ==="

# 检查Python虚拟环境
if [[ "$VIRTUAL_ENV" == "" ]]; then
    echo "Warning: No virtual environment detected. Please activate your virtual environment first."
    echo "Example: source venv/bin/activate"
fi

# 创建必要的目录
echo "Creating necessary directories..."
mkdir -p logs temp temp/logs temp/downloads

# 设置环境变量
export PYTHONPATH="${PYTHONPATH}:$(pwd)"

# 1. 启动Redis
echo "\n=== Starting Redis ==="
./start_redis.sh
if [ $? -ne 0 ]; then
    echo "Failed to start Redis. Exiting."
    exit 1
fi

# 2. 安装依赖（如果需要）
echo "\n=== Checking dependencies ==="
if [ ! -f "requirements_installed.flag" ]; then
    echo "Installing Python dependencies..."
    pip install -r requirements.txt
    if [ $? -eq 0 ]; then
        touch requirements_installed.flag
        echo "Dependencies installed successfully"
    else
        echo "Failed to install dependencies. Please check requirements.txt"
        exit 1
    fi
else
    echo "Dependencies already installed"
fi

# 3. 运行数据库迁移
echo "\n=== Running database migrations ==="
alembic upgrade head
if [ $? -ne 0 ]; then
    echo "Database migration failed. Please check your database configuration."
    exit 1
fi

# 4. 启动Celery Worker（后台运行）
echo "\n=== Starting Celery Worker ==="
celery -A app.celery_app worker \
    --loglevel=info \
    --concurrency=2 \
    --queues=log_processing,default \
    --hostname=worker@%h \
    --pidfile=/tmp/celery_worker.pid \
    --logfile=logs/celery_worker.log \
    --detach

if [ $? -eq 0 ]; then
    echo "Celery worker started successfully (PID file: /tmp/celery_worker.pid)"
else
    echo "Failed to start Celery worker"
    exit 1
fi

# 等待Celery worker启动
sleep 3

# 5. 启动FastAPI应用
echo "\n=== Starting FastAPI Application ==="
echo "Application will be available at: http://localhost:8085"
echo "API Documentation: http://localhost:8085/docs"
echo "\nPress Ctrl+C to stop all services"
echo "\n=== Service Status ==="
echo "✓ Redis: Running on port 6379"
echo "✓ Celery Worker: Running (check logs/celery_worker.log for details)"
echo "✓ FastAPI: Starting..."
echo "\n==========================================\n"

# 设置信号处理，确保退出时清理所有进程
trap 'echo "\n\nShutting down services..."; kill $(cat /tmp/celery_worker.pid 2>/dev/null) 2>/dev/null; echo "Services stopped."; exit 0' INT TERM

# 启动FastAPI应用（前台运行）
python -m uvicorn app.main:app --reload --host 0.0.0.0 --port 8085