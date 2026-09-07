from __future__ import annotations

import argparse
import asyncio
import json
import sys
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from flight_bot.naver_search import build_result_url, query_round_trip  # noqa: E402


DEFAULT_ORIGIN = "CJJ"
DEFAULT_DESTINATION = "TPE"
DEFAULT_DEPART = "2026-09-18"
DEFAULT_RETURN = "2026-09-20"


@dataclass
class ProbeResult:
    url: str
    rows: list[dict]
    diagnostics: dict
    artifact_dir: Path


def _save_artifacts(
    artifact_dir: Path,
    *,
    raw_sse: str,
    selected: dict,
    rows: list[dict],
    diagnostics: dict,
    result_url: str,
) -> None:
    artifact_dir.mkdir(parents=True, exist_ok=True)
    (artifact_dir / "response.sse.txt").write_text(raw_sse, encoding="utf-8")
    (artifact_dir / "response.json").write_text(
        json.dumps(selected, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    (artifact_dir / "diagnostics.json").write_text(
        json.dumps(diagnostics, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    (artifact_dir / "result.json").write_text(
        json.dumps(
            {
                "captured_at": datetime.now().isoformat(timespec="seconds"),
                "url": result_url,
                "rows": rows,
                "diagnostics": diagnostics,
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )


async def collect_naver_api_results(
    *,
    origin: str = DEFAULT_ORIGIN,
    destination: str = DEFAULT_DESTINATION,
    depart: str = DEFAULT_DEPART,
    return_date: str = DEFAULT_RETURN,
    result_timeout: int = 30,
    artifact_dir: str | Path = "artifacts/naver-flight-poc",
) -> ProbeResult:
    rows, diagnostics, raw_sse, selected = await asyncio.to_thread(
        query_round_trip,
        origin,
        destination,
        depart,
        return_date,
        timeout_seconds=result_timeout,
        attempts=3,
        limit=20,
    )
    url = build_result_url(origin, destination, depart, return_date)
    artifact_path = Path(artifact_dir)
    _save_artifacts(
        artifact_path,
        raw_sse=raw_sse,
        selected=selected,
        rows=rows,
        diagnostics=diagnostics,
        result_url=url,
    )
    return ProbeResult(url=url, rows=rows, diagnostics=diagnostics, artifact_dir=artifact_path.resolve())


def _print_rows(result: ProbeResult, max_rows: int = 5) -> None:
    print("\n=== NAVER RESULT ===")
    print("POC_STATUS=PASS")
    print("source=NAVER_SSE_API")
    print(f"origin_type={result.diagnostics.get('origin_type')}")
    print(f"destination_type={result.diagnostics.get('destination_type')}")
    print(f"direct_candidate_count={len(result.rows)}")
    print(f"lowest_direct_price={int(result.rows[0]['price']):,} KRW")
    advertised = result.diagnostics.get("advertised_lowest_direct")
    if isinstance(advertised, (int, float)):
        print(f"naver_advertised_lowest_direct={int(advertised):,} KRW")

    for index, row in enumerate(result.rows[:max_rows], start=1):
        times = row.get("times") or []
        out_dep = row.get("outbound_departure_airport") or "?"
        out_arr = row.get("outbound_arrival_airport") or "?"
        ret_dep = row.get("return_departure_airport") or "?"
        ret_arr = row.get("return_arrival_airport") or "?"
        out_times = f"{out_dep} {times[0]} -> {out_arr} {times[1]}" if len(times) >= 2 else "time-unavailable"
        ret_times = f"{ret_dep} {times[2]} -> {ret_arr} {times[3]}" if len(times) >= 4 else "time-unavailable"
        print(f"candidate_{index}={int(row['price']):,} KRW")
        print(
            f"  outbound={row.get('outbound_airline')} {row.get('outbound_flight')} | {out_times}"
        )
        print(
            f"  return={row.get('return_airline')} {row.get('return_flight')} | {ret_times}"
        )

    print(f"result_url={result.url}")
    print("booking_navigation_performed=False")
    print(f"artifact_dir={result.artifact_dir}")


async def run(args: argparse.Namespace) -> int:
    print("==================================================")
    print(" NAVER FLIGHTS SSE API POC")
    print("==================================================")
    print(f"route={args.origin.upper()}->{args.destination.upper()}->{args.origin.upper()}")
    print(f"dates={args.depart}~{args.return_date}")
    print("source=flight-api.naver.com SSE")
    print("direct_only=True")
    print("round_trip=True")
    print("")

    try:
        result = await collect_naver_api_results(
            origin=args.origin,
            destination=args.destination,
            depart=args.depart,
            return_date=args.return_date,
            result_timeout=args.result_timeout,
            artifact_dir=args.artifact_dir,
        )
    except Exception as exc:
        print("\n=== NAVER RESULT ===")
        print("POC_STATUS=FAIL")
        print(f"error={type(exc).__name__}: {exc}")
        return 2

    _print_rows(result, max_rows=args.top)
    return 0


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Naver Flights SSE API POC (airport or supported city code)")
    parser.add_argument("--origin", default=DEFAULT_ORIGIN)
    parser.add_argument("--destination", default=DEFAULT_DESTINATION)
    parser.add_argument("--depart", default=DEFAULT_DEPART)
    parser.add_argument("--return-date", default=DEFAULT_RETURN)
    parser.add_argument("--result-timeout", type=int, default=30)
    parser.add_argument("--top", type=int, default=5)
    parser.add_argument("--artifact-dir", default="artifacts/naver-flight-poc")
    return parser.parse_args()


if __name__ == "__main__":
    raise SystemExit(asyncio.run(run(parse_args())))
