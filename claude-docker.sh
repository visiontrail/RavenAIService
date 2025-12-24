#!/usr/bin/env bash
set -euo pipefail

NAME="claude-work"
IMAGE="node:20-bookworm"

# 进入脚本所在目录（确保 $PWD 是项目目录）
cd "$(dirname "$0")"

# 如果容器不存在，就创建一个（先用一个长期 sleep 保持容器可反复进入）
if ! docker inspect "$NAME" >/dev/null 2>&1; then
  echo "[+] Creating container: $NAME"
  docker run -dit \
    --name "$NAME" \
    -v "$PWD":/work \
    -w /work \
    "$IMAGE" \
    bash -lc "sleep infinity"
fi

# 判断容器是否在运行
RUNNING="$(docker inspect -f '{{.State.Running}}' "$NAME")"

if [[ "$RUNNING" == "true" ]]; then
  echo "[+] Entering running container: $NAME"
  docker exec -it "$NAME" bash
else
  echo "[+] Starting and entering container: $NAME"
  docker start "$NAME" >/dev/null
  docker exec -it "$NAME" bash
fi

