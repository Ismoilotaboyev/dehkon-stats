#!/bin/sh
# Starts the private file server in the background and the Bot API server in --local mode.
set -eu
: "${TELEGRAM_API_ID:?TELEGRAM_API_ID is required (my.telegram.org)}"
: "${TELEGRAM_API_HASH:?TELEGRAM_API_HASH is required (my.telegram.org)}"
: "${FILE_SERVER_SECRET:?FILE_SERVER_SECRET is required}"
DATA_DIR="${TELEGRAM_WORK_DIR:-/var/lib/telegram-bot-api}"
TEMP_DIR="${TELEGRAM_TEMP_DIR:-/tmp/telegram-bot-api}"
mkdir -p "$DATA_DIR" "$TEMP_DIR"

FILE_SERVER_ROOT="$DATA_DIR" python3 /opt/file_server.py &

exec telegram-bot-api \
  --api-id="$TELEGRAM_API_ID" \
  --api-hash="$TELEGRAM_API_HASH" \
  --local \
  --dir="$DATA_DIR" \
  --temp-dir="$TEMP_DIR" \
  --http-ip-address="[::]" \
  --http-port="${TELEGRAM_HTTP_PORT:-8081}"
