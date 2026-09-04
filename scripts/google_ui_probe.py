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

from playwright.async_api import Browser, Locator, Page, async_playwright


ORIGIN = "CJJ"
DESTINATION = "TPE"
DEPARTURE = "09/18/2026"
RETURN = "09/20/2026"
# Keep the UI in English for stable selectors. Region and displayed currency are
# independently forced with gl=kr and curr=KRW, then verified from the page footer.
GOOGLE_FLIGHTS_URL = "https://www.google.com/travel/flights?hl=en&gl=kr&curr=KRW"
_KRW_RE = re.compile(r"₩\s*([0-9][0-9,]*)")
_WON_RE = re.compile(r"([0-9][0-9,]*)\s+(?:South Korean won|Korean won|KRW)", re.I)


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


def parse_price(text: str | None) -> int | None:
    if not text:
        return None
    match = _KRW_RE.search(text) or _WON_RE.search(text)
    if not match:
        return None
    return int(match.group(1).replace(",", ""))


def step(message: str) -> None:
    print(message, flush=True)


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
    for candidate in candidates:
        if candidate.is_file():
            return candidate
    return None


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
            continue
    return None


async def last_visible(locator: Locator) -> Locator | None:
    visible: list[Locator] = []
    for index in range(await locator.count()):
        item = locator.nth(index)
        try:
            if await item.is_visible():
                visible.append(item)
        except Exception:
            continue
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
        raise RuntimeError("Google Flights origin input 'Where from?' was not found")
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
        raise RuntimeError("Google Flights destination input 'Where to?' was not found")
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
            await page.wait_for_timeout(1400)
    except Exception:
        pass


async def expand_results(page: Page) -> None:
    for label in ("View more flights", "More flights"):
        try:
            item = page.get_by_text(label, exact=False).last
            if await item.count() and await item.is_visible():
                await item.click(timeout=3500)
                await page.wait_for_timeout(1000)
                return
        except Exception:
            continue


async def collect_price_candidates(page: Page) -> list[PriceCandidate]:
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
        row_text = ""
        try:
            row_text = await item.evaluate(
                """el => {
                    const row = el.closest('li, [role="listitem"], [role="button"]');
                    return row ? (row.innerText || row.textContent || '') : '';
                }"""
            )
        except Exception:
            pass
        found.append(PriceCandidate(price, label or "aria-label", row_text.strip()[:2200]))

    if not found:
        body = await page.locator("body").inner_text()
        for raw in _KRW_RE.findall(body):
            price = int(raw.replace(",", ""))
            if 50_000 <= price <= 1_500_000:
                found.append(PriceCandidate(price, "body-text fallback", ""))

    dedup: dict[tuple[int, str], PriceCandidate] = {}
    for item in found:
        dedup[(item.price, item.row_text)] = item
    return sorted(dedup.values(), key=lambda item: item.price)


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


async def locale_diagnostics(page: Page) -> dict[str, str | bool | None]:
    body = await page.locator("body").inner_text()
    runtime = await page.evaluate(
        """() => ({
            webdriver: navigator.webdriver,
            language: navigator.language,
            languages: navigator.languages,
            timezone: Intl.DateTimeFormat().resolvedOptions().timeZone,
            userAgent: navigator.userAgent
        })"""
    )
    diagnostics: dict[str, str | bool | None] = {
        "url_gl_kr": "gl=kr" in page.url.lower(),
        "url_curr_krw": "curr=krw" in page.url.lower(),
        "footer_language": footer_setting(body, "Language"),
        "footer_location": footer_setting(body, "Location"),
        "footer_currency": footer_setting(body, "Currency"),
        "navigator_webdriver": runtime.get("webdriver"),
        "navigator_language": runtime.get("language"),
        "timezone": runtime.get("timezone"),
    }

    print("\n=== LOCALE / SESSION DIAGNOSTICS ===")
    for key, value in diagnostics.items():
        print(f"{key}={value}")
    return diagnostics


async def run_search_attempt(
    page: Page,
    *,
    attempt: int,
    max_attempts: int,
    timeout_ms: int,
    artifact_dir: Path,
) -> tuple[list[PriceCandidate], str]:
    print(f"\n=== SEARCH ATTEMPT {attempt}/{max_attempts} ===")
    step("[A] Opening Google Flights landing page")
    await page.goto(GOOGLE_FLIGHTS_URL, wait_until="domcontentloaded", timeout=timeout_ms)
    await dismiss_consent(page)

    step("[B] Entering CJJ -> TPE")
    await enter_origin(page)
    await enter_destination(page)

    step("[C] Entering 2026-09-18 .. 2026-09-20")
    await enter_dates(page)

    step("[D] Pressing Search")
    await press_search(page)

    step("[E] Waiting for results")
    await wait_for_results(page, timeout_ms)

    step("[F] Selecting Cheapest / expanding")
    await select_cheapest(page)
    await expand_results(page)

    step("[G] Reading KRW flight-row prices")
    body = await page.locator("body").inner_text()
    prices = await collect_price_candidates(page)
    await save_debug(page, artifact_dir, f"attempt-{attempt}-results")
    await locale_diagnostics(page)

    print(f"results_url={page.url}")
    print(f"price_candidates={len(prices)}")
    for index, candidate in enumerate(prices[:12], start=1):
        context_text = " | ".join(
            line.strip() for line in candidate.row_text.splitlines() if line.strip()
        )[:700]
        print(f"#{index} {candidate.price:,} KRW | {context_text or candidate.source}")

    return prices, body


async def main() -> None:
    if not sys.platform.startswith("win"):
        raise SystemExit("This probe is currently designed for Windows Edge acceptance testing")

    headless = env_bool("BROWSER_HEADLESS", False)
    if headless:
        raise SystemExit("Native Edge CDP acceptance must run visible; BROWSER_HEADLESS=false")

    timeout_ms = int(os.getenv("BROWSER_TIMEOUT_MS", "60000"))
    artifact_dir = Path(os.getenv("BROWSER_DEBUG_DIR", "artifacts/google-ui-win"))
    profile_dir = Path(os.getenv("BROWSER_PROFILE_DIR", "artifacts/google-profile-win"))
    keep_open_seconds = int(os.getenv("BROWSER_KEEP_OPEN_SECONDS", "12"))
    max_attempts = max(1, min(int(os.getenv("GOOGLE_UI_MAX_ATTEMPTS", "5")), 5))

    print("Google Flights native Edge UI probe")
    print("  CJJ -> TPE")
    print("  2026-09-18 ~ 2026-09-20")
    print("  1 adult / Economy / KRW")
    print("  Edge launch: native msedge.exe")
    print("  Playwright role: CDP attach only")
    print("  UI language: English (stable selectors)")
    print("  region: gl=kr")
    print("  currency: curr=KRW")
    print("  browser language hint: ko-KR")
    print("  session: dedicated persistent browser profile")
    print(f"  max fresh UI attempts: {max_attempts}")

    profile_dir.mkdir(parents=True, exist_ok=True)
    port = free_local_port()
    edge_process: subprocess.Popen | None = None
    playwright = await async_playwright().start()
    browser: Browser | None = None
    page: Page | None = None

    try:
        step("[1/2] Launching native Microsoft Edge")
        edge_process = launch_native_edge(profile_dir, port)
        await wait_for_cdp(port)

        step("[2/2] Attaching Playwright over CDP")
        browser = await playwright.chromium.connect_over_cdp(f"http://127.0.0.1:{port}")
        if not browser.contexts:
            raise RuntimeError("Native Edge exposed no browser context")
        context = browser.contexts[0]
        await context.set_extra_http_headers(
            {"Accept-Language": "ko-KR,ko;q=0.9,en-US;q=0.8,en;q=0.7"}
        )
        pages = context.pages
        page = pages[0] if pages else await context.new_page()
        page.set_default_timeout(timeout_ms)

        final_body = ""
        final_prices: list[PriceCandidate] = []
        for attempt in range(1, max_attempts + 1):
            if attempt > 1:
                wait_ms = 2000 + (attempt - 2) * 500
                print(f"Retrying after {wait_ms / 1000:.1f}s ...", flush=True)
                await page.wait_for_timeout(wait_ms)

            prices, body = await run_search_attempt(
                page,
                attempt=attempt,
                max_attempts=max_attempts,
                timeout_ms=timeout_ms,
                artifact_dir=artifact_dir,
            )
            final_prices = prices
            final_body = body

            if prices:
                print(f"\nPrice became visible on attempt {attempt}/{max_attempts}.")
                break

            if "price unavailable" not in body.lower():
                raise RuntimeError(
                    "Google UI completed search but no KRW flight-row price was detected"
                )

            print(f"attempt {attempt}: Google UI returned Price unavailable")

        if not final_prices:
            await save_debug(page, artifact_dir, "cjj-tpe-error")
            raise RuntimeError(
                f"Native Edge UI returned Price unavailable on all {max_attempts} fresh searches"
            )

        print("\n=== SUMMARY ===")
        print(f"ui_lowest={final_prices[0].price:,} KRW")
        print(f"artifact_dir={artifact_dir.resolve()}")
        print("acceptance=PRICE_VISIBLE")

        if keep_open_seconds > 0:
            print(f"\nBrowser stays open for {keep_open_seconds}s for visual confirmation ...")
            await page.wait_for_timeout(keep_open_seconds * 1000)
    except Exception as exc:
        if page is not None:
            await save_debug(page, artifact_dir, "cjj-tpe-error")
            try:
                await locale_diagnostics(page)
            except Exception:
                pass
            print(f"\nerror_url={page.url}")
        print(f"\nPROBE FAILED: {type(exc).__name__}: {exc}")
        print(f"artifacts={artifact_dir.resolve()}")
        if page is not None and keep_open_seconds > 0:
            print(
                f"Browser stays open for {keep_open_seconds}s so the failure page can be inspected ..."
            )
            try:
                await page.wait_for_timeout(keep_open_seconds * 1000)
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
