#!/bin/sh
set -eu

PORT="${PORT:-8000}"

exec gunicorn \
  --bind "0.0.0.0:${PORT}" \
  --worker-class uvicorn.workers.UvicornWorker \
  --timeout 600 \
  app.main:app
