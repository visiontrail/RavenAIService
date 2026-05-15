#!/usr/bin/env bash
set -euo pipefail

source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/common.sh"

require_docker
cd "${PROJECT_ROOT}"

if [ "${1:-}" != "--force" ]; then
  echo "此操作会停止容器并删除项目数据 volumes。"
  read -r -p "确认继续？输入 YES: " confirm
  if [ "${confirm}" != "YES" ]; then
    echo "已取消。"
    exit 0
  fi
fi

compose down -v --remove-orphans
docker image prune -f
echo "已清理本项目容器、网络、volumes 和悬空镜像。"
