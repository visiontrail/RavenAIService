#!/usr/bin/env bash
set -euo pipefail

source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/common.sh"

require_docker
cd "${PROJECT_ROOT}"

if [ "${1:-}" = "--volumes" ]; then
  echo "停止容器并删除 Compose volumes..."
  compose down -v
else
  echo "停止容器，保留数据 volumes..."
  compose down
fi
