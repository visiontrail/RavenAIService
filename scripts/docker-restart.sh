#!/usr/bin/env bash
set -euo pipefail

source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/common.sh"

require_docker
ensure_env_file
cd "${PROJECT_ROOT}"

echo "重启 RavenAIService 本地 Docker 环境..."
compose down
compose up -d --build

echo
compose ps
print_endpoints
