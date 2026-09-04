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
_KRW_TEXT_RE = re.compile(r"₩\s*[0-9][0-9,]*")
_WON_RE = re.compile(r"([0-9][0-9,]*)\s+(?:South Korean won|Korean won|KRW)", re.I)
_TIME_RE = re.compile(r"\b\d{1,2}:\d{2}(?:\s?[AP]M)?\b", re.I)
_STOP_RE = re.compile(r"(?:\bnonstop\b|\b\d+\s+stops?\b|직항|경유\s*\d*회?)", re.I)
_DURATION_RE = re.compile(
    r"(?:\b\d+\s*hr(?:\s*\d+\s*min)?\b|\d+\s*시간(?:\s*\d+\s*분)?)",
    re.I,
)
_CHEAPEST_TAB_RE = re.compile(r"^\s*(?:Cheapest\b|최저가)", re.I)


@dataclass(frozen=True)
class PriceCandidate:
    price: int
    source: str
    row_text: str


@dataclass(frozen=True)
class CheapestTabState:
    found: bool
    clicked: bool
    text: str
    advertised_price: int | None


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


def looks_like_cheapest_tab(text: str | None) -> bool:
    return bool(text and _CHEAPEST_TAB_RE.search(text))


def cheapest_price_consistent(advertised_price: int | None, row_lowest: int | None) -> bool:
    if row_lowest is None:
        return False
    return advertised_price is None or row_lowest <= advertised_price


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
    for label in ("Accept all", "Reject all", "I agree", "모두 동의", "모두 거부"):
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
        field = await first_visible(page.locator("input[aria-label*='출발']"))
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
        field = await first_visible(page.locator("input[aria-label*='도착']"))
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
        departure = await first_visible(page.locator("input[aria-label*='출발']"))
    if departure is None:
        raise RuntimeError("Google Flights Departure input was not found")
    await departure.click()
    await page.wait_for_timeout(450)
    departure_popup = await last_visible(page.locator("input[aria-label='Departure']")) or departure
    await departure_popup.fill(DEPARTURE)
    await page.wait_for_timeout(350)

    return_popup = await last_visible(page.locator("input[aria-label='Return']"))
    if return_popup is None:
        return_popup = await last_visible(page.locator("input[aria-label*='귀국']"))
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
        button = await first_visible(page.locator("button[aria-label*='검색']"))
    if button is None:
        raise RuntimeError("Google Flights Search button was not found")
    await button.click()


async def wait_for_results(page: Page, timeout_ms: int) -> None:
    deadline = asyncio.get_running_loop().time() + timeout_ms / 1000
    while asyncio.get_running_loop().time() < deadline:
        body = (await page.locator("body").inner_text()).lower()
        if (
            "departing flights" in body
            or "best departing flights" in body
            or "출발 항공편" in body
            or "인기 출발 항공편" in body
        ):
            return
        if (
            ("price unavailable" in body or "가격 정보를 이용할 수" in body)
            and ("cjj" in body or "cheongju" in body or "청주" in body)
        ):
            return
        await page.wait_for_timeout(500)
    body = (await page.locator("body").inner_text())[:2500]
    raise RuntimeError(f"Google Flights results did not become visible. Body sample:\n{body}")


async def _control_text(control: Locator) -> str:
    values: list[str] = []
    try:
        value = (await control.inner_text()).strip()
        if value:
            values.append(value)
    except Exception:
        pass
    try:
        value = (await control.get_attribute("aria-label") or "").strip()
        if value and value not in values:
            values.append(value)
    except Exception:
        pass
    return " | ".join(values)


async def select_cheapest(page: Page) -> CheapestTabState:
    control: Locator | None = None
    for locator in (
        page.get_by_role("tab", name=_CHEAPEST_TAB_RE),
        page.get_by_role("button", name=_CHEAPEST_TAB_RE),
        page.get_by_text(_CHEAPEST_TAB_RE),
    ):
        control = await first_visible(locator)
        if control is not None:
            break

    if control is None:
        print("cheapest_tab_found=False")
        return CheapestTabState(False, False, "", None)

    text_before = await _control_text(control)
    advertised_price = parse_price(text_before)
    print("cheapest_tab_found=True")
    print(f"cheapest_tab_text={text_before or '<empty>'}")
    if advertised_price is not None:
        print(f"cheapest_advertised={advertised_price:,} KRW")
    else:
        print("cheapest_advertised=unknown")

    try:
        await control.click(timeout=5000)
        await page.wait_for_timeout(1800)
    except Exception as exc:
        print(f"cheapest_tab_clicked=False ({type(exc).__name__}: {exc})")
        return CheapestTabState(True, False, text_before, advertised_price)

    text_after = await _control_text(control)
    if text_after:
        advertised_price = parse_price(text_after) or advertised_price
    print("cheapest_tab_clicked=True")

    try:
        state = await control.evaluate(
            """el => {
                const host = el.closest('[role="tab"], button, [role="button"]') || el;
                return {
                    ariaSelected: host.getAttribute('aria-selected'),
                    ariaPressed: host.getAttribute('aria-pressed'),
                    text: (host.innerText || host.textContent || '').trim()
                };
            }"""
        )
        print(f"cheapest_tab_aria_selected={state.get('ariaSelected')}")
        print(f"cheapest_tab_aria_pressed={state.get('ariaPressed')}")
    except Exception:
        pass

    return CheapestTabState(True, True, text_after or text_before, advertised_price)


async def expand_results(page: Page) -> None:
    for label in ("View more flights", "More flights", "항공편 더보기", "더 많은 항공편"):
        try:
            item = page.get_by_text(label, exact=False).last
            if await item.count() and await item.is_visible():
                await item.click(timeout=3500)
                await page.wait_for_timeout(900)
                print(f"expanded_results_with={label}")
                return
        except Exception:
            pass


async def _row_text_for_price_element(item: Locator) -> str:
    try:
        return str(
            await item.evaluate(
                """el => {
                    let node = el;
                    for (let depth = 0; depth < 12 && node; depth += 1, node = node.parentElement) {
                        const text = (node.innerText || node.textContent || '').trim();
                        if (!text) continue;
                        const upper = text.toUpperCase();
                        const times = text.match(/\b\d{1,2}:\d{2}(?:\s?[AP]M)?\b/gi) || [];
                        const hasRoute = upper.includes('CJJ') && upper.includes('TPE');
                        const hasFlightShape = /nonstop|stops?|직항|경유|\bhr\b|시간/i.test(text);
                        if (times.length >= 2 && (hasRoute || hasFlightShape)) {
                            return text;
                        }
                    }
                    return '';
                }"""
            )
        )
    except Exception:
        return ""


async def collect_price_candidates(page: Page) -> list[PriceCandidate]:
    """Collect only KRW prices whose nearest useful ancestor looks like a flight row."""
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

    # Visible price text is also inspected, but the price is accepted only after
    # climbing to a flight-shaped ancestor. We never take the page-wide minimum.
    visible_prices = page.get_by_text(_KRW_TEXT_RE)
    for index in range(await visible_prices.count()):
        item = visible_prices.nth(index)
        try:
            if not await item.is_visible():
                continue
            own_text = (await item.inner_text()).strip()
        except Exception:
            try:
                own_text = (await item.text_content() or "").strip()
            except Exception:
                continue
        values = parse_prices(own_text)
        if not values:
            continue
        row_text = (await _row_text_for_price_element(item)).strip()[:2200]
        if not row_looks_like_flight_result(row_text):
            continue
        for price in values:
            if 50_000 <= price <= 1_500_000:
                found.append(PriceCandidate(price, "flight-row visible text", row_text))

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
) -> tuple[Page, list[PriceCandidate], str, CheapestTabState]:
    print(f"\n=== FRESH TAB ATTEMPT {attempt} ===", flush=True)
    page = await context.new_page()
    page.set_default_timeout(timeout_ms)
    try:
        print("[6/7] Opening generated search URL in a NEW tab", flush=True)
        await page.goto(search_url, wait_until="domcontentloaded", timeout=timeout_ms)
        print(f"fresh_url={page.url}")
        await wait_for_results(page, timeout_ms)
        cheapest_state = await select_cheapest(page)
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
        return page, prices, body, cheapest_state
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
    print("  next tabs: reopen EXACT same URL and select Cheapest/최저가")
    print("  only accept flight-row prices after cheapest-tab selection")
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
            page, prices, body, cheapest_state = await inspect_fresh_tab(
                context,
                search_url,
                attempt=attempt,
                timeout_ms=timeout_ms,
                price_wait_ms=price_wait_ms,
                artifact_dir=artifact_dir,
            )
            last_page = page
            row_lowest = prices[0].price if prices else None
            price_match = cheapest_price_consistent(cheapest_state.advertised_price, row_lowest)

            if prices:
                print("render_gate=PRICE_VISIBLE_AFTER_FRESH_TAB")
            print(f"cheapest_tab_ready={cheapest_state.found and cheapest_state.clicked}")
            print(f"cheapest_price_match={price_match}")
            if cheapest_state.advertised_price is not None:
                print(f"cheapest_advertised={cheapest_state.advertised_price:,} KRW")
            if row_lowest is not None:
                print(f"cheapest_row_lowest={row_lowest:,} KRW")

            if cheapest_state.found and cheapest_state.clicked and prices and price_match:
                print("\n=== SUMMARY ===")
                print(f"fresh_tab_attempt={attempt}")
                if cheapest_state.advertised_price is not None:
                    print(f"cheapest_advertised={cheapest_state.advertised_price:,} KRW")
                print(f"ui_lowest={row_lowest:,} KRW")
                print("acceptance=CHEAPEST_PRICE_VISIBLE_AFTER_FRESH_TAB")
                print(f"artifact_dir={artifact_dir.resolve()}")
                if keep_open_seconds > 0:
                    print(f"Browser stays open for {keep_open_seconds}s for visual confirmation ...")
                    await page.wait_for_timeout(keep_open_seconds * 1000)
                return

            unavailable = "price unavailable" in body.lower()
            print(f"fresh_tab_{attempt}_price_unavailable={unavailable}")
            if cheapest_state.advertised_price is not None and row_lowest is not None and not price_match:
                print(
                    "fresh_tab_mismatch="
                    f"tab advertised {cheapest_state.advertised_price:,} KRW but "
                    f"row parser lowest was {row_lowest:,} KRW"
                )
            if attempt < max_fresh_tabs:
                await page.close()
                await asyncio.sleep(1.0)

        raise RuntimeError(
            "Fresh tabs rendered, but the Cheapest/최저가 tab and matching row-scoped lowest price "
            "were not both confirmed"
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
