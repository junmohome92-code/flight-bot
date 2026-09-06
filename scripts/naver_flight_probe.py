from __future__ import annotations

import argparse
import asyncio
import json
import re
import sys
from datetime import datetime
from pathlib import Path
from urllib.parse import urlencode

from playwright.async_api import Page, async_playwright


DEFAULT_ORIGIN = "CJJ"
DEFAULT_DESTINATION = "TPE"
DEFAULT_DEPART = "2026-09-18"
DEFAULT_RETURN = "2026-09-20"


def build_naver_url(origin: str, destination: str, depart: str, return_date: str) -> str:
    origin = origin.strip().upper()
    destination = destination.strip().upper()
    depart_compact = depart.replace("-", "")
    return_compact = return_date.replace("-", "")
    path = (
        f"https://flight.naver.com/flights/international/"
        f"{origin}:airport-{destination}:airport-{depart_compact}/"
        f"{destination}:airport-{origin}:airport-{return_compact}"
    )
    query = urlencode({"adult": 1, "fareType": "Y", "isDirect": "true"})
    return f"{path}?{query}"


_COLLECT_ROWS_JS = r"""
() => {
  const priceRe = /(?:₩\s*)?([0-9]{1,3}(?:,[0-9]{3})+)\s*(?:원|KRW)?/g;
  const timeRe = /\b(?:[01]?\d|2[0-3]):[0-5]\d\b/g;
  const directRe = /직항|direct|nonstop/i;
  const transferRe = /경유|stopover|\bstops?\b/i;

  function visible(el) {
    if (!(el instanceof Element) || !el.isConnected) return false;
    const style = getComputedStyle(el);
    if (style.display === 'none' || style.visibility === 'hidden' || style.opacity === '0') return false;
    const rect = el.getBoundingClientRect();
    return rect.width > 2 && rect.height > 2;
  }

  function clean(text) {
    return String(text || '').replace(/\s+/g, ' ').trim();
  }

  function prices(text) {
    const out = [];
    priceRe.lastIndex = 0;
    let m;
    while ((m = priceRe.exec(text)) !== null) {
      const value = Number(m[1].replaceAll(',', ''));
      if (Number.isFinite(value) && value >= 50000 && value <= 1500000) out.push(value);
    }
    return [...new Set(out)];
  }

  const rows = [];
  const seen = new Set();
  const nodes = document.querySelectorAll('strong, em, b, span, p, div');

  for (const el of nodes) {
    if (!visible(el)) continue;
    const own = clean(el.innerText || el.textContent || '');
    if (!own || own.length > 120) continue;
    const ownPrices = prices(own);
    if (!ownPrices.length) continue;

    for (const price of ownPrices) {
      let node = el;
      for (let depth = 0; depth < 11 && node; depth += 1, node = node.parentElement) {
        const text = clean(node.innerText || node.textContent || '');
        if (!text || text.length < 35) continue;
        if (text.length > 1600) break;

        timeRe.lastIndex = 0;
        const times = text.match(timeRe) || [];
        if (times.length < 2 || times.length > 8) continue;

        const direct = directRe.test(text);
        const transfer = transferRe.test(text);
        if (transfer && !direct) continue;

        const rowPrices = prices(text);
        if (!rowPrices.includes(price) || rowPrices.length > 8) continue;

        const key = `${price}|${text.slice(0, 700).toUpperCase()}`;
        if (seen.has(key)) break;
        seen.add(key);
        rows.push({
          price,
          times: times.slice(0, 4),
          direct_evidence: direct ? 'row-direct-marker' : 'query-isDirect=true',
          text: text.slice(0, 1200),
        });
        break;
      }
    }
  }

  rows.sort((a, b) => a.price - b.price || a.text.length - b.text.length);
  return rows.slice(0, 12);
}
"""


async def _dismiss_consent(page: Page) -> None:
    labels = [
        r"^모두 동의$",
        r"^동의$",
        r"^동의하고 계속$",
        r"^확인$",
        r"^Accept all$",
        r"^I agree$",
    ]
    for pattern in labels:
        try:
            button = page.get_by_role("button", name=re.compile(pattern, re.I)).first
            if await button.count() and await button.is_visible():
                await button.click(timeout=1500)
                await page.wait_for_timeout(300)
        except Exception:
            pass


async def _body_text(page: Page) -> str:
    try:
        return await page.locator("body").inner_text(timeout=3000)
    except Exception:
        return ""


async def _wait_for_rows(page: Page, timeout_seconds: int) -> tuple[list[dict], str]:
    deadline = asyncio.get_running_loop().time() + timeout_seconds
    last_body = ""
    cycle = 0
    while asyncio.get_running_loop().time() < deadline:
        cycle += 1
        await _dismiss_consent(page)
        try:
            rows = await page.evaluate(_COLLECT_ROWS_JS)
        except Exception:
            rows = []
        if rows:
            return list(rows), await _body_text(page)

        last_body = await _body_text(page)
        lowered = last_body.lower()
        blocked_markers = (
            "접근이 제한",
            "비정상적인 접근",
            "captcha",
            "verify you are human",
            "access denied",
        )
        if any(marker in lowered for marker in blocked_markers):
            raise RuntimeError("Naver Flights appears to be blocking or challenging this browser session")

        if cycle % 4 == 0:
            try:
                await page.mouse.wheel(0, 650)
            except Exception:
                pass
        await page.wait_for_timeout(1000)

    return [], last_body


async def _save_artifacts(page: Page, artifact_dir: Path, rows: list[dict], body: str) -> None:
    artifact_dir.mkdir(parents=True, exist_ok=True)
    try:
        await page.screenshot(path=str(artifact_dir / "page.png"), full_page=True)
    except Exception:
        pass
    (artifact_dir / "page.txt").write_text(body or "", encoding="utf-8")
    payload = {
        "captured_at": datetime.now().isoformat(timespec="seconds"),
        "url": page.url,
        "rows": rows,
    }
    (artifact_dir / "result.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
    )


async def run(args: argparse.Namespace) -> int:
    url = build_naver_url(args.origin, args.destination, args.depart, args.return_date)
    artifact_dir = Path(args.artifact_dir)

    print("==================================================")
    print(" NAVER FLIGHTS independent visible POC")
    print("==================================================")
    print(f"route={args.origin.upper()}->{args.destination.upper()}->{args.origin.upper()}")
    print(f"dates={args.depart}~{args.return_date}")
    print("browser=Microsoft Edge (Playwright msedge channel)")
    print("direct_only=True")
    print("booking_navigation=False")
    print(f"search_url={url}")
    print("")

    playwright = await async_playwright().start()
    browser = None
    context = None
    page = None
    rows: list[dict] = []
    body = ""
    try:
        try:
            browser = await playwright.chromium.launch(
                channel="msedge",
                headless=False,
                args=["--start-maximized"],
            )
        except Exception as exc:
            raise RuntimeError(
                "Microsoft Edge could not be launched by Playwright. Update/install Edge and run 01 setup again."
            ) from exc

        context = await browser.new_context(
            locale="ko-KR",
            timezone_id="Asia/Seoul",
            viewport={"width": 1440, "height": 1000},
        )
        page = await context.new_page()
        page.set_default_timeout(5000)
        await page.goto(url, wait_until="domcontentloaded", timeout=args.navigation_timeout * 1000)
        print(f"loaded_url={page.url}")

        rows, body = await _wait_for_rows(page, args.result_timeout)
        await _save_artifacts(page, artifact_dir, rows, body)

        if not rows:
            print("\n=== NAVER RESULT ===")
            print("POC_STATUS=FAIL")
            print("reason=no row-scoped direct flight price found before timeout")
            print(f"final_url={page.url}")
            print(f"artifact_dir={artifact_dir.resolve()}")
            if args.failure_keep_open > 0:
                await page.wait_for_timeout(args.failure_keep_open * 1000)
            return 2

        print("\n=== NAVER RESULT ===")
        print("POC_STATUS=PASS")
        print(f"direct_candidate_count={len(rows)}")
        print(f"lowest_visible_direct_price={rows[0]['price']:,} KRW")
        for index, row in enumerate(rows[:4], start=1):
            times = row.get("times") or []
            time_text = " -> ".join(times[:2]) if len(times) >= 2 else "time-unavailable"
            compact = re.sub(r"\s+", " ", str(row.get("text") or ""))[:380]
            print(f"candidate_{index}={row['price']:,} KRW | {time_text} | {compact}")
        print(f"result_url={page.url}")
        print("booking_navigation_performed=False")
        print(f"artifact_dir={artifact_dir.resolve()}")
        if args.keep_open > 0:
            await page.wait_for_timeout(args.keep_open * 1000)
        return 0
    except Exception as exc:
        if page is not None:
            body = body or await _body_text(page)
            await _save_artifacts(page, artifact_dir, rows, body)
        print("\n=== NAVER RESULT ===")
        print("POC_STATUS=FAIL")
        print(f"error={type(exc).__name__}: {exc}")
        if page is not None:
            print(f"final_url={page.url}")
            print(f"artifact_dir={artifact_dir.resolve()}")
            if args.failure_keep_open > 0:
                try:
                    await page.wait_for_timeout(args.failure_keep_open * 1000)
                except Exception:
                    pass
        return 2
    finally:
        if context is not None:
            try:
                await context.close()
            except Exception:
                pass
        if browser is not None:
            try:
                await browser.close()
            except Exception:
                pass
        await playwright.stop()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Visible Naver Flights POC")
    parser.add_argument("--origin", default=DEFAULT_ORIGIN)
    parser.add_argument("--destination", default=DEFAULT_DESTINATION)
    parser.add_argument("--depart", default=DEFAULT_DEPART)
    parser.add_argument("--return-date", default=DEFAULT_RETURN)
    parser.add_argument("--navigation-timeout", type=int, default=60)
    parser.add_argument("--result-timeout", type=int, default=70)
    parser.add_argument("--keep-open", type=int, default=8)
    parser.add_argument("--failure-keep-open", type=int, default=15)
    parser.add_argument("--artifact-dir", default="artifacts/naver-flight-poc")
    return parser.parse_args()


if __name__ == "__main__":
    if not sys.platform.startswith("win"):
        raise SystemExit("This POC is intended for Windows visible Edge testing")
    raise SystemExit(asyncio.run(run(parse_args())))
