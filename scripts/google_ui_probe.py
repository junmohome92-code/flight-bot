from __future__ import annotations

import asyncio
import os
import re
import socket
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path

from playwright.async_api import Browser, BrowserContext, Locator, Page, async_playwright


ORIGIN = "CJJ"
DESTINATION = "TPE"
DEPARTURE = "09/18/2026"
RETURN = "09/20/2026"
GOOGLE_FLIGHTS_URL = "https://www.google.com/travel/flights?hl=en&gl=kr&curr=KRW"
_KRW_RE = re.compile(r"₩\s*([0-9][0-9,]*)")
_WON_RE = re.compile(r"([0-9][0-9,]*)\s+(?:South Korean won|Korean won|KRW)", re.I)
_TIME_RE = re.compile(r"\b\d{1,2}:\d{2}(?:\s?[AP]M)?\b", re.I)
_STOP_RE = re.compile(r"\b(?:nonstop|\d+\s+stops?)\b", re.I)
_DURATION_RE = re.compile(r"\b\d+\s*hr(?:\s*\d+\s*min)?\b", re.I)


@dataclass(frozen=True)
class PriceCandidate:
    price: int
    source: str
    row_text: str


def env_bool(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def parse_prices(text: str | None) -> list[int]:
    if not text:
        return []
    values = [int(raw.replace(",", "")) for raw in _KRW_RE.findall(text)]
    values.extend(int(raw.replace(",", "")) for raw in _WON_RE.findall(text))
    return sorted(set(values))


def parse_price(text: str | None) -> int | None:
    values = parse_prices(text)
    return values[0] if values else None


def row_looks_like_flight_result(text: str | None) -> bool:
    if not text:
        return False
    upper = text.upper()
    has_route = ORIGIN in upper and DESTINATION in upper
    time_count = len(_TIME_RE.findall(text))
    if time_count < 2:
        return False
    return has_route or bool(_STOP_RE.search(text) or _DURATION_RE.search(text))


def free_local_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def find_windows_edge() -> Path | None:
    candidates = [
        Path(os.environ.get("PROGRAMFILES(X86)", "")) / "Microsoft/Edge/Application/msedge.exe",
        Path(os.environ.get("PROGRAMFILES", "")) / "Microsoft/Edge/Application/msedge.exe",
        Path(os.environ.get("LOCALAPPDATA", "")) / "Microsoft/Edge/Application/msedge.exe",
    ]
    return next((path for path in candidates if path.is_file()), None)


def launch_native_edge(profile_dir: Path, port: int) -> subprocess.Popen:
    edge = find_windows_edge()
    if edge is None:
        raise RuntimeError("Microsoft Edge executable was not found")
    args = [
        str(edge),
        f"--remote-debugging-port={port}",
        f"--user-data-dir={profile_dir.resolve()}",
        "--no-first-run",
        "--no-default-browser-check",
        "--lang=ko-KR",
        GOOGLE_FLIGHTS_URL,
    ]
    creationflags = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
    return subprocess.Popen(
        args,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        creationflags=creationflags,
    )


async def wait_for_cdp(port: int, timeout_seconds: float = 15.0) -> None:
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        try:
            _, writer = await asyncio.open_connection("127.0.0.1", port)
            writer.close()
            await writer.wait_closed()
            return
        except OSError:
            await asyncio.sleep(0.25)
    raise RuntimeError(f"Edge remote debugging port {port} did not open")


async def first_visible(locator: Locator) -> Locator | None:
    for index in range(await locator.count()):
        item = locator.nth(index)
        try:
            if await item.is_visible():
                return item
        except Exception:
            pass
    return None


async def last_visible(locator: Locator) -> Locator | None:
    visible: list[Locator] = []
    for index in range(await locator.count()):
        item = locator.nth(index)
        try:
            if await item.is_visible():
                visible.append(item)
        except Exception:
            pass
    return visible[-1] if visible else None


async def dismiss_consent(page: Page) -> None:
    for label in ("Accept all", "Reject all", "I agree"):
        try:
            button = page.get_by_role("button", name=label, exact=False).first
            if await button.count() and await button.is_visible():
                await button.click(timeout=2500)
                await page.wait_for_timeout(500)
                return
        except Exception:
            pass


async def enter_origin(page: Page) -> None:
    field = await first_visible(page.locator("input[aria-label='Where from?']"))
    if field is None:
        raise RuntimeError("Google Flights origin input was not found")
    await field.click()
    await page.wait_for_timeout(350)
    popup = await last_visible(page.locator("input[aria-label*='Where else?']")) or field
    await popup.fill(ORIGIN)
    await page.wait_for_timeout(650)
    await popup.press("ArrowDown")
    await popup.press("Enter")
    await page.wait_for_timeout(450)


async def enter_destination(page: Page) -> None:
    field = await first_visible(page.locator("input[aria-label^='Where to?']"))
    if field is None:
        raise RuntimeError("Google Flights destination input was not found")
    await field.click()
    await page.wait_for_timeout(350)
    popup = await last_visible(page.locator("input[aria-label^='Where to?']")) or field
    await popup.fill(DESTINATION)
    await page.wait_for_timeout(650)
    await popup.press("ArrowDown")
    await popup.press("Enter")
    await page.wait_for_timeout(450)


async def enter_dates(page: Page) -> None:
    departure = await first_visible(page.locator("input[aria-label='Departure']"))
    if departure is None:
        raise RuntimeError("Google Flights Departure input was not found")
    await departure.click()
    await page.wait_for_timeout(450)
    departure_popup = await last_visible(page.locator("input[aria-label='Departure']")) or departure
    await departure_popup.fill(DEPARTURE)
    await page.wait_for_timeout(350)

    return_popup = await last_visible(page.locator("input[aria-label='Return']"))
    if return_popup is None:
        raise RuntimeError("Google Flights Return input was not found")
    await return_popup.fill(RETURN)
    await page.wait_for_timeout(350)
    await return_popup.press("Enter")
    await page.wait_for_timeout(350)
    try:
        await return_popup.press("Enter")
    except Exception:
        pass
    await page.wait_for_timeout(500)


async def press_search(page: Page) -> None:
    button = await first_visible(page.locator("button[aria-label='Search']"))
    if button is None:
        raise RuntimeError("Google Flights Search button was not found")
    await button.click()


async def wait_for_results(page: Page, timeout_ms: int) -> None:
    deadline = asyncio.get_running_loop().time() + timeout_ms / 1000
    while asyncio.get_running_loop().time() < deadline:
        body = (await page.locator("body").inner_text()).lower()
        if "departing flights" in body or "best departing flights" in body:
            return
        if "price unavailable" in body and ("cjj" in body or "cheongju" in body):
            return
        await page.wait_for_timeout(500)
    body = (await page.locator("body").inner_text())[:2500]
    raise RuntimeError(f"Google Flights results did not become visible. Body sample:\n{body}")


async def select_cheapest(page: Page) -> None:
    try:
        cheapest = page.get_by_text("Cheapest", exact=True).first
        if await cheapest.count() and await cheapest.is_visible():
            await cheapest.click(timeout=4000)
            await page.wait_for_timeout(1200)
    except Exception:
        pass


async def expand_results(page: Page) -> None:
    for label in ("View more flights", "More flights"):
        try:
            item = page.get_by_text(label, exact=False).last
            if await item.count() and await item.is_visible():
                await item.click(timeout=3500)
                await page.wait_for_timeout(900)
                return
        except Exception:
            pass


async def _row_text_for_price_element(item: Locator) -> str:
    try:
        return str(
            await item.evaluate(
                """el => {
                    const rows = [
                        el.closest('li'),
                        el.closest('[role="listitem"]'),
                        el.closest('[role="button"]')
                    ];
                    for (const row of rows) {
                        if (!row) continue;
                        const text = (row.innerText || row.textContent || '').trim();
                        if (text) return text;
                    }
                    return '';
                }"""
            )
        )
    except Exception:
        return ""


async def collect_price_candidates(page: Page) -> list[PriceCandidate]:
    """Collect only KRW prices attached to DOM elements that look like flight rows."""
    found: list[PriceCandidate] = []

    labelled = page.locator("[aria-label]")
    for index in range(await labelled.count()):
        item = labelled.nth(index)
        try:
            label = await item.get_attribute("aria-label")
        except Exception:
            continue
        price = parse_price(label)
        if price is None or not 50_000 <= price <= 1_500_000:
            continue
        row_text = (await _row_text_for_price_element(item)).strip()[:2200]
        if not row_looks_like_flight_result(row_text):
            continue
        found.append(PriceCandidate(price, label or "aria-label", row_text))

    # Some Google builds expose the visible price as text rather than an aria-label.
    # This fallback is still row-scoped; it never scans the page body for the minimum.
    rows = page.locator("li, [role='listitem'], [role='button']")
    for index in range(await rows.count()):
        row = rows.nth(index)
        try:
            if not await row.is_visible():
                continue
            row_text = (await row.inner_text()).strip()
        except Exception:
            continue
        if not row_looks_like_flight_result(row_text):
            continue
        for price in parse_prices(row_text):
            if 50_000 <= price <= 1_500_000:
                found.append(PriceCandidate(price, "flight-row text", row_text[:2200]))

    dedup: dict[tuple[int, str], PriceCandidate] = {}
    for item in found:
        dedup[(item.price, item.row_text)] = item
    return sorted(dedup.values(), key=lambda item: item.price)


async def wait_for_price_candidates(page: Page, timeout_ms: int) -> list[PriceCandidate]:
    deadline = asyncio.get_running_loop().time() + timeout_ms / 1000
    while asyncio.get_running_loop().time() < deadline:
        prices = await collect_price_candidates(page)
        if prices:
            return prices
        await page.wait_for_timeout(750)
    return []


async def save_debug(page: Page, artifact_dir: Path, stem: str) -> None:
    artifact_dir.mkdir(parents=True, exist_ok=True)
    try:
        await page.screenshot(path=str(artifact_dir / f"{stem}.png"), full_page=True)
    except Exception:
        pass
    try:
        (artifact_dir / f"{stem}.txt").write_text(
            await page.locator("body").inner_text(), encoding="utf-8"
        )
    except Exception:
        pass
    try:
        (artifact_dir / f"{stem}.html").write_text(await page.content(), encoding="utf-8")
    except Exception:
        pass


def _clean_setting_line(value: str) -> str:
    return value.replace("\u200b", "").replace("\u2060", "").strip()


def footer_setting(body: str, label: str) -> str | None:
    lines = [_clean_setting_line(line) for line in body.splitlines() if _clean_setting_line(line)]
    wanted = label.lower()
    for index, line in enumerate(lines):
        lower = line.lower()
        if lower == wanted and index + 1 < len(lines):
            return lines[index + 1]
        if lower.startswith(wanted) and len(line) > len(label):
            value = line[len(label):].strip(" :\t")
            if value:
                return value
    return None


async def print_session_diagnostics(page: Page, label: str) -> None:
    body = await page.locator("body").inner_text()
    runtime = await page.evaluate(
        """() => ({
            webdriver: navigator.webdriver,
            language: navigator.language,
            timezone: Intl.DateTimeFormat().resolvedOptions().timeZone
        })"""
    )
    print(f"\n=== {label} SESSION ===")
    print(f"url={page.url}")
    print(f"url_gl_kr={'gl=kr' in page.url.lower()}")
    print(f"url_curr_krw={'curr=krw' in page.url.lower()}")
    print(f"footer_language={footer_setting(body, 'Language')}")
    print(f"footer_location={footer_setting(body, 'Location')}")
    print(f"footer_currency={footer_setting(body, 'Currency')}")
    print(f"navigator_webdriver={runtime.get('webdriver')}")
    print(f"navigator_language={runtime.get('language')}")
    print(f"timezone={runtime.get('timezone')}")


async def generate_search_url(page: Page, timeout_ms: int, artifact_dir: Path) -> str:
    print("[1/7] Opening Google Flights landing page", flush=True)
    await page.goto(GOOGLE_FLIGHTS_URL, wait_until="domcontentloaded", timeout=timeout_ms)
    await dismiss_consent(page)

    print("[2/7] Entering CJJ -> TPE", flush=True)
    await enter_origin(page)
    await enter_destination(page)

    print("[3/7] Entering dates", flush=True)
    await enter_dates(page)

    print("[4/7] Pressing Search", flush=True)
    await press_search(page)

    print("[5/7] Waiting for first result page", flush=True)
    await wait_for_results(page, timeout_ms)
    await save_debug(page, artifact_dir, "generator-tab")
    await print_session_diagnostics(page, "GENERATOR TAB")
    search_url = page.url
    if "/travel/flights/search" not in search_url:
        raise RuntimeError(f"Google Flights did not produce a search URL: {search_url}")
    print(f"generated_search_url={search_url}")
    return search_url


async def inspect_fresh_tab(
    context: BrowserContext,
    search_url: str,
    *,
    attempt: int,
    timeout_ms: int,
    price_wait_ms: int,
    artifact_dir: Path,
) -> tuple[Page, list[PriceCandidate], str]:
    print(f"\n=== FRESH TAB ATTEMPT {attempt} ===", flush=True)
    page = await context.new_page()
    page.set_default_timeout(timeout_ms)
    try:
        print("[6/7] Opening generated search URL in a NEW tab", flush=True)
        await page.goto(search_url, wait_until="domcontentloaded", timeout=timeout_ms)
        print(f"fresh_url={page.url}")
        await wait_for_results(page, timeout_ms)
        await select_cheapest(page)
        await expand_results(page)

        print("[7/7] Reading row-scoped prices from fresh tab", flush=True)
        prices = await wait_for_price_candidates(page, price_wait_ms)
        body = await page.locator("body").inner_text()
        await save_debug(page, artifact_dir, f"fresh-tab-{attempt}")
        await print_session_diagnostics(page, f"FRESH TAB {attempt}")
        print(f"price_candidates={len(prices)}")
        for index, candidate in enumerate(prices[:12], start=1):
            context_text = " | ".join(
                line.strip() for line in candidate.row_text.splitlines() if line.strip()
            )[:700]
            print(f"#{index} {candidate.price:,} KRW | {context_text or candidate.source}")
        return page, prices, body
    except Exception:
        await save_debug(page, artifact_dir, f"fresh-tab-{attempt}-error")
        try:
            await print_session_diagnostics(page, f"FRESH TAB {attempt} ERROR")
        except Exception:
            pass
        raise


async def main() -> None:
    if not sys.platform.startswith("win"):
        raise SystemExit("This probe is currently designed for Windows Edge acceptance testing")
    if env_bool("BROWSER_HEADLESS", False):
        raise SystemExit("This acceptance probe must run visible; BROWSER_HEADLESS=false")

    timeout_ms = int(os.getenv("BROWSER_TIMEOUT_MS", "60000"))
    price_wait_ms = max(1000, int(os.getenv("GOOGLE_UI_PRICE_WAIT_MS", "15000")))
    artifact_dir = Path(os.getenv("BROWSER_DEBUG_DIR", "artifacts/google-ui-win"))
    profile_dir = Path(os.getenv("BROWSER_PROFILE_DIR", "artifacts/google-profile-win"))
    max_fresh_tabs = max(1, min(int(os.getenv("GOOGLE_UI_MAX_ATTEMPTS", "3")), 5))
    keep_open_seconds = int(os.getenv("BROWSER_KEEP_OPEN_SECONDS", "12"))

    print("Google Flights native Edge fresh-tab probe")
    print("  CJJ -> TPE / 2026-09-18 ~ 2026-09-20")
    print("  first tab: generate canonical Google Flights URL")
    print("  next tabs: reopen EXACT same URL and read flight-row prices")
    print("  body-wide minimum fallback: DISABLED")
    print("  based on user-confirmed manual copy/open behavior")
    print(f"  fresh tabs: {max_fresh_tabs}")
    print(f"  row-price wait per fresh tab: {price_wait_ms} ms")

    profile_dir.mkdir(parents=True, exist_ok=True)
    artifact_dir.mkdir(parents=True, exist_ok=True)
    port = free_local_port()
    edge_process: subprocess.Popen | None = None
    playwright = await async_playwright().start()
    browser: Browser | None = None
    last_page: Page | None = None

    try:
        edge_process = launch_native_edge(profile_dir, port)
        await wait_for_cdp(port)
        browser = await playwright.chromium.connect_over_cdp(f"http://127.0.0.1:{port}")
        if not browser.contexts:
            raise RuntimeError("Native Edge exposed no browser context")
        context = browser.contexts[0]
        generator = context.pages[0] if context.pages else await context.new_page()
        generator.set_default_timeout(timeout_ms)
        last_page = generator

        search_url = await generate_search_url(generator, timeout_ms, artifact_dir)

        for attempt in range(1, max_fresh_tabs + 1):
            page, prices, body = await inspect_fresh_tab(
                context,
                search_url,
                attempt=attempt,
                timeout_ms=timeout_ms,
                price_wait_ms=price_wait_ms,
                artifact_dir=artifact_dir,
            )
            last_page = page
            if prices:
                print("\n=== SUMMARY ===")
                print(f"fresh_tab_attempt={attempt}")
                print(f"ui_lowest={prices[0].price:,} KRW")
                print("acceptance=PRICE_VISIBLE_AFTER_FRESH_TAB")
                print(f"artifact_dir={artifact_dir.resolve()}")
                if keep_open_seconds > 0:
                    print(f"Browser stays open for {keep_open_seconds}s for visual confirmation ...")
                    await page.wait_for_timeout(keep_open_seconds * 1000)
                return

            unavailable = "price unavailable" in body.lower()
            print(f"fresh_tab_{attempt}_price_unavailable={unavailable}")
            if attempt < max_fresh_tabs:
                await page.close()
                await asyncio.sleep(1.0)

        raise RuntimeError(
            "Generated URL was correct, but all automated fresh tabs still showed no row-scoped KRW price"
        )
    except Exception as exc:
        if last_page is not None:
            await save_debug(last_page, artifact_dir, "final-error")
        print(f"\nPROBE FAILED: {type(exc).__name__}: {exc}")
        print(f"artifacts={artifact_dir.resolve()}")
        if last_page is not None and keep_open_seconds > 0:
            try:
                await last_page.wait_for_timeout(keep_open_seconds * 1000)
            except Exception:
                pass
        raise SystemExit(2) from exc
    finally:
        if browser is not None:
            try:
                await browser.close()
            except Exception:
                pass
        await playwright.stop()
        if edge_process is not None and edge_process.poll() is None:
            try:
                edge_process.terminate()
            except Exception:
                pass


if __name__ == "__main__":
    asyncio.run(main())
