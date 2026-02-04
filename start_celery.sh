#!/bin/bash

# Celery Worker启动脚本

echo "Starting Celery worker for log processing..."

# 设置环境变量
export PYTHONPATH="${PYTHONPATH}:$(pwd)"

# 启动Celery worker
celery -A app.celery_app worker \
    --loglevel=info \
    --concurrency=4 \
    --queues=log_processing,ai_analysis,maintenance,default \
    --hostname=worker@%h \
    --pidfile=/tmp/celery_worker.pid \
    --logfile=logs/celery_worker.log
