#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

slot="${1:-}"
mode="${2:-target}"

if [[ ! "$slot" =~ ^([1-9]|10)$ ]]; then
  echo 'Usage: bash deploy/ubuntu-live-check.sh <slot 1-10> [target|daily]' >&2
  exit 2
fi
if [[ "$mode" != 'target' && "$mode" != 'daily' ]]; then
  echo 'Mode must be target or daily.' >&2
  exit 2
fi

command -v docker >/dev/null 2>&1 || { echo 'docker not found' >&2; exit 3; }
docker compose ps --status running flight-bot | grep -q 'flight-bot' || {
  echo 'flight-bot container is not running. Run: bash deploy/ubuntu-deploy.sh' >&2
  exit 3
}

if [[ "$mode" == 'target' ]]; then
  path="/admin/check-slot/$slot"
else
  path="/admin/daily-summary/$slot"
fi

echo "Running real Ubuntu Google Flights check: slot=$slot mode=$mode"
echo 'Expected search flow: accepted-tfs-v1 -> Cheapest -> forced reload -> recovery <=2 -> direct rows.'

docker compose exec -T -e CHECK_PATH="$path" flight-bot python - <<'PY'
import json
import os
import sys
import urllib.error
import urllib.request

path = os.environ['CHECK_PATH']
secret = os.environ.get('ADMIN_SECRET', '')
port = os.environ.get('HTTP_PORT', '8080')
if not secret:
    raise SystemExit('ADMIN_SECRET is empty inside the container')

request = urllib.request.Request(
    f'http://127.0.0.1:{port}{path}',
    data=b'',
    method='POST',
    headers={'X-Flight-Bot-Secret': secret},
)
try:
    with urllib.request.urlopen(request, timeout=360) as response:
        payload = json.load(response)
except urllib.error.HTTPError as exc:
    body = exc.read().decode('utf-8', errors='replace')
    raise SystemExit(f'HTTP {exc.code}: {body}') from exc

print(json.dumps(payload, ensure_ascii=False, indent=2))
if not payload.get('accepted'):
    raise SystemExit('admin live check was not accepted')
result = str(payload.get('result') or '')
if '조회 실패' in result or 'failed' in result.lower() or 'Price unavailable' in result:
    raise SystemExit('live Google search failed: ' + result)
if 'Google Flights' not in result:
    raise SystemExit('live response did not contain a Google Flights result')
PY

echo
echo 'Live Google search API call: PASS'
echo 'Recent container logs:'
docker compose logs --tail 100 flight-bot

echo
if [[ "$mode" == 'target' ]]; then
  echo 'Confirm that Telegram received the target alert if this target had not fired before.'
  echo 'Repeating target mode with the same target must NOT send a second target alert.'
else
  echo 'Confirm that Telegram received one regular daily-summary message.'
fi
