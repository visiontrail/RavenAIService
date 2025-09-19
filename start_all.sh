#!/bin/bash

# 一键启动：日志暂存/处理服务 + 依赖服务（在Python虚拟环境中执行）
# 功能：
# 1) 自动创建并激活本地 venv（若未激活）
# 2) 检查依赖命令与关键 Python 包
# 3) 安装 requirements.txt（带缓存标记）
# 4) 启动 Redis、执行 Alembic 迁移、启动 Celery Worker、启动 FastAPI
# 5) 完善的错误处理、进程清理与日志记录

set -Eeuo pipefail

# ------------------------------
# 基本配置
# ------------------------------
PROJECT_ROOT="$(cd "$(dirname "$0")" && pwd)"
LOG_DIR="$PROJECT_ROOT/logs"
TMP_DIR="$PROJECT_ROOT/temp"
CELERY_PIDFILE="/tmp/celery_worker.pid"
CELERY_LOGFILE="$LOG_DIR/celery_worker.log"
START_LOGFILE="$LOG_DIR/start_all.log"
REQUIREMENTS_FLAG="$PROJECT_ROOT/requirements_installed.flag"
API_HOST="0.0.0.0"
API_PORT="8085"   # 与原脚本一致
PYTHONPATH_EXPORT="${PYTHONPATH:-}:$PROJECT_ROOT"
# Redis 容器名称（与 start_redis.sh 保持一致）
REDIS_CONTAINER_NAME="gs-redis"
# 记录是否需要强制安装依赖
NEED_PIP_INSTALL=0

mkdir -p "$LOG_DIR" "$TMP_DIR" "$TMP_DIR/logs" "$TMP_DIR/downloads"

# 将所有输出同时写入日志文件
exec > >(tee -a "$START_LOGFILE") 2>&1

# ------------------------------
# 日志与辅助函数
# ------------------------------
_ts() { date "+%Y-%m-%d %H:%M:%S"; }
log_info()  { echo "[$(_ts)] [INFO ] $*"; }
log_warn()  { echo "[$(_ts)] [WARN ] $*"; }
log_error() { echo "[$(_ts)] [ERROR] $*"; }

command_exists() { command -v "$1" >/dev/null 2>&1; }

check_python_pkg() {
  # 使用已激活的 Python 解释器检查包
  "$PYTHON_BIN" - "$@" <<'PY'
import importlib, sys
mods = sys.argv[1:]
missing = []
for m in mods:
    try:
        importlib.import_module(m)
    except Exception:
        missing.append(m)
if missing:
    print(",".join(missing))
    sys.exit(1)
PY
}

cleanup() {
  # 仅在我们创建了 PID 文件且进程还在时尝试清理
  if [[ -f "$CELERY_PIDFILE" ]]; then
    local pid
    pid=$(cat "$CELERY_PIDFILE" 2>/dev/null || true)
    if [[ -n "${pid:-}" ]] && ps -p "$pid" >/dev/null 2>&1; then
      log_info "Stopping Celery worker (PID: $pid) ..."
      kill "$pid" >/dev/null 2>&1 || true
      # 等待最多5秒
      for i in {1..5}; do
        if ps -p "$pid" >/dev/null 2>&1; then sleep 1; else break; fi
      done
      if ps -p "$pid" >/dev/null 2>&1; then
        log_warn "Celery worker did not stop gracefully, forcing..."
        kill -9 "$pid" >/dev/null 2>&1 || true
      fi
    fi
    rm -f "$CELERY_PIDFILE" >/dev/null 2>&1 || true
  fi

  # 如果存在 Redis 的 docker 容器，尝试停止
  if command_exists docker; then
    if docker ps --format '{{.Names}}' | grep -q "^${REDIS_CONTAINER_NAME}$"; then
      log_info "Stopping Redis docker container (${REDIS_CONTAINER_NAME}) ..."
      docker stop "$REDIS_CONTAINER_NAME" >/dev/null 2>&1 || true
    fi
  fi
}

on_error() {
  local exit_code=$?
  log_error "Startup failed with exit code: $exit_code"
  cleanup
  exit "$exit_code"
}

trap on_error ERR
trap 'log_info "Received termination signal"; cleanup; exit 0' INT TERM

# ------------------------------
# 1) 确保在 Python 虚拟环境中运行
# ------------------------------
ensure_venv() {
  # 始终优先使用项目内的 venv，避免外部受管环境导致 pip 安装失败（PEP 668）
  local project_venv="$PROJECT_ROOT/venv"

  if [[ ! -d "$project_venv" ]]; then
    log_warn "No project virtual environment detected. Creating venv ..."
    local py_bin="python3"
    command_exists python3 || py_bin="python"
    "$py_bin" -m venv "$project_venv"
    log_info "Virtual environment created at $project_venv"
  fi

  # 若已激活其他虚拟环境，先提示并切换到项目 venv
  if [[ -n "${VIRTUAL_ENV:-}" && "$VIRTUAL_ENV" != "$project_venv" ]]; then
    log_warn "Another virtual environment detected ($VIRTUAL_ENV). Switching to project venv: $project_venv"
  fi
  # shellcheck disable=SC1091
  source "$project_venv/bin/activate"
  log_info "Activated virtual environment: $VIRTUAL_ENV"
}

# 根据当前环境选择 Python 解释器
set_python_bin() {
  # 首选项目本地 venv 的 python
  if [[ -x "$PROJECT_ROOT/venv/bin/python" ]]; then
    PYTHON_BIN="$PROJECT_ROOT/venv/bin/python"
  elif [[ -x "$PROJECT_ROOT/venv/bin/python3" ]]; then
    PYTHON_BIN="$PROJECT_ROOT/venv/bin/python3"
  elif [[ -n "${VIRTUAL_ENV:-}" && -x "$VIRTUAL_ENV/bin/python" ]]; then
    PYTHON_BIN="$VIRTUAL_ENV/bin/python"
  elif [[ -n "${VIRTUAL_ENV:-}" && -x "$VIRTUAL_ENV/bin/python3" ]]; then
    PYTHON_BIN="$VIRTUAL_ENV/bin/python3"
  elif command_exists python3; then
    PYTHON_BIN="$(command -v python3)"
  elif command_exists python; then
    PYTHON_BIN="$(command -v python)"
  else
    log_error "No suitable Python interpreter found."
    exit 1
  fi
  log_info "Using Python interpreter: $PYTHON_BIN"
}

# ------------------------------
# 2) 前置检查：依赖命令/服务/关键包
# ------------------------------
precheck_dependencies() {
  log_info "Checking required commands and services ..."

  # 基础命令
  for cmd in python3 python; do
    if command_exists "$cmd"; then
      log_info "Found command: $cmd"
      break
    fi
  done

  # 启动 Redis 的脚本
  if [[ ! -f "$PROJECT_ROOT/start_redis.sh" ]]; then
    log_error "Missing $PROJECT_ROOT/start_redis.sh. Please provide a way to start Redis."
    exit 1
  fi
  if [[ ! -x "$PROJECT_ROOT/start_redis.sh" ]]; then
    chmod +x "$PROJECT_ROOT/start_redis.sh" || true
  fi

  # 关键 Python 模块（在 venv 内检查）
  if ! check_python_pkg fastapi uvicorn celery alembic; then
    log_warn "Some Python packages are missing (fastapi/uvicorn/celery/alembic). Will install via requirements.txt."
    NEED_PIP_INSTALL=1
  else
    log_info "Core Python packages are present"
  fi
}

# ------------------------------
# 3) 安装依赖（requirements.txt）
# ------------------------------
install_requirements() {
  log_info "Installing Python dependencies (if needed) ..."
  if [[ $NEED_PIP_INSTALL -eq 1 || ! -f "$REQUIREMENTS_FLAG" ]]; then
    if [[ -f "$PROJECT_ROOT/requirements.txt" ]]; then
      "$PYTHON_BIN" -m pip install --upgrade pip setuptools wheel
      "$PYTHON_BIN" -m pip install -r "$PROJECT_ROOT/requirements.txt"
      touch "$REQUIREMENTS_FLAG"
      log_info "Dependencies installed successfully"
    else
      log_warn "requirements.txt not found, skipping bulk install"
    fi
  else
    log_info "Dependencies already installed (flag present)"
  fi
}

# ------------------------------
# 前端构建
# ------------------------------
build_frontend() {
  local fe_dir="$PROJECT_ROOT/frontend"
  if [[ -d "$fe_dir" ]]; then
    if command_exists npm; then
      if [[ ! -d "$fe_dir/node_modules" ]]; then
        log_info "Installing frontend dependencies (npm install) ..."
        (cd "$fe_dir" && npm install)
      fi
      log_info "Building frontend (npm run build) ..."
      (cd "$fe_dir" && npm run build)
      log_info "Frontend build completed."
    else
      log_warn "npm not found, skipping frontend build. The root page may not be available."
    fi
  else
    log_warn "Frontend directory not found, skipping frontend build."
  fi
}

# ------------------------------
# 4) 启动依赖服务与后台任务
# ------------------------------
start_redis() {
  log_info "Starting Redis ..."
  "$PROJECT_ROOT/start_redis.sh"
  log_info "Redis start script executed"
  # 可选：验证 redis 是否可用（需要 redis-cli）
  if command_exists redis-cli; then
    if redis-cli -h 127.0.0.1 -p 6379 ping | grep -q PONG; then
      log_info "Redis is responsive (PONG)"
    else
      log_warn "redis-cli did not receive PONG. Redis may not be ready yet."
    fi
  else
    log_warn "redis-cli not found, skipping Redis health check"
  fi
}

run_db_migrations() {
  log_info "Running database migrations (alembic upgrade head) ..."
  export PYTHONPATH="$PYTHONPATH_EXPORT"
  # 使用模块方式以确保来自当前 Python 环境
  "$PYTHON_BIN" -m alembic upgrade head
  log_info "Database migrations completed"
}

start_celery() {
  log_info "Starting Celery worker (detached) ..."
  # 清理陈旧 PID
  if [[ -f "$CELERY_PIDFILE" ]]; then
    local oldpid
    oldpid=$(cat "$CELERY_PIDFILE" 2>/dev/null || true)
    if [[ -n "${oldpid:-}" ]] && ps -p "$oldpid" >/dev/null 2>&1; then
      log_warn "Existing Celery worker detected (PID: $oldpid). Reusing it."
      return
    else
      rm -f "$CELERY_PIDFILE" || true
    fi
  fi

  export PYTHONPATH="$PYTHONPATH_EXPORT"
  # 使用 python -m celery 以确保在 venv 内
  "$PYTHON_BIN" -m celery -A app.celery_app worker \
    --loglevel=info \
    --concurrency=2 \
    --queues=log_processing,default \
    --hostname=worker@%h \
    --pidfile="$CELERY_PIDFILE" \
    --logfile="$CELERY_LOGFILE" \
    --detach

  # 等待 PID 文件或通过 ps 检测到进程（最多 15 秒）
  for i in {1..15}; do
    if [[ -f "$CELERY_PIDFILE" ]]; then
      local pid
      pid=$(cat "$CELERY_PIDFILE" 2>/dev/null || true)
      if [[ -n "${pid:-}" ]] && ps -p "$pid" >/dev/null 2>&1; then
        log_info "Celery worker started successfully (PID: $pid)"
        return
      fi
    fi
    # 通过 ps 辅助检测
    local ps_pid
    ps_pid=$(ps aux | grep -E 'celery.*worker' | grep -E 'app\.celery_app' | grep -v grep | awk '{print $2}' | head -n1 || true)
    if [[ -n "${ps_pid:-}" ]] && ps -p "$ps_pid" >/dev/null 2>&1; then
      echo "$ps_pid" > "$CELERY_PIDFILE"
      log_info "Celery worker started (detected via ps, PID: $ps_pid)"
      return
    fi
    sleep 1
  done

  log_error "Celery worker failed to start (PID not detected)"
  if [[ -f "$CELERY_LOGFILE" ]]; then
    log_error "Last 50 lines of Celery log:"; tail -n 50 "$CELERY_LOGFILE" || true
  fi
  exit 1
}

start_api() {
  log_info "Starting FastAPI application ..."
  export PYTHONPATH="$PYTHONPATH_EXPORT"
  log_info "Service URL: http://localhost:${API_PORT} | Docs: http://localhost:${API_PORT}/docs"
  log_info "Press Ctrl+C to stop all services"
  echo "=========================================="
  # 前台运行，便于 Ctrl+C 统一清理
  "$PYTHON_BIN" -m uvicorn app.main:app --reload --host "$API_HOST" --port "$API_PORT"
}

# ------------------------------
# 主流程
# ------------------------------
log_info "=== 启动：协议栈日志处理服务（All-in-One） ==="

ensure_venv
set_python_bin
precheck_dependencies
install_requirements
start_redis
run_db_migrations
start_celery
build_frontend

log_info "=== Service Status ==="
log_info "✓ Redis: start script executed (check redis-cli PING if available)"
log_info "✓ Celery Worker: running (see $CELERY_LOGFILE)"
log_info "✓ FastAPI: starting on port $API_PORT"
log_info "=========================================="

# 收到 INT/TERM 时由 trap 负责清理；正常退出时也会清理
start_api

# 若 uvicorn 正常退出，则进行清理
cleanup
log_info "Services stopped. Bye."