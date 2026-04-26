"""Playwright browser automation — Chromium via async Playwright API.

On Windows, Playwright requires ProactorEventLoop to spawn the browser subprocess.
When the caller runs in a SelectorEventLoop (e.g. langgraph dev), a background
daemon thread with a ProactorEventLoop is used instead.

If Playwright fails for any reason (missing binary, wrong event loop, sandbox
restriction), the adapter automatically falls back to httpx for HTML fetching.
The fallback produces a PageSnapshot with HTML only (no JS execution, no
screenshot) — sufficient for DOM analysis and test generation.
"""

from __future__ import annotations

import asyncio
import logging
import sys
import threading
from dataclasses import dataclass, field
from typing import Any, Optional

import httpx
from bs4 import BeautifulSoup
from playwright.async_api import Browser, Page, Playwright, async_playwright

from src.config import config

logger = logging.getLogger(__name__)


@dataclass
class InteractiveElement:
    index: int
    tag: str
    text: str
    role: Optional[str] = None
    href: Optional[str] = None
    element_type: Optional[str] = None
    element_id: Optional[str] = None
    name: Optional[str] = None
    aria_label: Optional[str] = None
    data_cy: Optional[str] = None
    data_testid: Optional[str] = None
    placeholder: Optional[str] = None
    selector: Optional[str] = None
    bounding_box: Optional[dict] = None


@dataclass
class PageSnapshot:
    url: str
    title: str
    html: str
    elements: list[InteractiveElement] = field(default_factory=list)
    accessibility_tree: dict | str = field(default_factory=dict)
    screenshot: Optional[bytes] = None
    meta: dict = field(default_factory=dict)

# JavaScript snippet that extracts interactive / meaningful elements.
# Returns a flat JSON array — keeps only visible elements and strips noise.
_EXTRACT_ELEMENTS_JS = """
() => {
    const SELECTORS = [
        'button', 'a[href]', 'input', 'select', 'textarea', 'form',
        '[role]', '[data-testid]', '[data-cy]', '[aria-label]',
        'h1', 'h2', 'h3', 'h4', 'h5', 'h6', 'label',
        'nav', 'main', 'header', 'footer',
        '[class*="modal"]', '[class*="dialog"]', '[class*="dropdown"]'
    ];
    const seen = new Set();
    const results = [];
    let idx = 0;

    for (const el of document.querySelectorAll(SELECTORS.join(','))) {
        if (seen.has(el) || el.offsetParent === null) continue;  // skip dupes & hidden
        seen.add(el);

        const tag = el.tagName.toLowerCase();
        const text = (el.textContent || '').trim().slice(0, 120);
        const rect = el.getBoundingClientRect();

        results.push({
            index: idx++,
            tag,
            text,
            role:        el.getAttribute('role')         || null,
            href:        el.getAttribute('href')         || null,
            element_type: el.getAttribute('type')        || null,
            element_id:  el.id                           || null,
            name:        el.getAttribute('name')         || null,
            aria_label:  el.getAttribute('aria-label')   || null,
            data_cy:     el.getAttribute('data-cy')      || null,
            data_testid: el.getAttribute('data-testid')  || null,
            placeholder: el.getAttribute('placeholder')  || null,
            selector:    _bestSelector(el),
            bounding_box: {
                x: Math.round(rect.x),
                y: Math.round(rect.y),
                width:  Math.round(rect.width),
                height: Math.round(rect.height),
            },
        });
    }
    return results;

    function _bestSelector(el) {
        if (el.getAttribute('data-cy'))      return `[data-cy="${el.getAttribute('data-cy')}"]`;
        if (el.getAttribute('data-testid'))  return `[data-testid="${el.getAttribute('data-testid')}"]`;
        if (el.id)                           return `#${el.id}`;
        if (el.getAttribute('aria-label'))   return `[aria-label="${el.getAttribute('aria-label')}"]`;
        if (el.getAttribute('role'))         return `[role="${el.getAttribute('role')}"]`;
        if (el.name)                         return `${el.tagName.toLowerCase()}[name="${el.name}"]`;
        return null;
    }
}
"""

# JS that builds a lightweight filtered HTML string (interactive elements only).
_FILTERED_HTML_JS = """
() => {
    const SELECTORS = [
        'button', 'a[href]', 'input', 'select', 'textarea', 'form',
        '[role]', '[data-testid]', '[data-cy]', '[aria-label]',
        'h1', 'h2', 'h3', 'h4', 'h5', 'h6', 'label',
        'nav', 'main', 'header', 'footer'
    ];
    const seen = new Set();
    const lines = [];
    for (const el of document.querySelectorAll(SELECTORS.join(','))) {
        if (seen.has(el) || el.offsetParent === null) continue;
        seen.add(el);
        const tag = el.tagName.toLowerCase();
        const attrs = {};
        for (const a of ['id','name','type','href','role','aria-label',
                          'data-testid','data-cy','placeholder','value']) {
            const v = el.getAttribute(a);
            if (v) attrs[a] = v;
        }
        const text = (el.textContent || '').trim().slice(0, 100);
        const attrStr = Object.entries(attrs).map(([k,v]) => `${k}="${v}"`).join(' ');
        lines.push(`<${tag} ${attrStr}>${text}</${tag}>`);
    }
    return lines.join('\\n');
}
"""


class PlaywrightAdapter:
    """Concrete BrowserAdapter backed by Playwright (Chromium).

    When ``config.TARGET_ENV == "local"``:
    - HTTPS certificate errors are ignored (useful for self-signed certs on localhost).
    - Navigation timeout is extended to 60 s (vs 30 s for cloud).

    Windows / SelectorEventLoop compatibility:
    If the calling event loop is a SelectorEventLoop (which cannot spawn subprocesses),
    a background daemon thread with a ProactorEventLoop is created automatically and
    all Playwright operations are routed there.  Results are serialisable values
    (strings, bytes, dicts) so they cross the loop boundary safely.
    """

    def __init__(self, headless: bool = True, viewport_width: int = 1280, viewport_height: int = 720):
        self._headless = headless
        self._viewport = {"width": viewport_width, "height": viewport_height}
        self._pw: Optional[Playwright] = None
        self._browser: Optional[Browser] = None
        self._page: Optional[Page] = None
        # Background ProactorEventLoop thread — created lazily on Windows when needed.
        self._bg_loop: Optional[asyncio.AbstractEventLoop] = None

    # ── Loop-dispatch helpers ───────────────────────────────

    def _needs_bg_loop(self) -> bool:
        """True when running on Windows inside a non-Proactor event loop."""
        if sys.platform != "win32":
            return False
        try:
            return not isinstance(asyncio.get_running_loop(), asyncio.ProactorEventLoop)
        except RuntimeError:
            return False

    def _get_bg_loop(self) -> asyncio.AbstractEventLoop:
        """Return the background ProactorEventLoop, creating it (once) if needed."""
        if self._bg_loop is not None and self._bg_loop.is_running():
            return self._bg_loop

        ready = threading.Event()
        holder: dict = {}

        def _thread_main() -> None:
            lp = asyncio.ProactorEventLoop()
            asyncio.set_event_loop(lp)
            holder["lp"] = lp
            ready.set()
            lp.run_forever()

        threading.Thread(target=_thread_main, daemon=True, name="playwright-proactor").start()
        ready.wait(timeout=10)
        self._bg_loop = holder["lp"]
        return self._bg_loop

    async def _run(self, coro) -> Any:
        """Run *coro* in the ProactorEventLoop (bg thread on Windows, directly otherwise)."""
        if self._needs_bg_loop():
            return await asyncio.wrap_future(
                asyncio.run_coroutine_threadsafe(coro, self._get_bg_loop())
            )
        return await coro

    # ── Lifecycle ───────────────────────────────────────────

    async def start(self) -> None:
        await self._run(self._start_impl())

    async def _start_impl(self) -> None:
        self._pw = await async_playwright().start()
        self._browser = await self._pw.chromium.launch(headless=self._headless)

        if config.TARGET_ENV == "local":
            context = await self._browser.new_context(
                viewport=self._viewport,
                ignore_https_errors=True,
            )
        else:
            context = await self._browser.new_context(viewport=self._viewport)

        self._page = await context.new_page()

    async def stop(self) -> None:
        await self._run(self._stop_impl())

    async def _stop_impl(self) -> None:
        if self._browser:
            await self._browser.close()
        if self._pw:
            await self._pw.stop()
        self._browser = None
        self._pw = None
        self._page = None

    async def _ensure_started(self) -> None:
        """Lazily start the browser if not already running."""
        if self._page is None:
            await self._run(self._start_impl())

    @property
    def page(self) -> Page:
        if self._page is None:
            raise RuntimeError("PlaywrightAdapter not started — call start() or _ensure_started() first")
        return self._page

    # ── Navigation & Extraction ─────────────────────────────

    async def crawl_page(self, url: str) -> PageSnapshot:
        try:
            return await self._run(self._crawl_page_impl(url))
        except Exception as exc:
            logger.warning(
                "Playwright crawl failed (%s: %s) — falling back to httpx",
                type(exc).__name__, exc,
            )
            return await self._crawl_page_httpx(url)

    async def _crawl_page_httpx(self, url: str) -> PageSnapshot:
        """Fallback crawler using httpx — works in any event loop / environment."""
        url = url.strip()
        async with httpx.AsyncClient(
            timeout=30.0,
            follow_redirects=True,
            headers={"User-Agent": "Mozilla/5.0 (compatible; QA-Agent/1.0)"},
        ) as client:
            resp = await client.get(url)

        soup = BeautifulSoup(resp.text, "html.parser")
        for tag in soup(["script", "style", "svg", "noscript"]):
            tag.decompose()
        html = soup.prettify()[:50_000]

        logger.info("httpx fallback: fetched %d chars of HTML from %s", len(html), url)
        return PageSnapshot(
            url=str(resp.url),
            title=soup.title.string.strip() if soup.title else "",
            html=html,
            elements=[],
            accessibility_tree={},
            screenshot=None,
            meta={"fallback": "httpx", "status_code": resp.status_code},
        )

    async def _crawl_page_impl(self, url: str) -> PageSnapshot:
        url = url.strip()
        if self._page is None:
            await self._start_impl()

        nav_timeout = 60_000 if config.TARGET_ENV == "local" else 30_000
        networkidle_timeout = 30_000 if config.TARGET_ENV == "local" else 15_000

        await self._page.goto(url, wait_until="domcontentloaded", timeout=nav_timeout)
        await self._page.wait_for_load_state("networkidle", timeout=networkidle_timeout)

        title = await self._page.title()
        html = await self._page.evaluate(_FILTERED_HTML_JS.strip())
        raw_elements: list[dict] = await self._page.evaluate(_EXTRACT_ELEMENTS_JS.strip())
        elements = [InteractiveElement(**el) for el in raw_elements]

        try:
            ax_tree = await self._page.accessibility.snapshot() or {}  # type: ignore[attr-defined]
        except Exception:
            ax_tree = {}

        screenshot = await self._page.screenshot(full_page=True, type="png")

        return PageSnapshot(
            url=self._page.url,
            title=title,
            html=html,
            elements=elements,
            accessibility_tree=ax_tree,
            screenshot=screenshot,
            meta={"viewport": self._viewport, "target_env": config.TARGET_ENV},
        )

    async def get_interactive_elements(self) -> list[InteractiveElement]:
        raw: list[dict] = await self.evaluate_js(_EXTRACT_ELEMENTS_JS.strip())
        return [InteractiveElement(**el) for el in raw]

    async def get_accessibility_tree(self) -> dict | str:
        try:
            snapshot = await self.page.accessibility.snapshot()  # type: ignore[attr-defined]
            return snapshot or {}
        except Exception:
            return {}

    async def take_screenshot(self, full_page: bool = True) -> bytes:
        return await self.page.screenshot(full_page=full_page, type="png")

    # ── Interactions ────────────────────────────────────────

    async def click(self, selector: str) -> None:
        await self.page.locator(selector).click(timeout=10_000)

    async def fill(self, selector: str, value: str) -> None:
        await self.page.locator(selector).fill(value, timeout=10_000)

    # ── Low-level ───────────────────────────────────────────

    async def evaluate_js(self, expression: str) -> Any:
        try:
            return await self._run(self._evaluate_js_impl(expression))
        except Exception as exc:
            logger.warning(
                "Playwright evaluate_js failed (%s: %s) — returning empty string",
                type(exc).__name__, exc,
            )
            return ""

    async def _evaluate_js_impl(self, expression: str) -> Any:
        if self._page is None:
            await self._start_impl()
        return await self._page.evaluate(expression)

    async def get_page_html(self) -> str:
        return await self._run(self._get_page_html_impl())

    async def _get_page_html_impl(self) -> str:
        return await self._page.content()
