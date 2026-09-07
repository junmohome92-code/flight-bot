#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")"

echo "[1/6] Checking Docker..."
if ! command -v docker >/dev/null 2>&1; then
  echo "Docker is not installed. Install Docker Engine + Compose plugin first." >&2
  exit 2
fi
if ! docker compose version >/dev/null 2>&1; then
  echo "Docker Compose plugin is not available." >&2
  exit 2
fi

echo "[2/6] Preparing .env..."
if [[ ! -f .env ]]; then
  cp .env.example .env
  echo "Created .env from .env.example"
  echo "Edit TELEGRAM_BOT_TOKEN and TELEGRAM_ALLOWED_CHAT_IDS before production use."
fi

echo "[3/6] Preparing persistent data directory..."
# Compose bind-mounts this host directory to /data in the container.
# Never delete, truncate, or recreate an existing database during install/update.
mkdir -p data
# The image intentionally runs as non-root UID 10001. A bind mount hides the
# image's /data ownership, so make only the directory writable for first boot.
# Existing database file permissions/content are left untouched.
chmod a+rwx data

echo "[4/6] Validating compose configuration..."
docker compose config >/dev/null

echo "[5/6] Building and starting Flight Bot..."
docker compose up -d --build

echo "[6/6] Current container state:"
docker compose ps

echo
echo "Installation/start complete."
echo "Health: http://127.0.0.1:8080/health (or your HTTP_PORT)"
echo "Logs  : docker compose logs -f flight-bot"
echo "DB    : $(pwd)/data/flight_bot.db"
echo "Config: edit .env, then run: docker compose up -d --build"
