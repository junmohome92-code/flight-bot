from __future__ import annotations

from playwright.async_api import Locator

from .models import WatchSlot
from .providers import GoogleFlightsPlaywrightProvider


class RuntimeGoogleResultsProvider(GoogleFlightsPlaywrightProvider):
    """Production identity for the canonical accepted Google-results provider.

    Windows acceptance executes this class end-to-end. The compact row extractor
    mirrors the proven acceptance semantics: a route token may be absent because
    current Google cards often show separate airport-code text instead of a
    literal ``CJJ-TPE`` token. If route codes are present they must still appear
    in the expected direction, and broad page/list containers remain rejected.
    """

    name = "google-playwright-results-observed-accepted-flow"
    accepted_for_alerts = True

    async def _row_text_for_price_element(self, item: Locator, slot: WatchSlot) -> str:
        try:
            return str(
                await item.evaluate(
                    r"""(el, route) => {
                        function normalize(text) {
                            return (text || '')
                                .replace(/[–—‑−]/g, '-')
                                .replace(/\s+/g, ' ')
                                .trim()
                                .toUpperCase();
                        }
                        function semanticText(node) {
                            if (!(node instanceof Node)) return '';
                            const walker = document.createTreeWalker(node, NodeFilter.SHOW_TEXT);
                            const parts = [];
                            let current;
                            while ((current = walker.nextNode())) {
                                const value = (current.textContent || '').replace(/\s+/g, ' ').trim();
                                if (value) parts.push(value);
                                if (parts.length > 160) break;
                            }
                            return parts.join(' ').trim();
                        }

                        const origin = String(route.origin || '').toUpperCase();
                        const destination = String(route.destination || '').toUpperCase();
                        const forwardToken = `${origin}-${destination}`;
                        const reverseToken = `${destination}-${origin}`;
                        const hardBroad = /flight search|search results|all filters|sorted by|checking prices from multiple sources|searching nearby airports|checking online travel agencies|finding the cheapest booking options/i;
                        let node = el;

                        for (let depth = 0; depth < 18 && node; depth += 1, node = node.parentElement) {
                            const text = semanticText(node);
                            if (!text || text.length > 1800 || hardBroad.test(text)) continue;
                            const times = text.match(/\b\d{1,2}:\d{2}(?:\s?[AP]M)?\b/gi) || [];
                            if (times.length < 2 || times.length > 4) continue;
                            if (!/nonstop|stops?|직항|경유|\bhr\b|시간/i.test(text)) continue;

                            const normalized = normalize(text);
                            const forwardCount = normalized.split(forwardToken).length - 1;
                            const reverseCount = normalized.split(reverseToken).length - 1;
                            if (reverseCount > 0 || forwardCount > 1) continue;

                            // Google often renders "CJJ Cheongju ... TPE Taiwan ..."
                            // rather than the literal CJJ-TPE token. Missing route
                            // token is allowed on this fixed-route search surface.
                            // If one/both airport codes are shown, require both in
                            // forward order so a nearby/reverse row fails closed.
                            if (forwardCount === 0) {
                                const originIndex = normalized.indexOf(origin);
                                const destinationIndex = normalized.indexOf(destination);
                                const anyCode = originIndex >= 0 || destinationIndex >= 0;
                                if (anyCode && !(originIndex >= 0 && destinationIndex > originIndex)) continue;
                            }
                            return text;
                        }
                        return '';
                    }""",
                    {"origin": slot.origin.upper(), "destination": slot.destination.upper()},
                )
            )
        except Exception:
            return ""
