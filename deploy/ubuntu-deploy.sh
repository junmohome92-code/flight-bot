#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

EXPECTED_PROVIDER='google-playwright-results-observed-accepted-flow'
EXPECTED_QUERY='accepted-tfs-v1'

fail() {
  echo "ERROR: $*" >&2
  exit 1
}

value_from_env() {
  local key="$1"
  local value
  value="$(sed -n "s/^${key}=//p" .env | tail -n 1 | tr -d '\r')"
  value="${value%\"}"
  value="${value#\"}"
  value="${value%\'}"
  value="${value#\'}"
  printf '%s' "$value"
}

command -v docker >/dev/null 2>&1 || fail 'docker is not installed'
docker info >/dev/null 2>&1 || fail 'docker engine is not running or this user cannot access it'
docker compose version >/dev/null 2>&1 || fail 'docker compose plugin is not available'

if [[ ! -f .env ]]; then
  cp .env.example .env
  echo '.env was created from .env.example.'
  echo 'Fill these values, then run this script again:'
  echo '  TELEGRAM_BOT_TOKEN=...'
  echo '  TELEGRAM_ALLOWED_CHAT_IDS=...'
  echo '  ADMIN_SECRET=...'
  exit 2
fi

telegram_token="$(value_from_env TELEGRAM_BOT_TOKEN)"
telegram_chats="$(value_from_env TELEGRAM_ALLOWED_CHAT_IDS)"
admin_secret="$(value_from_env ADMIN_SECRET)"

[[ -n "$telegram_token" ]] || fail 'TELEGRAM_BOT_TOKEN is empty in .env'
[[ -n "$telegram_chats" ]] || fail 'TELEGRAM_ALLOWED_CHAT_IDS is empty in .env'
[[ -n "$admin_secret" ]] || fail 'ADMIN_SECRET is empty in .env'
[[ "$telegram_chats" =~ ^-?[0-9]+([[:space:]]*,[[:space:]]*-?[0-9]+)*$ ]] || fail 'TELEGRAM_ALLOWED_CHAT_IDS must be numeric IDs separated by commas'

echo '[1/5] Validating Docker Compose configuration ...'
docker compose config -q

echo '[2/5] Building the production image ...'
docker compose build --pull flight-bot

echo '[3/5] Starting/updating Flight Bot ...'
docker compose up -d --remove-orphans flight-bot

echo '[4/5] Waiting for container health ...'
healthy=0
for _ in $(seq 1 90); do
  status="$(docker inspect --format='{{if .State.Health}}{{.State.Health.Status}}{{else}}none{{end}}' flight-bot 2>/dev/null || true)"
  if [[ "$status" == 'healthy' ]]; then
    healthy=1
    break
  fi
  if [[ "$status" == 'unhealthy' ]]; then
    docker compose logs --tail 160 flight-bot >&2 || true
    fail 'container became unhealthy'
  fi
  sleep 1
done
if [[ "$healthy" != '1' ]]; then
  docker compose logs --tail 160 flight-bot >&2 || true
  fail 'container did not become healthy within 90 seconds'
fi

echo '[5/5] Verifying production runtime contract ...'
docker compose exec -T flight-bot python - <<'PY'
import json
import os
import urllib.request

port = os.environ.get('HTTP_PORT', '8080')
url = f'http://127.0.0.1:{port}/health'
with urllib.request.urlopen(url, timeout=10) as response:
    payload = json.load(response)

checks = {
    'ok': payload.get('ok') is True,
    'provider': payload.get('provider') == 'google-playwright-results-observed-accepted-flow',
    'query_contract': payload.get('google_query_contract') == 'accepted-tfs-v1',
    'slots': payload.get('slots_max') == 10 and payload.get('slots_design_capacity') == 10,
    'search_interval': payload.get('search_interval_hours') == 2,
    'search_concurrency': payload.get('search_concurrency') == 2,
    'storage_isolation': payload.get('browser_search_storage_isolated') is True,
    'asset_blocking': payload.get('browser_block_assets') is False,
    'cheapest_reload': payload.get('cheapest_selected_full_reload') is True,
    'price_recovery': payload.get('price_unavailable_recovery_reloads') == 2,
    'telegram': payload.get('telegram_connected') is True,
    'admin': payload.get('admin_endpoint_enabled') is True,
}
failed = [name for name, ok in checks.items() if not ok]
print(json.dumps(payload, ensure_ascii=False, indent=2))
if failed:
    raise SystemExit('runtime contract failed: ' + ', '.join(failed))
PY

echo
echo 'Flight Bot Ubuntu deployment: PASS'
echo "  provider: ${EXPECTED_PROVIDER}"
echo "  query:    ${EXPECTED_QUERY}"
echo '  slots:    10'
echo '  searches: every 2 hours, max 2 concurrent, isolated contexts'
echo
echo 'Next:'
echo '  1) In Telegram, add a slot, for example:'
echo '     /flight add CJJ TPE 2026-09-18 2026-09-20 999999'
echo '  2) Run a real server-side Google/Telegram verification:'
echo '     bash deploy/ubuntu-live-check.sh 1 target'
echo
echo 'Useful commands:'
echo '  docker compose ps'
echo '  docker compose logs -f --tail 120 flight-bot'
echo '  docker compose down'
