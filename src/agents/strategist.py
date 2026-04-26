"""Strategist Agent — Phase 2: QA Documentation (V2 Cluster).

Three specialized nodes replace the V1 monolith:
    1. generate_happy_paths  — LLM generates standard user journey test cases
    2. generate_edge_cases   — LLM generates boundary / negative / accessibility cases
    3. merge_strategies      — Python deduplicates and sets final test_cases list,
                               then generates multi-POV reports

The split gives Phase 2 a clear HITL surface: the human can inspect
test_cases after merge_strategies and either approve or ask for regeneration.
"""

from __future__ import annotations

import json
import logging

from langchain_core.prompts import ChatPromptTemplate
from langchain_openai import ChatOpenAI
from langsmith import traceable

from src.config import config
from src.models.state import QAState

logger = logging.getLogger(__name__)


# ── LLM factory ─────────────────────────────────────────────

def _get_llm() -> ChatOpenAI:
    return ChatOpenAI(model=config.LLM_MODEL, temperature=0)


# ── Prompts ─────────────────────────────────────────────────

_HAPPY_PATH_PROMPT = ChatPromptTemplate.from_messages(
    [
        (
            "system",
            "You are a Senior QA Strategist.  Generate **happy-path test cases only** "
            "(standard user journeys, positive flows, smoke tests).\n\n"
            "Output **strict JSON** with this schema:\n"
            "{{\n"
            '  "test_cases": [\n'
            "    {{\n"
            '      "id": "TC-HP-001",\n'
            '      "feature": "Login",\n'
            '      "scenario": "Valid login with correct credentials",\n'
            '      "steps": [\n'
            '        {{"step_number": 1, "action": "Navigate to /login", "expected_result": "Login page loads"}}\n'
            "      ],\n"
            '      "expected_result": "User is redirected to dashboard",\n'
            '      "severity": "critical",\n'
            '      "tags": ["smoke", "happy-path"]\n'
            "    }}\n"
            "  ]\n"
            "}}\n\n"
            "Severity values: critical | high | medium | low.\n"
            "Cover: smoke tests and primary user journeys only.",
        ),
        (
            "human",
            "## Product Knowledge Graph\n```json\n{knowledge_graph}\n```\n\n"
            "## Page Analysis\n{page_analysis}\n\n"
            "## PRD\n{prd}",
        ),
    ]
)

_EDGE_CASE_PROMPT = ChatPromptTemplate.from_messages(
    [
        (
            "system",
            "You are a Senior QA Strategist specialising in edge cases and negative testing.  "
            "Generate **boundary conditions, negative tests, error flows, and accessibility cases only** "
            "(do NOT include happy-path scenarios).\n\n"
            "Output **strict JSON** with this schema:\n"
            "{{\n"
            '  "test_cases": [\n'
            "    {{\n"
            '      "id": "TC-EC-001",\n'
            '      "feature": "Login",\n'
            '      "scenario": "Login fails with invalid password",\n'
            '      "steps": [\n'
            '        {{"step_number": 1, "action": "Navigate to /login", "expected_result": "Login page loads"}}\n'
            "      ],\n"
            '      "expected_result": "Error message is displayed",\n'
            '      "severity": "high",\n'
            '      "tags": ["negative", "edge-case"]\n'
            "    }}\n"
            "  ]\n"
            "}}\n\n"
            "Severity values: critical | high | medium | low.\n"
            "Cover: boundary values, invalid inputs, empty states, error messages, "
            "accessibility (aria-labels), and cross-browser edge cases.",
        ),
        (
            "human",
            "## Product Knowledge Graph\n```json\n{knowledge_graph}\n```\n\n"
            "## Page Analysis\n{page_analysis}\n\n"
            "## PRD\n{prd}",
        ),
    ]
)

_POV_REPORT_PROMPT = ChatPromptTemplate.from_messages(
    [
        (
            "system",
            "You are a QA Lead producing multi-audience reports.\n"
            "Generate three perspective reports in JSON:\n"
            "{{\n"
            '  "stakeholder": "Business-value perspective …",\n'
            '  "developer": "Technical-debt & implementation perspective …",\n'
            '  "user": "UX friction & usability perspective …"\n'
            "}}",
        ),
        (
            "human",
            "Knowledge Graph:\n{knowledge_graph}\n\nTest Cases:\n{test_cases}",
        ),
    ]
)


# ── Helper ───────────────────────────────────────────────────

def _parse_test_cases(raw: str, fallback_prefix: str) -> list[dict]:
    """Parse LLM JSON response into a list of test case dicts."""
    try:
        cleaned = raw.strip()
        if cleaned.startswith("```"):
            cleaned = cleaned.split("\n", 1)[1].rsplit("```", 1)[0]
        parsed = json.loads(cleaned)
        return parsed.get("test_cases", [])
    except (json.JSONDecodeError, IndexError):
        logger.warning("Could not parse %s test cases — wrapping raw text", fallback_prefix)
        return [{"id": f"{fallback_prefix}-RAW", "raw": raw}]


# ── Node functions ───────────────────────────────────────────


@traceable(name="generate_happy_paths", run_type="chain")
async def generate_happy_paths(state: QAState) -> dict:
    """Node 1 — Generate standard user journey (happy-path) test cases."""
    knowledge_graph = state.get("technical_overview", {})
    page_analysis = state.get("page_analysis", "")
    prd = state.get("project_description", "")

    kg_str = json.dumps(knowledge_graph, indent=2) if isinstance(knowledge_graph, dict) else str(knowledge_graph)

    logger.info("Strategist / generate_happy_paths: generating happy-path cases")
    result = await (_HAPPY_PATH_PROMPT | _get_llm()).ainvoke(
        {"knowledge_graph": kg_str, "page_analysis": page_analysis, "prd": prd}
    )

    cases = _parse_test_cases(result.content, "HP")  # type: ignore[arg-type]
    logger.info("Strategist / generate_happy_paths: %d cases", len(cases))
    return {"happy_path_cases": cases}


@traceable(name="generate_edge_cases", run_type="chain")
async def generate_edge_cases(state: QAState) -> dict:
    """Node 2 — Generate boundary / negative / edge-case test cases."""
    knowledge_graph = state.get("technical_overview", {})
    page_analysis = state.get("page_analysis", "")
    prd = state.get("project_description", "")

    kg_str = json.dumps(knowledge_graph, indent=2) if isinstance(knowledge_graph, dict) else str(knowledge_graph)

    logger.info("Strategist / generate_edge_cases: generating edge cases")
    result = await (_EDGE_CASE_PROMPT | _get_llm()).ainvoke(
        {"knowledge_graph": kg_str, "page_analysis": page_analysis, "prd": prd}
    )

    cases = _parse_test_cases(result.content, "EC")  # type: ignore[arg-type]
    logger.info("Strategist / generate_edge_cases: %d cases", len(cases))
    return {"edge_case_cases": cases}


@traceable(name="merge_strategies", run_type="chain")
async def merge_strategies(state: QAState) -> dict:
    """Node 3 — Merge happy-path + edge cases, deduplicate, generate POV reports."""
    happy = state.get("happy_path_cases") or []
    edge = state.get("edge_case_cases") or []

    # Combine and deduplicate by id
    seen_ids: set[str] = set()
    merged: list[dict] = []
    for tc in happy + edge:
        tc_id = tc.get("id", "")
        if tc_id not in seen_ids:
            seen_ids.add(tc_id)
            merged.append(tc)

    logger.info(
        "Strategist / merge_strategies: %d happy-path + %d edge = %d unique test cases",
        len(happy),
        len(edge),
        len(merged),
    )

    # Generate multi-POV reports
    knowledge_graph = state.get("technical_overview", {})
    kg_str = json.dumps(knowledge_graph, indent=2) if isinstance(knowledge_graph, dict) else str(knowledge_graph)

    pov_result = await (_POV_REPORT_PROMPT | _get_llm()).ainvoke(
        {"knowledge_graph": kg_str, "test_cases": json.dumps(merged, indent=2)}
    )

    pov_raw: str = pov_result.content  # type: ignore[union-attr]
    try:
        pov_cleaned = pov_raw.strip()
        if pov_cleaned.startswith("```"):
            pov_cleaned = pov_cleaned.split("\n", 1)[1].rsplit("```", 1)[0]
        pov_reports = json.loads(pov_cleaned)
    except (json.JSONDecodeError, IndexError):
        pov_reports = {"raw": pov_raw}

    updated_overview = {**(state.get("technical_overview") or {}), "pov_reports": pov_reports}

    return {
        "test_cases": merged,                 # plain list — overwrites (human can edit)
        "technical_overview": updated_overview,
    }
