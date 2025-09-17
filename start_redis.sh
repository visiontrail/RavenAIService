#!/bin/bash

# Redis启动脚本（用于本地开发）
# 支持三种情况：
# 1) 已有 redis 在本机运行 -> 直接检测并复用
# 2) 本机安装了 redis-server -> 后台拉起
# 3) 未安装 redis-server 但安装了 Docker -> 使用 docker 拉起（容器名：gs-redis）

set -Eeuo pipefail

PROJECT_ROOT="$(cd "$(dirname "$0")" && pwd)"
LOG_DIR="$PROJECT_ROOT/logs"
mkdir -p "$LOG_DIR"
REDIS_LOGFILE="$LOG_DIR/redis.log"

log() { echo "[start_redis] $*" | tee -a "$REDIS_LOGFILE"; }
cmd_exists() { command -v "$1" >/dev/null 2>&1; }

# 0) 如果 redis 已在本机 6379 端口响应，直接返回
if cmd_exists redis-cli; then
  if redis-cli -h 127.0.0.1 -p 6379 ping >/dev/null 2>&1; then
    log "Redis already running (PING ok)"
    exit 0
  fi
fi

log "Starting Redis server for Celery broker..."

# 1) 优先使用本机 redis-server
if cmd_exists redis-server; then
  # 如果已有 redis 进程，则复用
  if pgrep -x "redis-server" >/dev/null 2>&1; then
    log "redis-server already running"
    cmd_exists redis-cli && redis-cli ping || true
    exit 0
  fi
  log "Starting redis-server (daemonize) ..."
  redis-server --daemonize yes --port 6379 --logfile "$REDIS_LOGFILE"
  sleep 2
  if cmd_exists redis-cli && redis-cli -h 127.0.0.1 -p 6379 ping >/dev/null 2>&1; then
    log "Redis started successfully (local redis-server)"
    exit 0
  else
    log "WARN: redis-server started but PING not responded yet"
    exit 0
  fi
fi

# 2) 尝试使用 Docker 拉起
if cmd_exists docker; then
  CONTAINER_NAME="gs-redis"
  IMAGE="redis:7-alpine"

  # 如果容器已存在
  if docker ps -a --format '{{.Names}}' | grep -q "^${CONTAINER_NAME}$"; then
    # 若未在运行，则启动
    if ! docker ps --format '{{.Names}}' | grep -q "^${CONTAINER_NAME}$"; then
      log "Starting existing Redis container ${CONTAINER_NAME} ..."
      docker start "$CONTAINER_NAME" >/dev/null
    else
      log "Redis container ${CONTAINER_NAME} already running"
    fi
  else
    log "Running new Redis container via Docker ..."
    docker run -d --name "$CONTAINER_NAME" -p 6379:6379 -v "$PROJECT_ROOT/temp/redis":/data "$IMAGE" >/dev/null
  fi

  # 健康检查
  if cmd_exists redis-cli; then
    for i in {1..10}; do
      if redis-cli -h 127.0.0.1 -p 6379 ping >/dev/null 2>&1; then
        log "Redis (docker) is responsive (PONG)"
        exit 0
      fi
      sleep 1
    done
    log "WARN: Redis container started but not responsive yet"
    exit 0
  else
    log "redis-cli not found, skipping PING check (container started)"
    exit 0
  fi
fi

# 3) 两者都不可用 -> 提示安装
log "Redis is not installed and Docker is not available. Please install one of them."
log "  macOS: brew install redis  | or install Docker Desktop"
log "  Ubuntu: sudo apt-get install redis-server  | or install Docker"
log "  CentOS: sudo yum install redis  | or install Docker"
exit 1