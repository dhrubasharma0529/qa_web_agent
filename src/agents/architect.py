"""Architect Agent — Phase 1: Contextual Intelligence (V2 Cluster).

Three specialized nodes replace the V1 monolith:
    1. crawl_target   — browser navigation + raw HTML capture
    2. analyze_dom    — DOM chunking + LLM summarisation via DOMProcessor
    3. map_to_prd     — LLM compares DOM summary against PRD → knowledge graph

Usage: call `_build_architect_nodes(browser, dom_processor)` which returns
a dict of the three async node functions, ready to be registered in the graph.
"""

from __future__ import annotations

import json
import logging

from langchain_core.prompts import ChatPromptTemplate
from langchain_openai import ChatOpenAI
from langsmith import traceable

from src.browser.playwright_adapter import PlaywrightAdapter
from src.config import config
from src.dom.processor import DOMProcessor
from src.models.state import QAState

logger = logging.getLogger(__name__)

# ── LLM factory ─────────────────────────────────────────────

def _get_llm() -> ChatOpenAI:
    """Lazy LLM — avoids requiring OPENAI_API_KEY at import time."""
    logger.info("Architect _get_llm() → model=%s", config.LLM_MODEL)
    return ChatOpenAI(model=config.LLM_MODEL, temperature=0)


# ── Prompts ─────────────────────────────────────────────────

_ANALYSIS_PROMPT = ChatPromptTemplate.from_messages(
    [
        (
            "system",
            "You are a Senior QA Architect.  You receive a filtered DOM analysis "
            "of a live web application and the Product Requirements Document (PRD).  "
            "Your job is to produce a **Product Knowledge Graph** as JSON that maps "
            "every PRD requirement to its implementation status on the live page.\n\n"
            "Output schema (strict JSON):\n"
            "{{\n"
            '  "app_title": "string",\n'
            '  "tech_signals": ["React", "Tailwind", ...],\n'
            '  "implemented_features": [\n'
            '    {{"feature": "...", "evidence": "...", "selectors": ["..."]}}\n'
            "  ],\n"
            '  "missing_features": [\n'
            '    {{"feature": "...", "prd_reference": "..."}}\n'
            "  ],\n"
            '  "interactive_elements_summary": "...",\n'
            '  "risks": ["..."],\n'
            '  "recommendations": ["..."]\n'
            "}}",
        ),
        (
            "human",
            "## PRD\n{prd}\n\n"
            "## Live Page Analysis (URL: {url})\n{page_analysis}",
        ),
    ]
)


# ── Node factory ─────────────────────────────────────────────


def _build_architect_nodes(
    browser: PlaywrightAdapter,
    dom_processor: DOMProcessor,
) -> dict:
    """
    Return a dict of three LangGraph node functions closed over shared resources.

    Keys: "crawl_target", "analyze_dom", "map_to_prd"
    """

    @traceable(name="crawl_target", run_type="tool")
    async def crawl_target(state: QAState) -> dict:
        """Node 1 — Navigate to the target URL and capture raw HTML."""
        url: str = state["url"].strip()
        logger.info("Architect / crawl_target: crawling %s", url)
        snapshot = await browser.crawl_page(url)
        return {"raw_dom": snapshot.html}

    @traceable(name="analyze_dom", run_type="chain")
    async def analyze_dom(state: QAState) -> dict:
        """Node 2 — Run DOM through context-window manager to produce page_analysis."""
        logger.info("Architect / analyze_dom: processing DOM")
        llm = _get_llm()
        page_analysis = await dom_processor.process_page(browser, llm)
        return {"page_analysis": page_analysis}

    @traceable(name="map_to_prd", run_type="chain")
    async def map_to_prd(state: QAState) -> dict:
        """Node 3 — LLM compares DOM summary against PRD, outputs knowledge graph."""
        url: str = state["url"]
        prd: str = state.get("project_description", "")
        page_analysis: str = state.get("page_analysis", "")

        logger.info("Architect / map_to_prd: generating knowledge graph for %s", url)
        llm = _get_llm()
        chain = _ANALYSIS_PROMPT | llm
        result = await chain.ainvoke(
            {"prd": prd, "url": url, "page_analysis": page_analysis}
        )

        raw_text: str = result.content  # type: ignore[union-attr]
        try:
            cleaned = raw_text.strip()
            if cleaned.startswith("```"):
                cleaned = cleaned.split("\n", 1)[1].rsplit("```", 1)[0]
            knowledge_graph = json.loads(cleaned)
        except (json.JSONDecodeError, IndexError):
            logger.warning("Could not parse knowledge graph JSON — returning raw text")
            knowledge_graph = {"raw_analysis": raw_text}

        logger.info("Architect / map_to_prd: knowledge graph complete for %s", url)
        return {"technical_overview": knowledge_graph}

    return {
        "crawl_target": crawl_target,
        "analyze_dom": analyze_dom,
        "map_to_prd": map_to_prd,
    }
