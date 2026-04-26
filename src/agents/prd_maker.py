"""PRD Maker Agent — Phase 0: Auto-generate PRD from reference sites.

Two nodes:
    1. research_references — LLM identifies website category from the target URL,
                             suggests 4 similar well-known reference sites, then
                             fetches their HTML in parallel.
    2. draft_prd           — LLM identifies common features across the 4 references
                             and synthesises a structured PRD for the target site type.

Works for any URL — the site category is detected dynamically so the generated PRD
is always tailored to the specific type of website being tested.
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
import ssl
import urllib.request
from urllib.error import URLError

from langchain_core.prompts import ChatPromptTemplate
from langchain_openai import ChatOpenAI
from langsmith import traceable

from src.config import config
from src.models.state import QAState

logger = logging.getLogger(__name__)


def _get_llm() -> ChatOpenAI:
    return ChatOpenAI(model=config.LLM_MODEL, temperature=0)


# ── Prompts ──────────────────────────────────────────────────

_SITE_TYPE_PROMPT = ChatPromptTemplate.from_messages(
    [
        (
            "system",
            "You are a web analyst. Given a URL, identify its website category and "
            "suggest exactly 4 well-known, publicly accessible reference sites of the SAME category.\n\n"
            "Output strict JSON:\n"
            "{{\n"
            '  "site_type": "portfolio|e-commerce|blog|news|saas|corporate|restaurant|education|landing-page|other",\n'
            '  "site_description": "one sentence describing what users come here to do",\n'
            '  "reference_urls": [\n'
            '    "https://reference1.com",\n'
            '    "https://reference2.com",\n'
            '    "https://reference3.com",\n'
            '    "https://reference4.com"\n'
            "  ]\n"
            "}}\n\n"
            "Rules:\n"
            "- reference_urls must have exactly 4 entries.\n"
            "- Choose widely-known sites so they are likely reachable (e.g. github.com, shopify.com).\n"
            "- Use homepage or category-level URLs — not deep internal pages.\n"
            "- Do NOT include the target URL itself.",
        ),
        ("human", "Target URL: {url}"),
    ]
)

_PRD_PROMPT = ChatPromptTemplate.from_messages(
    [
        (
            "system",
            "You are a Product Manager writing a Product Requirements Document (PRD).\n"
            "You have the stripped HTML of up to 4 reference websites of the same category "
            "as the target site. Some references may show '(fetch unavailable)' — for those, "
            "use your own knowledge of that site type instead.\n"
            "Identify features, sections, and patterns that appear on MOST sites of this "
            "category — those are the standard requirements.\n\n"
            "Write a concise PRD covering:\n"
            "- Core sections / pages (e.g. Hero, About, Projects, Contact)\n"
            "- Key interactive features (navigation, forms, modals, carousels)\n"
            "- Link and navigation requirements\n"
            "- Content requirements (headings, images, CTAs)\n"
            "- Accessibility requirements (aria-labels, keyboard navigation, alt text)\n"
            "- Responsive design expectations (mobile, tablet, desktop)\n"
            "- Performance / reliability expectations (no broken links, fast load)\n\n"
            "Format: bullet points grouped under short headings. Be specific and concise.",
        ),
        (
            "human",
            "## Website Category\n**{site_type}**: {site_description}\n\n"
            "{reference_blocks}",
        ),
    ]
)


# ── Helpers ──────────────────────────────────────────────────

_BROWSER_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.5",
    "Accept-Encoding": "identity",
}

# SSL context that tolerates self-signed certs on reference sites
_SSL_CTX = ssl.create_default_context()
_SSL_CTX.check_hostname = False
_SSL_CTX.verify_mode = ssl.CERT_NONE


async def _fetch_url(url: str) -> str:
    """Fetch a URL's HTML in a background thread.

    Uses a real browser User-Agent so major sites (GitHub, Amazon, Medium …)
    don't return 403/429. Strips scripts/styles to save tokens.
    Returns a fallback string on any error so downstream nodes still run.
    """
    def _get() -> str:
        req = urllib.request.Request(url, headers=_BROWSER_HEADERS)
        with urllib.request.urlopen(req, timeout=20, context=_SSL_CTX) as resp:
            html = resp.read().decode(errors="replace")
        html = re.sub(r"<script[^>]*>.*?</script>", " ", html, flags=re.DOTALL | re.IGNORECASE)
        html = re.sub(r"<style[^>]*>.*?</style>", " ", html, flags=re.DOTALL | re.IGNORECASE)
        html = re.sub(r"<!--.*?-->", " ", html, flags=re.DOTALL)
        html = re.sub(r"\s{3,}", " ", html)
        return html[:5000]

    try:
        return await asyncio.to_thread(_get)
    except Exception as exc:
        logger.warning("PRD Maker / _fetch_url: %s — %s", url, exc)
        return f"(fetch unavailable — LLM will use knowledge of {url})"


# ── Node functions ────────────────────────────────────────────


@traceable(name="research_references", run_type="chain")
async def research_references(state: QAState) -> dict:
    """Node 1 — Detect site type and fetch 4 reference sites in parallel."""
    url = state["url"]
    logger.info("PRD Maker / research_references: identifying category for %s", url)

    result = await (_SITE_TYPE_PROMPT | _get_llm()).ainvoke({"url": url})
    raw: str = result.content  # type: ignore[union-attr]

    try:
        cleaned = raw.strip()
        if cleaned.startswith("```"):
            cleaned = cleaned.split("\n", 1)[1].rsplit("```", 1)[0]
        parsed = json.loads(cleaned)
    except (json.JSONDecodeError, IndexError):
        logger.warning("PRD Maker / research_references: JSON parse failed, using fallback")
        parsed = {
            "site_type": "unknown",
            "site_description": "a website",
            "reference_urls": [],
        }

    reference_urls: list[str] = parsed.get("reference_urls", [])[:4]
    site_type: str = parsed.get("site_type", "unknown")
    site_description: str = parsed.get("site_description", "a website")

    logger.info(
        "PRD Maker / research_references: type=%s, fetching %d reference site(s)",
        site_type,
        len(reference_urls),
    )

    contents = await asyncio.gather(*[_fetch_url(u) for u in reference_urls])

    prd_references = [
        {"url": u, "content": c}
        for u, c in zip(reference_urls, contents)
    ]

    return {
        "prd_site_type": site_type,
        "prd_site_description": site_description,
        "prd_references": prd_references,
    }


@traceable(name="draft_prd", run_type="chain")
async def draft_prd(state: QAState) -> dict:
    """Node 2 — Synthesise PRD from common patterns across the 4 reference sites.

    If the user already provided a PRD (non-empty project_description), skip generation
    and return the existing PRD so Phase 0 gate still runs for review.
    """
    existing_prd = (state.get("project_description") or "").strip()
    if existing_prd:
        logger.info("PRD Maker / draft_prd: user-provided PRD detected (%d chars) — skipping generation", len(existing_prd))
        return {"project_description": existing_prd}

    site_type = state.get("prd_site_type") or "unknown"
    site_description = state.get("prd_site_description") or "a website"
    references: list[dict] = list(state.get("prd_references") or [])

    # Pad to 4 so the prompt template always has content
    while len(references) < 4:
        references.append({"url": "(unavailable)", "content": "(no content available)"})

    reference_blocks = "\n\n".join(
        f"### Reference {i + 1}: {r['url']}\n```html\n{r['content'][:4000]}\n```"
        for i, r in enumerate(references[:4])
    )

    logger.info(
        "PRD Maker / draft_prd: synthesising PRD (type=%s, %d references)",
        site_type,
        len(references[:4]),
    )

    result = await (_PRD_PROMPT | _get_llm()).ainvoke(
        {
            "site_type": site_type,
            "site_description": site_description,
            "reference_blocks": reference_blocks,
        }
    )

    prd: str = result.content  # type: ignore[union-attr]
    logger.info("PRD Maker / draft_prd: PRD generated (%d chars)", len(prd))
    return {"project_description": prd}
