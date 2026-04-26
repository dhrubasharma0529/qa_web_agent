"""LangGraph V2 workflow — sub-graph clusters with HITL gates.

Graph topology (V2)
-------------------
::

    Phase 0 — PRD Maker Cluster
    START → research_references → draft_prd
      → phase_0_gate [INTERRUPT_BEFORE]  ← mandatory, always pauses for PRD review
                      → approved: crawl_target (Phase 1)
                      → rejected: research_references (redo PRD)

    Phase 1 — Architect Cluster
    crawl_target → analyze_dom → map_to_prd
      → [route_phase_1] → auto: cypress_docs_check  |  manual: phase_1_gate
                          phase_1_gate [INTERRUPT_BEFORE]
                          → approved: cypress_docs_check  |  rejected: crawl_target

    Cypress Docs Check (between Phase 1 and Phase 2)
    cypress_docs_check — fetches live docs.cypress.io API pages, detects
      changes vs known baseline, builds cypress_api_context for SDET/Executor.
      Runs once per pipeline run; fails gracefully (empty context on network error).
      cypress_docs_check → generate_happy_paths

    Phase 2 — Strategist Cluster
    generate_happy_paths → generate_edge_cases → merge_strategies
      → [route_phase_2] → auto: Phase 3  |  manual: phase_2_gate
                          phase_2_gate [INTERRUPT_BEFORE]
                          → approved: Phase 3  |  rejected: generate_happy_paths

    Phase 3 — SDET Cluster
    generate_page_objects → generate_specs → syntax_linter
      → [route_linter] → lint_retry: generate_specs
                          auto_pass: pre_flight_check
                          manual_pass: phase_3_gate
                          phase_3_gate [INTERRUPT_BEFORE]
                          → approved: pre_flight_check  |  rejected: generate_page_objects

    Phase 4 — Executor Cluster
    pre_flight_check → run_cypress → classify_errors
      → [route_executor] → needs_healing: heal_tests → run_cypress (loop)
                           auto_done: Phase 5
                           manual_done: phase_4_gate
                           phase_4_gate [INTERRUPT_BEFORE]
                           → approved: Phase 5  |  rejected: pre_flight_check

    Phase 5 — Reporter Cluster
    aggregate_metrics → draft_bug_tickets → assemble_markdown → END

HITL interaction protocol
--------------------------
When run_mode="manual", the graph pauses BEFORE each phase gate.
The client:
  1. GET  /runs/{thread_id}/state         → inspects phase output
  2. POST /runs/{thread_id}/resume        → sets approval + optional edits
     body: { phase: N, approved: bool, feedback: str, edited_state_payload: {} }
  3. Graph resumes, gate runs (noop), conditional edge routes onward.
"""

from __future__ import annotations

import logging

from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, START, StateGraph
from langgraph.types import interrupt

from src.agents.executor import (
    classify_errors,
    heal_tests,
    pre_flight_check,
    run_cypress,
)
from src.agents.prd_maker import draft_prd, research_references
from src.agents.reporter import aggregate_metrics, assemble_markdown, draft_bug_tickets
from src.agents.sdet import generate_page_objects, generate_specs, syntax_linter
from src.agents.strategist import (
    generate_edge_cases,
    generate_happy_paths,
    merge_strategies,
)
from src.agents.cypress_docs import (
    fetch_cypress_docs,
    detect_api_changes,
    build_cypress_context,
    docs_cache,
)
from src.browser.playwright_adapter import PlaywrightAdapter
from src.config import config
from src.dom.processor import DOMProcessor
from src.graph.checkpointer import create_checkpointer
from src.models.state import CypressDocsState, QAState

logger = logging.getLogger(__name__)


# ── Cypress Docs Subgraph ────────────────────────────────────
#
# Follows LangGraph Pattern 1 (different state schemas):
#
#   Parent state  : QAState           (src.models.state)
#   Subgraph state: CypressDocsState  (src.models.state)
#
#   1. CypressDocsState  →  StateGraph(CypressDocsState)  →  compiled subgraph
#   2. cypress_docs_check(state: QAState):
#        subgraph_output = await cypress_docs_subgraph.ainvoke({})
#        return {"cypress_api_context": subgraph_output["cypress_api_context"]}
#
# Topology:
#   START → fetch_cypress_docs → detect_api_changes → build_cypress_context → END

_cypress_docs_sg = StateGraph(CypressDocsState)
_cypress_docs_sg.add_node("fetch_cypress_docs",   fetch_cypress_docs)
_cypress_docs_sg.add_node("detect_api_changes",   detect_api_changes)
_cypress_docs_sg.add_node("build_cypress_context", build_cypress_context)
_cypress_docs_sg.add_edge(START, "fetch_cypress_docs")
_cypress_docs_sg.add_edge("fetch_cypress_docs",   "detect_api_changes")
_cypress_docs_sg.add_edge("detect_api_changes",   "build_cypress_context")
_cypress_docs_sg.add_edge("build_cypress_context", END)

# Compiled once at import time; reused for every pipeline run.
cypress_docs_subgraph = _cypress_docs_sg.compile()


async def cypress_docs_check(state: QAState) -> dict:
    """Wrapper node — invokes the cypress_docs subgraph with state transformation.

    Cache hit  (age < 24 h): return cypress_api_context instantly from disk.
    Cache miss (stale/missing): transform parent state → invoke subgraph
                                → transform subgraph output back to parent state.
    Fails gracefully so the pipeline continues with hardcoded rules if docs
    are unreachable.
    """
    # ── Fast path: 24-hour cache is warm ────────────────────
    if docs_cache.is_fresh():
        age = docs_cache.age_hours()
        logger.info("cypress_docs_check: cache hit (%.1f h old) — skipping subgraph", age or 0)
        # Transform subgraph output → parent state
        return {"cypress_api_context": docs_cache.load()}

    # ── Slow path: cache stale / first run ──────────────────
    logger.info("cypress_docs_check: cache stale — invoking cypress_docs subgraph")
    try:
        # Transform parent state → subgraph input (subgraph is self-contained, no input needed)
        subgraph_output: CypressDocsState = await cypress_docs_subgraph.ainvoke({})

        # Transform subgraph output → parent state
        ctx = subgraph_output.get("cypress_api_context") or {}
        docs_cache.save(ctx)

        if ctx.get("has_updates"):
            logger.info(
                "cypress_docs_check: %d API change(s) detected from live docs",
                len(ctx.get("changes_detected", [])),
            )
        else:
            logger.info("cypress_docs_check: no API changes vs baseline")
        return {"cypress_api_context": ctx}

    except Exception as exc:
        logger.warning("cypress_docs_check: subgraph failed (%s) — continuing without docs", exc)
        return {"cypress_api_context": {}}


# ── HITL Gate Nodes ──────────────────────────────────────────
# Each gate calls interrupt() so LangSmith Studio can resume natively.
# The resume value is a dict: {"approved": bool, "feedback": str, "edited_state_payload": dict}
# All routing logic lives in the conditional edges AFTER these nodes.


def _apply_gate_decision(decision, phase_n: int) -> dict:
    """Parse interrupt() resume value → state update for the given phase gate."""
    if isinstance(decision, dict):
        raw = decision.get("approved", True)
        approved = raw.lower() not in ("false", "no", "reject") if isinstance(raw, str) else bool(raw)
        update: dict = {f"phase_{phase_n}_approved": approved}
        if decision.get("feedback"):
            update["human_feedback"] = [decision["feedback"]]
        if decision.get("edited_state_payload"):
            update.update(decision["edited_state_payload"])
        return update
    # Plain bool / string ("yes", "true", "approved", …)
    approved = str(decision).lower() not in ("false", "no", "0", "reject", "rejected", "n")
    return {f"phase_{phase_n}_approved": approved}


async def phase_0_gate(state: QAState) -> dict:
    """HITL gate — pauses for PRD review. Works in LangSmith Studio and via /resume API."""
    return _apply_gate_decision(interrupt({"phase": 0}), 0)


async def phase_1_gate(state: QAState) -> dict:
    """HITL gate — pauses for Phase 1 (Architect) review."""
    return _apply_gate_decision(interrupt({"phase": 1}), 1)


async def phase_2_gate(state: QAState) -> dict:
    """HITL gate — pauses for Phase 2 (Strategist) review."""
    return _apply_gate_decision(interrupt({"phase": 2}), 2)


async def phase_3_gate(state: QAState) -> dict:
    """HITL gate — pauses for Phase 3 (SDET) review."""
    return _apply_gate_decision(interrupt({"phase": 3}), 3)


async def phase_4_gate(state: QAState) -> dict:
    """HITL gate — pauses for Phase 4 (Executor) review."""
    return _apply_gate_decision(interrupt({"phase": 4}), 4)


# ── Conditional Router Functions ─────────────────────────────


def _route_start(state: QAState) -> str:
    """Route from START: skip Phase 0 when the user supplies their own PRD."""
    return "own" if state.get("prd_source") == "own" else "reference"


def _gate_0_router(state: QAState) -> str:
    """Route after phase_0_gate: approved → Phase 1, rejected → redo PRD."""
    return "approved" if state.get("phase_0_approved") else "rejected"


def _route_phase_1(state: QAState) -> str:
    """Route after map_to_prd: skip gate in auto mode."""
    return "manual" if state.get("run_mode") == "manual" else "auto"


def _gate_1_router(state: QAState) -> str:
    """Route after phase_1_gate: approved → Phase 2, rejected → re-crawl."""
    return "approved" if state.get("phase_1_approved") else "rejected"


def _route_phase_2(state: QAState) -> str:
    """Route after merge_strategies: skip gate in auto mode."""
    return "manual" if state.get("run_mode") == "manual" else "auto"


def _gate_2_router(state: QAState) -> str:
    """Route after phase_2_gate: approved → Phase 3, rejected → redo happy paths."""
    return "approved" if state.get("phase_2_approved") else "rejected"


def _route_syntax_linter(state: QAState) -> str:
    """Route after syntax_linter.

    Priority:
      1. If POM lint errors remain AND budget not exhausted → pom_lint_retry.
      2. If spec lint errors remain AND budget not exhausted → lint_retry.
      3. If manual mode → phase_3_gate (human decides even on lint-give-up).
      4. Otherwise → pre_flight_check (auto pass or lint budget exhausted).
    """
    pom_lint_errors = state.get("pom_lint_errors") or []
    lint_errors = state.get("lint_errors") or []
    lint_retry_count = state.get("lint_retry_count", 0)

    if pom_lint_errors and lint_retry_count < config.MAX_RETRIES:
        return "pom_lint_retry"
    if lint_errors and lint_retry_count < config.MAX_RETRIES:
        return "lint_retry"
    if state.get("run_mode") == "manual":
        return "manual_pass"
    return "auto_pass"


def _gate_3_router(state: QAState) -> str:
    """Route after phase_3_gate: approved → Phase 4, rejected → redo page objects."""
    return "approved" if state.get("phase_3_approved") else "rejected"


def _route_executor(state: QAState) -> str:
    """Route after classify_errors.

    Priority:
      1. If last run passed → done (skip healing even if old errors linger in state).
      2. If test_code_errors exist AND retry budget not exhausted → heal_tests.
      3. If manual mode → phase_4_gate.
      4. Otherwise → aggregate_metrics.
    """
    exec_history = state.get("execution_history", [])
    last_run = exec_history[-1] if exec_history and isinstance(exec_history[-1], dict) else {}

    # If the last run had zero failures, no healing needed regardless of accumulated errors.
    if last_run.get("failed", 0) == 0 and last_run.get("status") == "pass":
        if state.get("run_mode") == "manual":
            return "manual_done"
        return "auto_done"

    classified = state.get("classified_errors", [])
    test_code_errors = [e for e in classified if e.get("type") == "test_code_error"]
    retry_count = state.get("retry_count", 0)

    if test_code_errors and retry_count < config.MAX_CYPRESS_RUNS:
        return "needs_healing"
    if state.get("run_mode") == "manual":
        return "manual_done"
    return "auto_done"


def _gate_4_router(state: QAState) -> str:
    """Route after phase_4_gate: approved → Phase 5, rejected → re-run executor."""
    return "approved" if state.get("phase_4_approved") else "rejected"


# ── Graph builder ────────────────────────────────────────────


def build_graph(
    browser: PlaywrightAdapter,
    dom_processor: DOMProcessor | None = None,
    checkpointer_backend: str | None = None,
    checkpointer: object | None = None,
):
    """Construct and compile the QA-Web-Agent V2 workflow.

    Parameters
    ----------
    browser
        An initialised (but not necessarily started) BrowserAdapter.
    dom_processor
        Optional pre-configured DOMProcessor. Default instance created if None.
    checkpointer_backend
        Explicit checkpointer selection. Ignored when *checkpointer* is provided.
    checkpointer
        A pre-created checkpointer instance. Takes priority over *checkpointer_backend*.

    Returns
    -------
    compiled_graph
        A CompiledGraph ready for .ainvoke() / .astream().
    """
    if dom_processor is None:
        dom_processor = DOMProcessor()

    from src.agents.architect import _build_architect_nodes

    architect_nodes = _build_architect_nodes(browser, dom_processor)
    crawl_target = architect_nodes["crawl_target"]
    analyze_dom = architect_nodes["analyze_dom"]
    map_to_prd = architect_nodes["map_to_prd"]

    # ── Assemble graph ──────────────────────────────────────
    workflow = StateGraph(QAState)

    # Phase 0 — PRD Maker Cluster
    workflow.add_node("research_references", research_references)
    workflow.add_node("draft_prd", draft_prd)
    workflow.add_node("phase_0_gate", phase_0_gate)

    # Phase 1 — Architect Cluster
    workflow.add_node("crawl_target", crawl_target)
    workflow.add_node("analyze_dom", analyze_dom)
    workflow.add_node("map_to_prd", map_to_prd)
    workflow.add_node("phase_1_gate", phase_1_gate)

    # Cypress Docs Check — between Phase 1 and Phase 2
    workflow.add_node("cypress_docs_check", cypress_docs_check)

    # Phase 2 — Strategist Cluster
    workflow.add_node("generate_happy_paths", generate_happy_paths)
    workflow.add_node("generate_edge_cases", generate_edge_cases)
    workflow.add_node("merge_strategies", merge_strategies)
    workflow.add_node("phase_2_gate", phase_2_gate)

    # Phase 3 — SDET Cluster
    workflow.add_node("generate_page_objects", generate_page_objects)
    workflow.add_node("generate_specs", generate_specs)
    workflow.add_node("syntax_linter", syntax_linter)
    workflow.add_node("phase_3_gate", phase_3_gate)

    # Phase 4 — Executor Cluster
    workflow.add_node("pre_flight_check", pre_flight_check)
    workflow.add_node("run_cypress", run_cypress)
    workflow.add_node("classify_errors", classify_errors)
    workflow.add_node("heal_tests", heal_tests)
    workflow.add_node("phase_4_gate", phase_4_gate)

    # Phase 5 — Reporter Cluster
    workflow.add_node("aggregate_metrics", aggregate_metrics)
    workflow.add_node("draft_bug_tickets", draft_bug_tickets)
    workflow.add_node("assemble_markdown", assemble_markdown)

    # ── Phase 0 edges ───────────────────────────────────────
    # When prd_source=="own" skip research + draft entirely and go straight to Phase 1.
    workflow.add_conditional_edges(
        START,
        _route_start,
        {"own": "crawl_target", "reference": "research_references"},
    )
    workflow.add_edge("research_references", "draft_prd")
    # PRD gate is mandatory — always interrupts regardless of run_mode
    workflow.add_edge("draft_prd", "phase_0_gate")
    workflow.add_conditional_edges(
        "phase_0_gate",
        _gate_0_router,
        {"approved": "crawl_target", "rejected": "research_references"},
    )

    # ── Phase 1 edges ───────────────────────────────────────
    workflow.add_edge("crawl_target", "analyze_dom")
    workflow.add_edge("analyze_dom", "map_to_prd")

    # Route: auto skips gate; manual routes to gate.
    # Both paths funnel through cypress_docs_check before Phase 2.
    workflow.add_conditional_edges(
        "map_to_prd",
        _route_phase_1,
        {"auto": "cypress_docs_check", "manual": "phase_1_gate"},
    )
    # Gate 1: noop → route based on approval
    workflow.add_conditional_edges(
        "phase_1_gate",
        _gate_1_router,
        {"approved": "cypress_docs_check", "rejected": "crawl_target"},
    )
    # Docs check always feeds into Phase 2
    workflow.add_edge("cypress_docs_check", "generate_happy_paths")

    # ── Phase 2 edges ───────────────────────────────────────
    workflow.add_edge("generate_happy_paths", "generate_edge_cases")
    workflow.add_edge("generate_edge_cases", "merge_strategies")

    workflow.add_conditional_edges(
        "merge_strategies",
        _route_phase_2,
        {"auto": "generate_page_objects", "manual": "phase_2_gate"},
    )
    workflow.add_conditional_edges(
        "phase_2_gate",
        _gate_2_router,
        {"approved": "generate_page_objects", "rejected": "generate_happy_paths"},
    )

    # ── Phase 3 edges ───────────────────────────────────────
    workflow.add_edge("generate_page_objects", "generate_specs")
    workflow.add_edge("generate_specs", "syntax_linter")

    workflow.add_conditional_edges(
        "syntax_linter",
        _route_syntax_linter,
        {
            "pom_lint_retry": "generate_page_objects",
            "lint_retry":     "generate_specs",
            "auto_pass":      "pre_flight_check",
            "manual_pass":    "phase_3_gate",
        },
    )
    workflow.add_conditional_edges(
        "phase_3_gate",
        _gate_3_router,
        {"approved": "pre_flight_check", "rejected": "generate_page_objects"},
    )

    # ── Phase 4 edges ───────────────────────────────────────
    workflow.add_edge("pre_flight_check", "run_cypress")
    workflow.add_edge("run_cypress", "classify_errors")

    workflow.add_conditional_edges(
        "classify_errors",
        _route_executor,
        {
            "needs_healing": "heal_tests",
            "auto_done":     "aggregate_metrics",
            "manual_done":   "phase_4_gate",
        },
    )
    # Heal loop: heal_tests → run_cypress
    workflow.add_edge("heal_tests", "run_cypress")

    workflow.add_conditional_edges(
        "phase_4_gate",
        _gate_4_router,
        {"approved": "aggregate_metrics", "rejected": "pre_flight_check"},
    )

    # ── Phase 5 edges ───────────────────────────────────────
    workflow.add_edge("aggregate_metrics", "draft_bug_tickets")
    workflow.add_edge("draft_bug_tickets", "assemble_markdown")
    workflow.add_edge("assemble_markdown", END)

    # ── Compile with persistence & HITL interrupt points ────
    if checkpointer is None:
        checkpointer = create_checkpointer()

    compiled = workflow.compile(
        checkpointer=checkpointer,
        # No interrupt_before — gate nodes call interrupt() directly,
        # which works natively in LangSmith Studio and via the /resume API.
    )

    logger.info(
        "QA-Web-Agent V2 graph compiled (%d nodes, checkpointer=%s)",
        len(workflow.nodes),
        type(checkpointer).__name__,
    )
    return compiled


def create_graph():
    """Zero-arg factory for ``langgraph dev`` (LangGraph Platform CLI).

    The CLI requires the factory to accept 0–2 params. This wrapper
    creates default browser + DOM processor and calls build_graph().
    """
    from src.browser.playwright_adapter import PlaywrightAdapter

    browser = PlaywrightAdapter()
    dom_processor = DOMProcessor()
    return build_graph(browser=browser, dom_processor=dom_processor)
