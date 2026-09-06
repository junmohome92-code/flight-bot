(() => {
  if (window.__flightBotCaptureV4) return;

  const config = window.__flightBotInitConfig || {origin: 'CJJ', destination: 'TPE'};
  const PHASE_KEY = '__flightBotPointerPhaseV4';
  let phase = 'pre-cheapest';
  try {
    const saved = sessionStorage.getItem(PHASE_KEY);
    if (['pre-cheapest', 'departure', 'returning', 'done'].includes(saved)) phase = saved;
  } catch (_) {}

  const state = window.__flightBotCaptureV4 = {
    phase,
    phaseStartedAtMs: performance.now(),
    candidates: [],
    refs: {},
    advertisedPrice: null,
    advertisedChangedAtMs: performance.now(),
    cheapestRequestedAtMs: null,
    cheapestSelected: false,
    cheapestSelectedAtMs: null,
    cheapestText: '',
    cheapestLoading: true,
    returningMarker: false,
    returningMarkerAtMs: null,
    rejectedBroad: 0,
    rejectedSource: 0,
    seq: 0,
    startedAtMs: performance.now()
  };

  const krwRe = /₩\s*([0-9][0-9,]*)/g;
  const wonRe = /([0-9][0-9,]*)\s+(?:South Korean won|Korean won|KRW)/gi;
  const timeRe = /\b\d{1,2}:\d{2}(?:\s?[AP]M)?\b/gi;
  const flightShapeRe = /nonstop|stops?|직항|경유|\bhr\b|시간/i;
  const cheapestRe = /(?:Cheapest|최저가)/i;
  const loadingRe = /fetching results|checking prices|searching nearby airports|checking online travel agencies|검색 중|불러오는 중|가격 확인 중/i;
  const returningRe = /returning flights|귀국 항공편/i;
  const semanticSelector = '[role="button"], [role="link"], button, a, [tabindex="0"]';
  const broadMarkerRe = /flight search|search results|all filters|top departing flights|other departing flights|sorted by|checking prices from multiple sources|searching nearby airports|checking online travel agencies|finding the cheapest booking options/i;

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

  function priceFloor() {
    return state.phase === 'returning' ? 0 : 50000;
  }

  function parsePrices(text, minPrice = priceFloor()) {
    const found = [];
    krwRe.lastIndex = 0;
    wonRe.lastIndex = 0;
    let match;
    while ((match = krwRe.exec(text || '')) !== null) {
      const value = Number(match[1].replaceAll(',', ''));
      if (Number.isFinite(value) && value >= minPrice && value <= 1500000) found.push(value);
    }
    while ((match = wonRe.exec(text || '')) !== null) {
      const value = Number(match[1].replaceAll(',', ''));
      if (Number.isFinite(value) && value >= minPrice && value <= 1500000) found.push(value);
    }
    return [...new Set(found)].sort((a, b) => a - b);
  }

  function visible(el) {
    if (!(el instanceof Element) || !el.isConnected) return false;
    const style = getComputedStyle(el);
    if (style.display === 'none' || style.visibility === 'hidden' || style.opacity === '0') return false;
    const rect = el.getBoundingClientRect();
    return rect.width > 2 && rect.height > 2;
  }

  function directSource(el) {
    if (!(el instanceof Element) || !visible(el)) return null;
    const aria = el.getAttribute('aria-label') || '';
    const directText = Array.from(el.childNodes || [])
      .filter(node => node.nodeType === Node.TEXT_NODE)
      .map(node => node.textContent || '')
      .join(' ')
      .trim();
    const own = `${aria}\n${directText}`.trim();
    if (!own || own.length > 220) {
      state.rejectedSource += 1;
      return null;
    }
    const prices = parsePrices(own);
    if (!prices.length || prices.length > 2) {
      state.rejectedSource += 1;
      return null;
    }
    return {text: own, prices};
  }

  function countToken(text, token) {
    return normalize(text).split(token).length - 1;
  }

  function scanPageMarkers() {
    const body = (document.body?.innerText || semanticText(document.body) || '').slice(0, 18000);
    state.cheapestLoading = loadingRe.test(body);

    if (state.phase === 'returning' && !state.returningMarker && returningRe.test(body)) {
      state.returningMarker = true;
      state.returningMarkerAtMs = performance.now();
    }

    const controls = document.querySelectorAll('[role="tab"], button, [role="button"]');
    let sawSelectedCheapest = false;
    for (const control of controls) {
      const text = `${control.innerText || semanticText(control) || control.textContent || ''}\n${control.getAttribute('aria-label') || ''}`.trim();
      if (!text || text.length > 900 || !cheapestRe.test(text)) continue;
      const selected = control.getAttribute('aria-selected') === 'true' || control.getAttribute('aria-pressed') === 'true';
      if (!selected) continue;
      sawSelectedCheapest = true;
      if (!state.cheapestSelected) {
        state.cheapestSelected = true;
        state.cheapestSelectedAtMs = performance.now();
      }
      state.cheapestText = text.slice(0, 900);
      const values = parsePrices(text, 50000);
      if (!values.length) continue;
      const next = Math.min(...values);
      if (state.advertisedPrice === null || next < state.advertisedPrice) {
        state.advertisedPrice = next;
        state.advertisedChangedAtMs = performance.now();
      }
    }
    if (state.phase === 'departure' && !sawSelectedCheapest && state.cheapestSelected) {
      // Keep the confirmed transition even when Google replaces the selected
      // tab DOM node during loading.
    }
  }

  function compactFlightContext(source, price) {
    const origin = String(config.origin || 'CJJ').toUpperCase();
    const destination = String(config.destination || 'TPE').toUpperCase();
    const forwardToken = state.phase === 'returning' ? `${destination}-${origin}` : `${origin}-${destination}`;
    const reverseToken = state.phase === 'returning' ? `${origin}-${destination}` : `${destination}-${origin}`;
    let node = source;
    for (let depth = 0; depth < 18 && node; depth += 1, node = node.parentElement) {
      // Google frequently lays out flight fields as adjacent inline spans. Using
      // innerText alone can concatenate values (for example PM1:10), so build a
      // semantic row string by joining descendant Text nodes with spaces.
      const text = semanticText(node);
      if (!text) continue;
      if (text.length > 1800 || broadMarkerRe.test(text)) {
        state.rejectedBroad += 1;
        continue;
      }
      timeRe.lastIndex = 0;
      const times = text.match(timeRe) || [];
      if (times.length < 2 || times.length > 4) continue;
      if (!flightShapeRe.test(text)) continue;
      const rowPrices = parsePrices(text);
      if (!rowPrices.includes(price) || rowPrices.length > 3) continue;

      const forward = countToken(text, forwardToken);
      const reverse = countToken(text, reverseToken);
      if (reverse > 0) continue;
      if (state.phase !== 'returning' && forward !== 1) continue;
      if (state.phase === 'returning' && !(forward === 1 || forward === 0)) continue;

      return {
        row: node,
        rowText: text,
        timeCount: times.length,
        routeCount: forward,
        rowPriceCount: rowPrices.length
      };
    }
    return null;
  }

  function clickAnchor(source, row) {
    let node = source;
    while (node) {
      if (visible(node)) {
        if (node.matches?.(semanticSelector)) return {el: node, mode: 'semantic'};
        if (getComputedStyle(node).cursor === 'pointer') return {el: node, mode: 'cursor-pointer'};
      }
      if (node === row) break;
      node = node.parentElement;
    }
    return visible(row) ? {el: row, mode: 'row-coordinate'} : null;
  }

  function rectOf(el) {
    const rect = el.getBoundingClientRect();
    return {
      x: rect.left + rect.width / 2,
      y: rect.top + rect.height / 2,
      left: rect.left,
      top: rect.top,
      width: rect.width,
      height: rect.height
    };
  }

  function consider(el) {
    if (state.phase === 'done') return;
    const source = directSource(el);
    if (!source) return;
    const seenAtMs = Math.round(performance.now() * 10) / 10;

    for (const price of source.prices) {
      const context = compactFlightContext(el, price);
      if (!context) continue;
      const anchor = clickAnchor(el, context.row);
      if (!anchor) continue;
      const key = `${state.phase}|${price}|${normalize(context.rowText).slice(0, 900)}`;
      if (state.candidates.some(item => item.key === key)) continue;

      const id = `flight-bot-v4-${state.phase}-${++state.seq}`;
      try { anchor.el.setAttribute('data-flight-bot-pointer-anchor-id', id); } catch (_) {}
      state.refs[id] = {anchor: anchor.el, row: context.row};
      state.candidates.push({
        id,
        key,
        phase: state.phase,
        price,
        priceKind: /^\s*\+\s*₩/.test(source.text) ? 'adjustment' : 'displayed',
        rowText: context.rowText.slice(0, 2800),
        sourceText: source.text.slice(0, 350),
        seenAtMs,
        cheapestSelectedAtSeen: state.cheapestSelected,
        cheapestSelectedAtMs: state.cheapestSelectedAtMs,
        cheapestRequestedAtMs: state.cheapestRequestedAtMs,
        returningMarkerAtSeen: state.returningMarker,
        returningMarkerAtMs: state.returningMarkerAtMs,
        anchorMode: anchor.mode,
        anchorTag: anchor.el.tagName,
        anchorRole: anchor.el.getAttribute('role'),
        anchorRect: rectOf(anchor.el),
        sourceRect: rectOf(el),
        timeCount: context.timeCount,
        routeCount: context.routeCount,
        rowPriceCount: context.rowPriceCount,
        rowLength: context.rowText.length,
        urlSeen: location.href
      });
      if (state.candidates.length > 240) state.candidates.shift();
    }
  }

  function inspect(root) {
    if (!root || state.phase === 'done') return;
    if (root instanceof Element) consider(root);
    if (!root.querySelectorAll) return;
    let checked = 0;
    for (const el of root.querySelectorAll('*')) {
      if (++checked > 5000) break;
      const aria = el.getAttribute?.('aria-label') || '';
      let likely = /₩|South Korean won|Korean won|\bKRW\b/i.test(aria);
      if (!likely) {
        for (const child of el.childNodes || []) {
          if (child.nodeType === Node.TEXT_NODE && /₩|South Korean won|Korean won|\bKRW\b/i.test(child.textContent || '')) {
            likely = true;
            break;
          }
        }
      }
      if (likely) consider(el);
    }
  }

  const observer = new MutationObserver(mutations => {
    scanPageMarkers();
    for (const mutation of mutations) {
      if (mutation.type === 'characterData') {
        const parent = mutation.target?.parentElement;
        if (parent) consider(parent);
      } else if (mutation.target instanceof Element) {
        consider(mutation.target);
      }
      for (const node of mutation.addedNodes || []) inspect(node);
    }
  });

  observer.observe(document, {
    subtree: true,
    childList: true,
    characterData: true,
    attributes: true,
    attributeFilter: ['aria-label', 'aria-selected', 'aria-pressed']
  });

  document.addEventListener('DOMContentLoaded', () => {
    scanPageMarkers();
    inspect(document.documentElement);
  }, {once: true});

  let scans = 0;
  const scanTimer = setInterval(() => {
    scanPageMarkers();
    inspect(document.documentElement);
    scans += 1;
    if (scans >= 600 || state.phase === 'done') clearInterval(scanTimer);
  }, 40);
})();
