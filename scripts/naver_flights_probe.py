from __future__ import annotations

import asyncio
import re
import sys
from pathlib import Path

from playwright.async_api import Browser, BrowserContext, Page, async_playwright


ARTIFACT_DIR = Path("artifacts/naver-flights-win")
SEARCH_URL = (
    "https://flight.naver.com/flights/international/"
    "CJJ:airport-TPE:airport-20260918/"
    "TPE:airport-CJJ:airport-20260920"
    "?adult=1&fareType=Y&isDirect=true"
)
PRICE_RE = re.compile(r"(?<!\d)([1-9][0-9]{1,2}(?:,[0-9]{3})+)\s*원")


async def save_artifacts(page: Page, network_urls: list[str], stem: str) -> None:
    ARTIFACT_DIR.mkdir(parents=True, exist_ok=True)
    try:
        await page.screenshot(path=str(ARTIFACT_DIR / f"{stem}.png"), full_page=True)
    except Exception:
        pass
    try:
        body = await page.locator("body").inner_text(timeout=3_000)
        (ARTIFACT_DIR / f"{stem}.txt").write_text(body, encoding="utf-8")
    except Exception:
        pass
    try:
        (ARTIFACT_DIR / "network.txt").write_text("\n".join(network_urls), encoding="utf-8")
    except Exception:
        pass


async def collect_row_scoped_prices(page: Page) -> list[dict]:
    """Collect compact visible result contexts containing a won price.

    The probe never clicks a fare/booking card. The URL itself requests direct
    flights only (isDirect=true). We still reject giant page-level containers
    so the output is useful for deciding whether a stable Naver provider is
    feasible later.
    """
    rows = await page.evaluate(
        r"""() => {
            const priceRe = /(?<!\d)([1-9][0-9]{1,2}(?:,[0-9]{3})+)\s*원/g;
            const timeRe = /\b\d{1,2}:\d{2}\b/g;
            const seen = new Set();
            const out = [];
            const visible = el => {
                const style = getComputedStyle(el);
                const rect = el.getBoundingClientRect();
                return style.display !== 'none' && style.visibility !== 'hidden' && rect.width > 2 && rect.height > 2;
            };
            const textOf = el => (el.innerText || el.textContent || '').replace(/\s+/g, ' ').trim();

            for (const el of document.querySelectorAll('body *')) {
                if (!visible(el)) continue;
                const own = `${el.getAttribute('aria-label') || ''} ${textOf(el)}`.trim();
                if (!own || own.length > 220) continue;
                priceRe.lastIndex = 0;
                const matches = [...own.matchAll(priceRe)];
                if (!matches.length) continue;

                let node = el;
                for (let depth = 0; depth < 9 && node; depth += 1, node = node.parentElement) {
                    const text = textOf(node);
                    if (!text || text.length > 1600) continue;
                    priceRe.lastIndex = 0;
                    const prices = [...text.matchAll(priceRe)]
                        .map(m => Number(m[1].replaceAll(',', '')))
                        .filter(Number.isFinite);
                    if (!prices.length || prices.length > 4) continue;
                    timeRe.lastIndex = 0;
                    const times = text.match(timeRe) || [];
                    const routeSignal = /CJJ|TPE|청주|타이베이|타오위안/i.test(text);
                    const flightSignal = /직항|항공|출발|도착|소요|편도|왕복|flight/i.test(text);
                    if (times.length < 2 && !routeSignal) continue;
                    if (!flightSignal && !routeSignal) continue;

                    const price = Math.min(...prices);
                    const key = `${price}|${text.slice(0, 800).toLowerCase()}`;
                    if (seen.has(key)) break;
                    seen.add(key);
                    out.push({price, text: text.slice(0, 1200), times: times.slice(0, 6)});
                    break;
                }
            }
            out.sort((a, b) => a.price - b.price);
            return out.slice(0, 20);
        }"""
    )
    return list(rows or [])


async def main() -> int:
    if not sys.platform.startswith("win"):
        print("This probe is Windows-only.")
        return 2

    ARTIFACT_DIR.mkdir(parents=True, exist_ok=True)
    print("==================================================")
    print(" Naver Flights visible viability test")
    print("==================================================")
    print("browser_channel=msedge")
    print("route=CJJ->TPE->CJJ")
    print("dates=2026-09-18..2026-09-20")
    print("direct_filter=isDirect=true")
    print("booking_navigation=NO")
    print("external_checkout_navigation=NO")
    print(f"selection_url={SEARCH_URL}")
    print("")

    playwright = await async_playwright().start()
    browser: Browser | None = None
    context: BrowserContext | None = None
    page: Page | None = None
    network_urls: list[str] = []
    try:
        browser = await playwright.chromium.launch(channel="msedge", headless=False)
        context = await browser.new_context(
            locale="ko-KR",
            timezone_id="Asia/Seoul",
            viewport={"width": 1365, "height": 900},
            service_workers="block",
        )
        page = await context.new_page()
        page.set_default_timeout(60_000)

        def on_response(response) -> None:
            try:
                req = response.request
                if req.resource_type not in {"xhr", "fetch"}:
                    return
                url = response.url
                if "naver.com" not in url:
                    return
                if url not in network_urls:
                    network_urls.append(url)
            except Exception:
                pass

        page.on("response", on_response)
        await page.goto(SEARCH_URL, wait_until="domcontentloaded", timeout=60_000)

        rows: list[dict] = []
        for cycle in range(45):
            await page.wait_for_timeout(1_000)
            body = await page.locator("body").inner_text(timeout=5_000)
            if cycle in {4, 14, 29}:
                print(f"naver_wait_cycle={cycle + 1} body_chars={len(body)}")
            rows = await collect_row_scoped_prices(page)
            if rows:
                break
            if "접근이 제한" in body or "비정상적인 접근" in body or "captcha" in body.lower():
                raise RuntimeError("Naver access restriction/CAPTCHA surface detected")

        await save_artifacts(page, network_urls, "naver-results")

        body = await page.locator("body").inner_text(timeout=5_000)
        page_prices = sorted({int(x.replace(",", "")) for x in PRICE_RE.findall(body)})
        print("\n=== NAVER FLIGHTS RESULT ===")
        print(f"final_url={page.url}")
        print(f"page_title={await page.title()}")
        print(f"xhr_fetch_count={len(network_urls)}")
        print(f"page_price_count={len(page_prices)}")
        print(f"row_scoped_candidate_count={len(rows)}")

        if not rows:
            print("status=FAILED")
            print("reason=no compact row-scoped won price was captured within 45s")
            print(f"artifact_dir={ARTIFACT_DIR.resolve()}")
            print("The screenshot/body/network artifacts are enough to tune selectors without clicking Booking.")
            await page.wait_for_timeout(10_000)
            return 2

        print("status=SUCCESS")
        for index, row in enumerate(rows[:8], 1):
            snippet = re.sub(r"\s+", " ", str(row.get("text") or "")).strip()
            print(f"candidate_{index}={int(row['price']):,} KRW | {snippet[:300]}")
        print(f"lowest_visible_candidate={int(rows[0]['price']):,} KRW")
        print("booking_navigation_performed=False")
        print("external_checkout_navigation_performed=False")
        print(f"artifact_dir={ARTIFACT_DIR.resolve()}")
        print("Keep this window only for visual confirmation; the probe will close it after 12 seconds.")
        await page.wait_for_timeout(12_000)
        return 0
    except Exception as exc:
        if page is not None and not page.is_closed():
            await save_artifacts(page, network_urls, "naver-failed")
            try:
                await page.wait_for_timeout(10_000)
            except Exception:
                pass
        print("\n=== NAVER FLIGHTS RESULT ===")
        print("status=FAILED")
        print(f"error_type={type(exc).__name__}")
        print(f"error={exc}")
        print(f"artifact_dir={ARTIFACT_DIR.resolve()}")
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


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
