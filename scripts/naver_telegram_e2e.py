from __future__ import annotations

import argparse
import asyncio
import json
import urllib.parse
import urllib.request
from pathlib import Path

from naver_flight_probe import (
    DEFAULT_DEPART,
    DEFAULT_DESTINATION,
    DEFAULT_ORIGIN,
    DEFAULT_RETURN,
    collect_naver_api_results,
)


DEFAULT_ENV_FILE = Path("flight-bot - test win") / "telegram-test.env"


def _load_env(path: Path) -> dict[str, str]:
    if not path.exists():
        raise RuntimeError(f"Telegram test env file not found: {path}")
    values: dict[str, str] = {}
    for raw in path.read_text(encoding="utf-8-sig").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key.strip()] = value.strip().strip('"').strip("'")
    return values


def _chat_ids(value: str) -> list[str]:
    normalized = value.replace(";", ",").replace(" ", ",")
    return [item.strip() for item in normalized.split(",") if item.strip()]


def _telegram_request(token: str, method: str, payload: dict[str, str]) -> dict:
    url = f"https://api.telegram.org/bot{token}/{method}"
    data = urllib.parse.urlencode(payload).encode("utf-8")
    request = urllib.request.Request(url, data=data, method="POST")
    with urllib.request.urlopen(request, timeout=15) as response:
        parsed = json.loads(response.read().decode("utf-8"))
    if not parsed.get("ok"):
        raise RuntimeError(f"Telegram {method} failed: {parsed}")
    return parsed


def _validate_telegram(token: str, chat_id: str) -> tuple[str, str]:
    me = _telegram_request(token, "getMe", {})
    bot = me.get("result") or {}
    bot_name = str(bot.get("username") or bot.get("first_name") or "unknown-bot")
    chat = _telegram_request(token, "getChat", {"chat_id": chat_id})
    chat_info = chat.get("result") or {}
    chat_name = str(
        chat_info.get("title")
        or chat_info.get("username")
        or chat_info.get("first_name")
        or chat_id
    )
    return bot_name, chat_name


def _format_message(result, origin: str, destination: str, depart: str, return_date: str) -> str:
    lines = [
        "🧪 네이버 항공권 E2E 테스트",
        f"✈️ {origin.upper()} → {destination.upper()} 왕복",
        f"📅 {depart} ~ {return_date}",
        "네이버 항공권 SSE API · 직항",
    ]
    for index, row in enumerate(result.rows[:4], start=1):
        times = row.get("times") or []
        out_time = " → ".join(times[:2]) if len(times) >= 2 else "시간 정보 확인 불가"
        ret_time = " → ".join(times[2:4]) if len(times) >= 4 else "시간 정보 확인 불가"
        lines.append(
            f"{index}. {int(row['price']):,}원 · "
            f"{row.get('outbound_flight')} {out_time} / "
            f"{row.get('return_flight')} {ret_time}"
        )
    lines.extend(
        [
            "",
            "※ 테스트 메시지입니다. 예약/결제 페이지로 이동하지 않았습니다.",
            f"네이버 항공권 검색결과: {result.url}",
        ]
    )
    return "\n".join(lines)


async def run(args: argparse.Namespace) -> int:
    env_path = Path(args.env_file)
    values = _load_env(env_path)
    token = values.get("TELEGRAM_BOT_TOKEN", "").strip()
    chat_ids = _chat_ids(values.get("TELEGRAM_ALLOWED_CHAT_IDS", ""))
    if not token:
        raise RuntimeError(f"TELEGRAM_BOT_TOKEN is empty in {env_path}")
    if not chat_ids:
        raise RuntimeError(f"TELEGRAM_ALLOWED_CHAT_IDS is empty in {env_path}")

    chat_id = chat_ids[0]
    print("[1/3] Checking Telegram bot/chat ...")
    bot_name, chat_name = await asyncio.to_thread(_validate_telegram, token, chat_id)
    print(f"telegram_bot=@{bot_name}")
    print(f"telegram_chat={chat_name} ({chat_id})")

    print("[2/3] Querying real Naver Flights SSE API ...")
    result = await collect_naver_api_results(
        origin=args.origin,
        destination=args.destination,
        depart=args.depart,
        return_date=args.return_date,
        result_timeout=args.result_timeout,
        artifact_dir=args.artifact_dir,
    )

    message = _format_message(
        result,
        args.origin,
        args.destination,
        args.depart,
        args.return_date,
    )
    print("[3/3] Sending Telegram test notification ...")
    await asyncio.to_thread(
        _telegram_request,
        token,
        "sendMessage",
        {"chat_id": chat_id, "text": message, "disable_web_page_preview": "true"},
    )

    print("\n=== NAVER -> TELEGRAM E2E ===")
    print("E2E_STATUS=PASS")
    print("source=NAVER_SSE_API")
    print(f"direct_candidate_count={len(result.rows)}")
    print(f"lowest_direct_price={int(result.rows[0]['price']):,} KRW")
    print(f"telegram_chat_id={chat_id}")
    print("telegram_message_sent=True")
    print("booking_navigation_performed=False")
    print(f"result_url={result.url}")
    print(f"artifact_dir={result.artifact_dir}")
    return 0


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Naver Flights SSE API to Telegram E2E test")
    parser.add_argument("--origin", default=DEFAULT_ORIGIN)
    parser.add_argument("--destination", default=DEFAULT_DESTINATION)
    parser.add_argument("--depart", default=DEFAULT_DEPART)
    parser.add_argument("--return-date", default=DEFAULT_RETURN)
    parser.add_argument("--result-timeout", type=int, default=30)
    parser.add_argument("--artifact-dir", default="artifacts/naver-telegram-e2e")
    parser.add_argument("--env-file", default=str(DEFAULT_ENV_FILE))
    return parser.parse_args()


if __name__ == "__main__":
    try:
        raise SystemExit(asyncio.run(run(parse_args())))
    except Exception as exc:
        print("\n=== NAVER -> TELEGRAM E2E ===")
        print("E2E_STATUS=FAIL")
        print(f"error={type(exc).__name__}: {exc}")
        raise SystemExit(2)
