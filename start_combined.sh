#!/bin/bash

set -euo pipefail

LOG_SERVER_PORT="${LOG_SERVER_PORT:-8085}"
RAVEN_PORT="${RAVEN_PORT:-8083}"
RAVEN_BASE_PATH="${RAVEN_BASE_PATH:-/raven}"
RAVEN_DATA_DIR="${RAVEN_DATA_DIR:-/app/data/raven}"

if ! mkdir -p "${RAVEN_DATA_DIR}" 2>/dev/null; then
  echo "⚠️ 无法创建 ${RAVEN_DATA_DIR}，改用 /app/package-server/data"
  RAVEN_DATA_DIR="/app/package-server/data"
fi

RAVEN_UPLOAD_DIR="${RAVEN_UPLOAD_DIR:-${RAVEN_DATA_DIR}/uploads}"

mkdir -p "${RAVEN_DATA_DIR}" "${RAVEN_UPLOAD_DIR}"

echo "Starting Raven package server on port ${RAVEN_PORT} (base path: ${RAVEN_BASE_PATH}, data dir: ${RAVEN_DATA_DIR})"

pushd /app/package-server >/dev/null
PORT="${RAVEN_PORT}" RAVEN_BASE_PATH="${RAVEN_BASE_PATH}" RAVEN_DATA_DIR="${RAVEN_DATA_DIR}" UPLOAD_DIR="${RAVEN_UPLOAD_DIR}" node src/index.js &
PACKAGE_PID=$!
popd >/dev/null

echo "Starting log server on port ${LOG_SERVER_PORT}"
uvicorn app.main:app --host 0.0.0.0 --port "${LOG_SERVER_PORT}" &
UVICORN_PID=$!

cleanup() {
  echo "Stopping services..."
  kill "${PACKAGE_PID}" "${UVICORN_PID}" 2>/dev/null || true
}

trap cleanup SIGINT SIGTERM

# Wait for any process to exit
wait -n "${PACKAGE_PID}" "${UVICORN_PID}"
EXIT_CODE=$?

# Ensure both processes are stopped when one exits
cleanup
exit "${EXIT_CODE}"
