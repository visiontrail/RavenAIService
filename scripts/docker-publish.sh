#!/usr/bin/env bash
set -euo pipefail

source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/common.sh"

usage() {
  cat <<'USAGE'
用法:
  scripts/docker-publish.sh <dockerhub_namespace> [tag]

示例:
  scripts/docker-publish.sh galaxyspaceai v1.0.0
  IMAGE_TAG=2026.05.15 scripts/docker-publish.sh galaxyspaceai

发布镜像:
  <namespace>/raven-backend:<tag>
  <namespace>/raven-frontend:<tag>
  <namespace>/raven-package-server:<tag>
  同时推送 latest 标签，除非设置 PUSH_LATEST=false。
USAGE
}

if [ "${1:-}" = "-h" ] || [ "${1:-}" = "--help" ]; then
  usage
  exit 0
fi

require_docker

NAMESPACE="${DOCKERHUB_NAMESPACE:-${1:-}}"
TAG="${IMAGE_TAG:-${2:-latest}}"
PUSH_LATEST="${PUSH_LATEST:-true}"

if [ -z "${NAMESPACE}" ]; then
  usage
  echo
  echo "缺少 DockerHub namespace，例如 galaxyspaceai。" >&2
  exit 1
fi

cd "${PROJECT_ROOT}"

images=(
  "raven-backend:."
  "raven-frontend:./frontend"
  "raven-package-server:./package-server"
)

for item in "${images[@]}"; do
  name="${item%%:*}"
  context="${item#*:}"
  dockerfile="${context}/Dockerfile"
  if [ "${context}" = "." ]; then
    dockerfile="Dockerfile"
  fi

  echo "构建 ${NAMESPACE}/${name}:${TAG} ..."
  docker build -f "${dockerfile}" -t "${NAMESPACE}/${name}:${TAG}" "${context}"

  if [ "${PUSH_LATEST}" = "true" ]; then
    docker tag "${NAMESPACE}/${name}:${TAG}" "${NAMESPACE}/${name}:latest"
  fi
done

for item in "${images[@]}"; do
  name="${item%%:*}"
  echo "推送 ${NAMESPACE}/${name}:${TAG} ..."
  docker push "${NAMESPACE}/${name}:${TAG}"

  if [ "${PUSH_LATEST}" = "true" ]; then
    echo "推送 ${NAMESPACE}/${name}:latest ..."
    docker push "${NAMESPACE}/${name}:latest"
  fi
done

echo "DockerHub 发布完成。"
