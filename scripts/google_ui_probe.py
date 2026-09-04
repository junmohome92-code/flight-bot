from __future__ import annotations

import asyncio
import os
import re
import sys
from dataclasses import dataclass
from pathlib import Path

from playwright.async_api import BrowserContext, Locator, Page, async_playwright
from playwright.async_api import TimeoutError as PlaywrightTimeoutError


ORIGIN = "CJJ"
DESTINATION = "TPE"
DEPARTURE = "09/18/2026"
RETURN = "09/20/2026"
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

    popup = await last_visible(page.locator("input[aria-label*='Where else?']"))
    if popup is None:
        # Google occasionally keeps the original field editable instead of opening a second input.
        popup = field
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

    popup = await last_visible(page.locator("input[aria-label^='Where to?']"))
    if popup is None:
        popup = field
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

    departure_popup = await last_visible(page.locator("input[aria-label='Departure']"))
    if departure_popup is None:
        departure_popup = departure
    await departure_popup.fill(DEPARTURE)
    await page.wait_for_timeout(350)

    return_popup = await last_visible(page.locator("input[aria-label='Return']"))
    if return_popup is None:
        raise RuntimeError("Google Flights Return input was not found")
    await return_popup.fill(RETURN)
    await page.wait_for_timeout(350)
    await return_popup.press("Enter")
    await page.wait_for_timeout(350)
    # Some layouts use the first Enter to select the date and the second to close the date picker.
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

    # Fallback for UI variants where price spans have text but no aria-label.
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


async def launch_context(playwright, profile_dir: Path, headless: bool) -> tuple[BrowserContext, str]:
    requested = os.getenv("BROWSER_CHANNEL", "").strip()
    if requested:
        candidates: list[str | None] = [requested]
    elif sys.platform.startswith("win") and not headless:
        # Prefer the user's installed browser engine on Windows. The profile is dedicated to this bot,
        # so the real personal Edge/Chrome profile is never touched.
        candidates = ["msedge", "chrome", None]
    else:
        candidates = [None, "msedge", "chrome"]

    errors: list[str] = []
    for channel in candidates:
        try:
            kwargs = {
                "user_data_dir": str(profile_dir),
                "headless": headless,
                "locale": "en-US",
                "timezone_id": "Asia/Seoul",
                "viewport": {"width": 1440, "height": 1000},
                "args": ["--disable-dev-shm-usage"],
            }
            if channel:
                kwargs["channel"] = channel
            context = await playwright.chromium.launch_persistent_context(**kwargs)
            return context, channel or "playwright-chromium"
        except Exception as exc:
            errors.append(f"{channel or 'playwright-chromium'}: {type(exc).__name__}: {exc}")

    raise RuntimeError("Could not launch any Chromium browser:\n" + "\n".join(errors))


async def main() -> None:
    headless = env_bool("BROWSER_HEADLESS", False)
    timeout_ms = int(os.getenv("BROWSER_TIMEOUT_MS", "60000"))
    artifact_dir = Path(os.getenv("BROWSER_DEBUG_DIR", "artifacts/google-ui-win"))
    profile_dir = Path(os.getenv("BROWSER_PROFILE_DIR", "artifacts/google-profile-win"))
    keep_open_seconds = int(os.getenv("BROWSER_KEEP_OPEN_SECONDS", "8" if not headless else "0"))

    print("Google Flights real UI probe")
    print("  CJJ -> TPE")
    print("  2026-09-18 ~ 2026-09-20")
    print("  1 adult / Economy / KRW")
    print("  route entry: Google Flights UI (no tfs direct-link)")
    print("  session: dedicated persistent browser profile")
    print(f"  headless: {headless}")

    playwright = await async_playwright().start()
    context: BrowserContext | None = None
    page: Page | None = None
    try:
        profile_dir.mkdir(parents=True, exist_ok=True)
        context, channel = await launch_context(playwright, profile_dir, headless)
        page = context.pages[0] if context.pages else await context.new_page()
        page.set_default_timeout(timeout_ms)
        print(f"  browser: {channel}")
        print(f"  profile: {profile_dir.resolve()}")

        await page.goto(
            "https://www.google.com/travel/flights?hl=en&curr=KRW&gl=kr",
            wait_until="domcontentloaded",
            timeout=timeout_ms,
        )
        await dismiss_consent(page)
        await enter_origin(page)
        await enter_destination(page)
        await enter_dates(page)
        await press_search(page)
        await wait_for_results(page, timeout_ms)
        await select_cheapest(page)
        await expand_results(page)

        await save_debug(page, artifact_dir, "cjj-tpe-results")
        body = await page.locator("body").inner_text()
        prices = await collect_price_candidates(page)

        print(f"\nresults_url={page.url}")
        print(f"price_candidates={len(prices)}")
        for index, candidate in enumerate(prices[:12], start=1):
            context_text = " | ".join(
                line.strip() for line in candidate.row_text.splitlines() if line.strip()
            )[:700]
            print(f"#{index} {candidate.price:,} KRW | {context_text or candidate.source}")

        if not prices:
            if "price unavailable" in body.lower():
                raise RuntimeError(
                    "Google UI search completed but this browser session still shows Price unavailable"
                )
            raise RuntimeError("Google UI search completed but no KRW flight-row price was detected")

        lowest = prices[0]
        print("\n=== SUMMARY ===")
        print(f"ui_lowest={lowest.price:,} KRW")
        print(f"artifact_dir={artifact_dir.resolve()}")
        print("acceptance=PRICE_VISIBLE")

        if keep_open_seconds > 0:
            print(f"\nBrowser stays open for {keep_open_seconds}s for visual confirmation ...")
            await page.wait_for_timeout(keep_open_seconds * 1000)
    except Exception as exc:
        if page is not None:
            await save_debug(page, artifact_dir, "cjj-tpe-error")
            print(f"\nerror_url={page.url}")
        print(f"\nPROBE FAILED: {type(exc).__name__}: {exc}")
        print(f"artifacts={artifact_dir.resolve()}")
        if page is not None and keep_open_seconds > 0:
            print(f"Browser stays open for {keep_open_seconds}s so the failure page can be inspected ...")
            try:
                await page.wait_for_timeout(keep_open_seconds * 1000)
            except Exception:
                pass
        raise SystemExit(2) from exc
    finally:
        if context is not None:
            await context.close()
        await playwright.stop()


if __name__ == "__main__":
    asyncio.run(main())
