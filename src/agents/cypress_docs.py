"""Cypress Docs Subgraph — 3-node pipeline.

Fetches live Cypress API documentation, detects any changes or new behaviors
against a known baseline, and produces a `cypress_api_context` dict that is
injected into the SDET and Executor prompts so test generation always reflects
the current Cypress API.

Nodes (run in sequence inside the cypress_docs subgraph):
    1. fetch_cypress_docs   — async HTTP fetch of key API pages via httpx
    2. detect_api_changes   — LLM compares fetched content against known baseline
    3. build_cypress_context — synthesize into a structured context dict
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
from datetime import datetime, date, timezone
from pathlib import Path
import httpx
from bs4 import BeautifulSoup
from langchain_core.prompts import ChatPromptTemplate
from langchain_openai import ChatOpenAI
from langsmith import traceable

from src.config import config
from src.models.state import CypressDocsState

logger = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).resolve().parents[2]


# ── 24-hour file-backed cache ────────────────────────────────

class _DocsCache:
    """Persists the Cypress API context to disk with a 24-hour TTL.

    The cache file lives at PROJECT_ROOT/cypress_docs_cache.json.
    All pipeline runs read from the cache; the background refresh loop
    is the only writer (plus the first cold-start fetch).
    """

    PATH = PROJECT_ROOT / "cypress_docs_cache.json"
    TTL_SECONDS = 24 * 3600

    def _load_raw(self) -> dict:
        try:
            return json.loads(self.PATH.read_text(encoding="utf-8"))
        except Exception:
            return {}

    def is_fresh(self) -> bool:
        """True if the cache exists and was written within the last 24 hours."""
        raw = self._load_raw()
        if not raw:
            return False
        try:
            fetched_at = datetime.fromisoformat(raw["fetched_at"])
            # Make timezone-aware for comparison
            if fetched_at.tzinfo is None:
                fetched_at = fetched_at.replace(tzinfo=timezone.utc)
            age = (datetime.now(tz=timezone.utc) - fetched_at).total_seconds()
            return age < self.TTL_SECONDS
        except Exception:
            return False

    def load(self) -> dict:
        """Return the cached context dict, or {} if missing/corrupt."""
        return self._load_raw().get("context", {})

    def save(self, context: dict) -> None:
        """Persist context alongside an ISO-format UTC timestamp."""
        payload = {
            "fetched_at": datetime.now(tz=timezone.utc).isoformat(),
            "context": context,
        }
        self.PATH.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        logger.info("cypress_docs / cache: saved to %s", self.PATH)

    def age_hours(self) -> float | None:
        """Hours since last fetch, or None if no cache exists."""
        raw = self._load_raw()
        if not raw:
            return None
        try:
            fetched_at = datetime.fromisoformat(raw["fetched_at"])
            if fetched_at.tzinfo is None:
                fetched_at = fetched_at.replace(tzinfo=timezone.utc)
            return (datetime.now(tz=timezone.utc) - fetched_at).total_seconds() / 3600
        except Exception:
            return None

    def status(self) -> dict:
        """Summary dict for the /docs/status endpoint."""
        raw = self._load_raw()
        ctx = raw.get("context", {})
        return {
            "cache_exists": bool(raw),
            "is_fresh": self.is_fresh(),
            "fetched_at": raw.get("fetched_at"),
            "age_hours": self.age_hours(),
            "ttl_hours": self.TTL_SECONDS / 3600,
            "pages_fetched": ctx.get("pages_fetched", []),
            "fetch_count": ctx.get("fetch_count", 0),
            "has_updates": ctx.get("has_updates", False),
            "changes_count": len(ctx.get("changes_detected", [])),
        }


# Module-level singleton — shared by the subgraph wrapper and server refresh task.
docs_cache = _DocsCache()


# ── Cypress API pages to fetch ───────────────────────────────

_CYPRESS_DOCS_URLS: dict[str, str] = {
    "click":     "https://docs.cypress.io/api/commands/click",
    "visit":     "https://docs.cypress.io/api/commands/visit",
    "get":       "https://docs.cypress.io/api/commands/get",
    "focus":     "https://docs.cypress.io/api/commands/focus",
    "type":      "https://docs.cypress.io/api/commands/type",
    "should":    "https://docs.cypress.io/api/commands/should",
    "url":       "https://docs.cypress.io/api/commands/url",
    "request":   "https://docs.cypress.io/api/commands/request",
    "origin":    "https://docs.cypress.io/api/commands/origin",
    "intercept": "https://docs.cypress.io/api/commands/intercept",
    "realpress": "https://docs.cypress.io/api/commands/realPress",
}

# Concise description of what our test-generation rules already know.
# The LLM compares fetched docs against this to find NEW or CHANGED behaviors.
_KNOWN_BASELINE = """\
- cy.click() fails if subject contains >1 element — requires .first() or { multiple: true }
- cy.visit() fails on SPA hash routes like /about, /contact — use cy.visit('/') instead
- .tab() does not exist in core Cypress — use .focus().should('be.focused') per element
- .or() does not exist — use combined CSS selectors or .and() for chaining assertions
- cy.origin() wraps commands targeting a different domain (introduced in Cypress v12)
- cy.intercept() replaces the legacy cy.route() (introduced in Cypress v6/7)
- cy.request() supports { failOnStatusCode: false } to avoid failing on 4xx/5xx
- Single-element commands: click, type, check, uncheck, select, focus, blur, clear
- Assertions retry automatically up to defaultCommandTimeout (default 4 s)
- cy.get(selector, { timeout: N }) increases per-query retry timeout
- cy.scrollIntoView() makes off-screen elements interactable
- { force: true } bypasses actionability checks (last resort)
- { waitForAnimations: false } skips animation detection
- cy.realPress('Tab') simulates keyboard via cypress-real-events plugin (not built-in)
- cy.frameLoaded() / cy.iframe() available via cypress-iframe plugin (not built-in)
- SPA detection: if page hrefs contain #section anchors, cy.visit('/path') will 404
"""


# ── Helpers ──────────────────────────────────────────────────

def _extract_text(html: str, max_chars: int = 3000) -> str:
    """Strip HTML noise and return clean readable text, capped at max_chars."""
    soup = BeautifulSoup(html, "html.parser")
    for tag in soup(["script", "style", "nav", "footer", "head", "aside"]):
        tag.decompose()
    text = soup.get_text(separator=" ", strip=True)
    text = re.sub(r"\s+", " ", text)
    return text[:max_chars]


def _get_llm() -> ChatOpenAI:
    return ChatOpenAI(model=config.LLM_MODEL, temperature=0)


# ── Prompts ──────────────────────────────────────────────────

_DETECT_CHANGES_PROMPT = ChatPromptTemplate.from_messages(
    [
        (
            "system",
            "You are a Cypress.io documentation analyst.\n\n"
            "You will receive freshly fetched content from docs.cypress.io and a "
            "summary of what is already known. Your job is to identify:\n"
            "1. NEW options, behaviors, or features not covered by the known list.\n"
            "2. DEPRECATED or REMOVED commands/options (marked as such in the docs).\n"
            "3. CHANGED signatures or default values.\n"
            "4. Important cautions or best-practice notes that test writers should know.\n\n"
            "Be conservative — only report genuine differences from the known list.\n"
            "If nothing is new or changed, return an empty changes array and empty string.\n\n"
            "Output strict JSON only:\n"
            "{{\n"
            '  "changes": [\n'
            '    {{"command": "...", "change_type": "new|deprecated|changed|caution", "detail": "..."}}\n'
            "  ],\n"
            '  "rules_addendum": "Concise extra rules for test writers. Empty string if nothing new."\n'
            "}}",
        ),
        (
            "human",
            "## Known baseline\n```\n{known_rules}\n```\n\n"
            "## Freshly fetched Cypress API docs\n```\n{docs_content}\n```",
        ),
    ]
)


# ── Node 1: fetch_cypress_docs ───────────────────────────────

@traceable(name="fetch_cypress_docs", run_type="tool")
async def fetch_cypress_docs(state: CypressDocsState) -> dict:
    """Fetch key Cypress API docs pages concurrently using httpx."""
    docs_raw: dict[str, str] = {}

    async def _fetch_one(
        client: httpx.AsyncClient, name: str, url: str
    ) -> tuple[str, str]:
        try:
            resp = await client.get(url)
            resp.raise_for_status()
            return name, _extract_text(resp.text)
        except Exception as exc:
            logger.warning("cypress_docs / fetch: %s failed — %s", name, exc)
            return name, ""

    try:
        async with httpx.AsyncClient(
            timeout=15.0,
            follow_redirects=True,
            headers={"User-Agent": "Mozilla/5.0 (compatible; QA-Agent/1.0)"},
        ) as client:
            results = await asyncio.gather(
                *[_fetch_one(client, name, url) for name, url in _CYPRESS_DOCS_URLS.items()]
            )
        docs_raw = {name: text for name, text in results if text}
    except Exception as exc:
        logger.warning("cypress_docs / fetch_cypress_docs: network error — %s", exc)

    logger.info(
        "cypress_docs / fetch_cypress_docs: fetched %d/%d pages",
        len(docs_raw), len(_CYPRESS_DOCS_URLS),
    )
    return {"docs_raw": docs_raw}


# ── Node 2: detect_api_changes ───────────────────────────────

@traceable(name="detect_api_changes", run_type="chain")
async def detect_api_changes(state: CypressDocsState) -> dict:
    """LLM compares fetched docs against the known baseline to surface changes."""
    docs_raw = state.get("docs_raw") or {}

    if not docs_raw:
        logger.info("cypress_docs / detect_api_changes: no docs fetched — skipping")
        return {"api_changes": []}

    docs_block = "\n\n".join(
        f"### {name}\n{content}"
        for name, content in docs_raw.items()
    )

    try:
        result = await (_DETECT_CHANGES_PROMPT | _get_llm()).ainvoke(
            {
                "known_rules": _KNOWN_BASELINE,
                "docs_content": docs_block[:8000],
            }
        )
        raw: str = result.content  # type: ignore[union-attr]
        cleaned = raw.strip()
        if cleaned.startswith("```"):
            cleaned = cleaned.split("\n", 1)[1].rsplit("```", 1)[0]
        parsed = json.loads(cleaned)
        changes = parsed.get("changes", [])
        rules_addendum = parsed.get("rules_addendum", "")
    except Exception as exc:
        logger.warning("cypress_docs / detect_api_changes: LLM error — %s", exc)
        changes = []
        rules_addendum = ""

    logger.info(
        "cypress_docs / detect_api_changes: %d change(s) detected", len(changes)
    )
    return {"api_changes": changes, "rules_addendum": rules_addendum}


# ── Node 3: build_cypress_context ────────────────────────────

@traceable(name="build_cypress_context", run_type="chain")
async def build_cypress_context(state: CypressDocsState) -> dict:
    """Synthesise docs + changes into a structured context dict for downstream nodes."""
    docs_raw = state.get("docs_raw") or {}
    api_changes = state.get("api_changes") or []
    rules_addendum: str = state.get("rules_addendum", "")  # type: ignore[assignment]

    context: dict = {
        "fetched_at": str(date.today()),
        "pages_fetched": sorted(docs_raw.keys()),
        "fetch_count": len(docs_raw),
        "changes_detected": api_changes,
        "rules_addendum": rules_addendum,
        "has_updates": bool(api_changes or rules_addendum),
    }

    logger.info(
        "cypress_docs / build_cypress_context: context built — %d change(s), addendum=%s",
        len(api_changes),
        bool(rules_addendum),
    )
    return {"cypress_api_context": context}


# ── Subgraph factory ─────────────────────────────────────────

def _build_docs_subgraph():
    """Build (but do not compile) a fresh StateGraph for the cypress docs pipeline.

    Returns an uncompiled StateGraph so callers can compile it themselves.
    Used by both workflow.py (module-level compile) and refresh_docs_cache()
    (fresh compile per call) to avoid a circular import between the two modules.
    """
    from langgraph.graph import END, START, StateGraph  # local import — avoids top-level cycle

    sg = StateGraph(CypressDocsState)
    sg.add_node("fetch_cypress_docs", fetch_cypress_docs)
    sg.add_node("detect_api_changes", detect_api_changes)
    sg.add_node("build_cypress_context", build_cypress_context)
    sg.add_edge(START, "fetch_cypress_docs")
    sg.add_edge("fetch_cypress_docs", "detect_api_changes")
    sg.add_edge("detect_api_changes", "build_cypress_context")
    sg.add_edge("build_cypress_context", END)
    return sg


# ── Public refresh entry-point ────────────────────────────────

async def refresh_docs_cache() -> dict:
    """Run the full fetch → detect → build pipeline and persist result to cache.

    Called by:
      - The server's daily background loop (every 24 h)
      - The POST /docs/refresh endpoint (manual trigger)
    Returns the fresh cypress_api_context dict.
    """
    logger.info("cypress_docs / refresh_docs_cache: starting full docs refresh")
    try:
        compiled = _build_docs_subgraph().compile()
        result: CypressDocsState = await compiled.ainvoke({})
        context = result.get("cypress_api_context") or {}
        docs_cache.save(context)
        logger.info(
            "cypress_docs / refresh_docs_cache: done — %d change(s) detected",
            len(context.get("changes_detected", [])),
        )
        return context
    except Exception as exc:
        logger.warning("cypress_docs / refresh_docs_cache: failed — %s", exc)
        return {}
