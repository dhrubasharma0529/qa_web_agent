"""FastAPI server — entry point for the QA-Web-Agent V2 platform.

Endpoints
---------
* ``POST /analyze``                  — kick off a full graph run (auto or manual mode)
* ``POST /analyze/stream``           — SSE streaming of agent steps
* ``POST /runs/{thread_id}/resume``  — HITL: approve/reject a phase gate and resume
* ``GET  /report/{thread_id}``       — fetch results from a completed run
* ``GET  /runs/{thread_id}/state``   — inspect current graph state (incl. next gate)
* ``GET  /health``                   — liveness probe
"""
from __future__ import annotations
import asyncio
import json
import logging
import time
import uuid
from contextlib import asynccontextmanager
from pathlib import Path

from dotenv import load_dotenv
from fastapi import BackgroundTasks, FastAPI, HTTPException
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles

from langgraph.types import Command

from src.browser.playwright_adapter import PlaywrightAdapter
from src.dom.processor import DOMProcessor
from src.graph.checkpointer import create_async_checkpointer
from src.graph.workflow import build_graph
from src.models.schemas import AnalyzeRequest, AnalyzeResponse, ResumeRequest, RunStatus

load_dotenv()

logger = logging.getLogger(__name__)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(name)-30s  %(levelname)-7s  %(message)s",
)


# ── Lifespan ────────────────────────────────────────────────


async def _docs_refresh_loop() -> None:
    """Background task: refresh the Cypress docs cache every 24 hours.

    On first call it refreshes immediately if the cache is stale, then sleeps
    for 24 hours before each subsequent refresh. This keeps the cache warm so
    pipeline runs always hit the fast (cache-read) path in cypress_docs_check.
    """
    from src.agents.cypress_docs import docs_cache, refresh_docs_cache

    if not docs_cache.is_fresh():
        logger.info("Cypress docs cache: stale on startup — running initial refresh")
        await refresh_docs_cache()
    else:
        age = docs_cache.age_hours()
        logger.info("Cypress docs cache: fresh (%.1f h old) — skipping startup refresh", age or 0)

    while True:
        await asyncio.sleep(24 * 3600)
        logger.info("Cypress docs cache: 24 h TTL reached — refreshing")
        await refresh_docs_cache()


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup / shutdown hook — manages browser, checkpointer, graph & docs refresh."""
    adapter = PlaywrightAdapter()
    await adapter.start()
    logger.info("Browser adapter started (%s)", type(adapter).__name__)

    checkpointer = await create_async_checkpointer()
    logger.info("Checkpointer ready (%s)", type(checkpointer).__name__)

    dom_processor = DOMProcessor()
    graph = build_graph(
        browser=adapter,
        dom_processor=dom_processor,
        checkpointer=checkpointer,
    )

    app.state.browser = adapter
    app.state.dom_processor = dom_processor
    app.state.checkpointer = checkpointer
    app.state.graph = graph

    # Start daily Cypress docs refresh in the background
    docs_task = asyncio.create_task(_docs_refresh_loop())
    app.state.docs_task = docs_task
    logger.info("Cypress docs refresh task started (24 h interval)")

    yield

    docs_task.cancel()
    try:
        await docs_task
    except asyncio.CancelledError:
        pass
    logger.info("Cypress docs refresh task stopped")

    await adapter.stop()
    logger.info("Browser adapter stopped")


app = FastAPI(
    title="QA-Web-Agent V2",
    version="2.0.0",
    description="Autonomous end-to-end QA platform powered by LangGraph + GPT-4o (V2 with HITL)",
    lifespan=lifespan,
)

# ── Static files & frontend ────────────────────────────────

STATIC_DIR = Path(__file__).resolve().parent.parent / "static"
REPORTS_DIR = Path(__file__).resolve().parent.parent / "reports"
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")


@app.get("/")
async def index():
    return FileResponse(str(STATIC_DIR / "index.html"))


@app.get("/reports/{filename}")
async def get_report_file(filename: str):
    if not filename.endswith(".md"):
        raise HTTPException(status_code=400, detail="Only .md files are served")
    filepath = REPORTS_DIR / filename
    if not filepath.exists():
        raise HTTPException(status_code=404, detail=f"Report '{filename}' not found")
    return FileResponse(str(filepath), media_type="text/markdown", filename=filename)


# ── Helpers ─────────────────────────────────────────────────


def _new_thread_id() -> str:
    return f"qa-{uuid.uuid4().hex[:12]}"


def _build_initial_state(req: AnalyzeRequest) -> dict:
    """Build initial QAState for a new graph run."""
    return {
        "url": str(req.url),
        "project_description": req.prd_text or "",
        "run_mode": req.run_mode or "auto",
        "prd_source": req.prd_source if req.prd_source in ("own", "reference") else "reference",
        # Phase outputs
        "test_cases": [],
        "cypress_file_paths": [],
        "errors": [],
        "execution_history": [],
        "retry_count": 0,
        # V2 HITL fields
        "human_feedback": [],
        "phase_0_approved": False,
        "phase_1_approved": False,
        "phase_2_approved": False,
        "phase_3_approved": False,
        "phase_4_approved": False,
        # V2 intermediate fields
        "happy_path_cases": None,
        "edge_case_cases": None,
        "lint_errors": None,
        "pom_lint_errors": None,
        "lint_retry_count": 0,
        "classified_errors": [],
        "heal_retry_count": 0,
    }


# ── Endpoints ───────────────────────────────────────────────


@app.get("/health")
async def health():
    return {"status": "ok"}


@app.get("/docs/status")
async def docs_status():
    """Return the current state of the Cypress API docs cache."""
    from src.agents.cypress_docs import docs_cache
    return docs_cache.status()


@app.post("/docs/refresh")
async def docs_refresh(background_tasks: BackgroundTasks):
    """Manually trigger a Cypress docs cache refresh (runs in background).

    Returns immediately. Poll GET /docs/status to see when it completes.
    """
    from src.agents.cypress_docs import refresh_docs_cache
    background_tasks.add_task(refresh_docs_cache)
    return {"status": "refresh_started"}


@app.post("/analyze", response_model=AnalyzeResponse)
async def analyze(req: AnalyzeRequest):
    """Kick off the full QA workflow for a given URL + PRD.

    In **auto** mode (default): runs the complete pipeline and returns when done.
    In **manual** mode: runs until the first phase gate, then returns with
    ``status="running"`` and ``thread_id`` so the client can call ``/runs/{thread_id}/state``
    to inspect the phase output, then ``/runs/{thread_id}/resume`` to approve/reject.
    """
    thread_id = _new_thread_id()
    config_lg = {"configurable": {"thread_id": thread_id}}
    initial_state = _build_initial_state(req)

    result = None
    invoke_error = None
    try:
        result = await app.state.graph.ainvoke(initial_state, config_lg)
    except Exception as exc:
        invoke_error = exc

    # interrupt() may return normally OR raise — always check snapshot for paused state.
    snapshot = None
    try:
        snapshot = await app.state.graph.aget_state(config_lg)
    except Exception:
        pass

    if snapshot and snapshot.next:
        logger.info("Graph paused at gate(s) %s for thread %s", snapshot.next, thread_id)
        return AnalyzeResponse(
            thread_id=thread_id,
            status=RunStatus.RUNNING,
            report={"next_nodes": list(snapshot.next)},
            errors=[],
        )

    if result is not None:
        status = RunStatus.COMPLETED if not result.get("errors") else RunStatus.FAILED
        return AnalyzeResponse(
            thread_id=thread_id,
            status=status,
            report={
                "technical_overview": result.get("technical_overview"),
                "test_cases": result.get("test_cases"),
                "cypress_file_paths": result.get("cypress_file_paths"),
                "execution_history": result.get("execution_history"),
            },
            errors=result.get("errors", []),
        )

    logger.exception("Graph run failed for thread %s", thread_id)
    return AnalyzeResponse(
        thread_id=thread_id,
        status=RunStatus.FAILED,
        errors=[str(invoke_error)],
    )


@app.post("/analyze/stream")
async def analyze_stream(req: AnalyzeRequest):
    """SSE stream of every graph event as it happens.

    Emits structured events the frontend can use for real-time UI updates:
      - init:          thread_id assigned
      - node_start:    a graph node begins execution (includes phase info)
      - node_end:      a graph node finishes (includes phase, outputs summary)
      - files_written: new files were generated (includes paths list)
      - lint_result:   syntax_linter finished (includes error counts)
      - state_snapshot: periodic full-state push so tabs can refresh
      - error:         something went wrong
      - done:          stream finished
    """
    thread_id = _new_thread_id()
    config_lg = {"configurable": {"thread_id": thread_id}}
    initial_state = _build_initial_state(req)

    # Phase lookup for each node
    PHASE_MAP = {
        "research_references": 0, "draft_prd": 0, "phase_0_gate": 0,
        "crawl_target": 1, "analyze_dom": 1, "map_to_prd": 1,
        "phase_1_gate": 1,
        "cypress_docs_check": 1,   # runs after Phase 1, before Phase 2
        "generate_happy_paths": 2, "generate_edge_cases": 2, "merge_strategies": 2,
        "phase_2_gate": 2,
        "generate_page_objects": 3, "generate_specs": 3, "syntax_linter": 3,
        "phase_3_gate": 3,
        "pre_flight_check": 4, "run_cypress": 4, "classify_errors": 4, "heal_tests": 4,
        "phase_4_gate": 4,
        "aggregate_metrics": 5, "draft_bug_tickets": 5, "assemble_markdown": 5,
    }

    NODE_LABELS = {
        "research_references": "Finding 4 reference websites",
        "draft_prd": "Generating PRD from references",
        "crawl_target": "Crawling target website",
        "analyze_dom": "Analyzing DOM structure",
        "map_to_prd": "Mapping to PRD requirements",
        "cypress_docs_check": "Checking live Cypress API docs",
        "generate_happy_paths": "Generating happy-path test cases",
        "generate_edge_cases": "Generating edge-case test cases",
        "merge_strategies": "Merging test strategies",
        "generate_page_objects": "Generating Page Object Models",
        "generate_specs": "Generating Cypress spec files",
        "syntax_linter": "Linting generated files",
        "pre_flight_check": "Pre-flight environment check",
        "run_cypress": "Running Cypress tests",
        "classify_errors": "Classifying test errors",
        "heal_tests": "Self-healing failed tests",
        "aggregate_metrics": "Aggregating test metrics",
        "draft_bug_tickets": "Drafting bug tickets",
        "assemble_markdown": "Assembling final report",
    }

    async def _event_generator():
        yield f"data: {json.dumps({'type': 'init', 'thread_id': thread_id})}\n\n"

        completed_nodes = set()
        last_snapshot_time = 0

        try:
            async for event in app.state.graph.astream_events(
                initial_state, config_lg, version="v2"
            ):
                kind = event.get("event", "")
                name = event.get("name", "")
                phase = PHASE_MAP.get(name)

                if kind == "on_chain_start" and name in PHASE_MAP:
                    payload = {
                        "type": "node_start",
                        "node": name,
                        "phase": phase,
                        "label": NODE_LABELS.get(name, name),
                    }
                    yield f"data: {json.dumps(payload)}\n\n"

                elif kind == "on_chain_end" and name in PHASE_MAP:
                    completed_nodes.add(name)
                    output_data = event.get("data", {})
                    output = output_data.get("output", {}) if isinstance(output_data, dict) else {}

                    payload = {
                        "type": "node_end",
                        "node": name,
                        "phase": phase,
                        "label": NODE_LABELS.get(name, name),
                    }

                    # Emit file generation events
                    if name in ("generate_page_objects", "generate_specs"):
                        file_paths = []
                        if isinstance(output, dict):
                            file_paths = output.get("cypress_file_paths", [])
                        if file_paths:
                            payload["files"] = file_paths
                            files_evt = {
                                "type": "files_written",
                                "node": name,
                                "phase": phase,
                                "files": file_paths,
                                "kind": "page_objects" if name == "generate_page_objects" else "specs",
                            }
                            yield f"data: {json.dumps(files_evt)}\n\n"

                    # Emit lint result events
                    if name == "syntax_linter" and isinstance(output, dict):
                        lint_evt = {
                            "type": "lint_result",
                            "phase": 3,
                            "spec_errors": output.get("lint_errors", []),
                            "pom_errors": output.get("pom_lint_errors", []),
                            "retry_count": output.get("lint_retry_count", 0),
                            "passed": not output.get("lint_errors") and not output.get("pom_lint_errors"),
                        }
                        yield f"data: {json.dumps(lint_evt)}\n\n"

                    # Emit test case count after strategist
                    if name == "merge_strategies" and isinstance(output, dict):
                        cases = output.get("test_cases", [])
                        if cases:
                            payload["test_case_count"] = len(cases)

                    # Emit execution results
                    if name == "run_cypress" and isinstance(output, dict):
                        exec_hist = output.get("execution_history", [])
                        if exec_hist:
                            last_run = exec_hist[-1] if isinstance(exec_hist[-1], dict) else {}
                            payload["execution"] = {
                                "passed": last_run.get("passed", 0),
                                "failed": last_run.get("failed", 0),
                                "total": last_run.get("total_tests", 0),
                                "status": last_run.get("status", "unknown"),
                            }

                    yield f"data: {json.dumps(payload)}\n\n"

                    # Emit PRD-ready event so the frontend can show it for review
                    if name == "draft_prd" and isinstance(output, dict):
                        # prd_site_type lives in state (set by research_references), not in draft_prd output
                        try:
                            snap_for_prd = await app.state.graph.aget_state(config_lg)
                            site_type = (snap_for_prd.values or {}).get("prd_site_type", "") if snap_for_prd else ""
                        except Exception:
                            site_type = ""
                        prd_evt = {
                            "type": "prd_ready",
                            "phase": 0,
                            "site_type": site_type,
                            "project_description": output.get("project_description", ""),
                        }
                        yield f"data: {json.dumps(prd_evt)}\n\n"

                    # Periodic state snapshot after important nodes
                    now = time.time()
                    important_nodes = {
                        "draft_prd", "map_to_prd", "merge_strategies",
                        "generate_page_objects", "generate_specs", "syntax_linter",
                        "run_cypress", "classify_errors", "assemble_markdown",
                    }
                    if name in important_nodes and (now - last_snapshot_time) > 1.5:
                        last_snapshot_time = now
                        try:
                            snapshot = await app.state.graph.aget_state(config_lg)
                            if snapshot and snapshot.values:
                                snap_payload = {
                                    "type": "state_snapshot",
                                    "values": _serialize_state(snapshot.values),
                                    "next": list(snapshot.next) if snapshot.next else [],
                                }
                                yield f"data: {json.dumps(snap_payload)}\n\n"
                        except Exception:
                            pass

                elif kind in ("on_chain_start", "on_chain_end", "on_chain_stream"):
                    # Other sub-chain events — emit as generic log
                    if name and name not in PHASE_MAP:
                        payload = {
                            "type": kind,
                            "name": name,
                            "data": str(event.get("data", ""))[:500],
                        }
                        yield f"data: {json.dumps(payload)}\n\n"

        except Exception as exc:
            yield f"data: {json.dumps({'type': 'error', 'detail': str(exc)})}\n\n"

        # Final state snapshot
        try:
            snapshot = await app.state.graph.aget_state(config_lg)
            if snapshot and snapshot.values:
                snap_payload = {
                    "type": "state_snapshot",
                    "values": _serialize_state(snapshot.values),
                    "next": list(snapshot.next) if snapshot.next else [],
                    "final": True,
                }
                yield f"data: {json.dumps(snap_payload)}\n\n"
        except Exception:
            pass

        yield f"data: {json.dumps({'type': 'done', 'thread_id': thread_id})}\n\n"

    return StreamingResponse(_event_generator(), media_type="text/event-stream")


def _serialize_state(values: dict) -> dict:
    """Make graph state JSON-serializable for SSE push."""
    safe = {}
    for k, v in values.items():
        try:
            json.dumps(v)
            safe[k] = v
        except (TypeError, ValueError):
            safe[k] = str(v)[:500]
    return safe


async def _run_graph_background(config_lg: dict, command: Command | None = None) -> None:
    """Fire-and-forget: resume the graph after a HITL gate decision."""
    try:
        await app.state.graph.ainvoke(command, config_lg)
    except Exception as exc:
        logger.debug("Background graph resume finished (gate or completion): %s", exc)


@app.post("/runs/{thread_id}/resume")
async def resume_run(thread_id: str, payload: ResumeRequest, background_tasks: BackgroundTasks):
    """HITL resume — approve or reject a phase gate, then continue the graph.

    Returns immediately with status="running" so the frontend can poll for
    progress via GET /runs/{thread_id}/state, rather than blocking until the
    entire pipeline finishes.
    """
    config_lg = {"configurable": {"thread_id": thread_id}}

    # Verify the run exists
    try:
        snapshot = await app.state.graph.aget_state(config_lg)
    except Exception as exc:
        raise HTTPException(status_code=404, detail=f"Thread not found: {exc}") from exc

    if snapshot is None or snapshot.values is None:
        raise HTTPException(status_code=404, detail="Thread not found")

    if not snapshot.next:
        raise HTTPException(
            status_code=409,
            detail="Graph is not paused at a gate — no resume needed",
        )

    # Build Command(resume=...) — the gate node receives this via interrupt() return value
    # and sets phase_N_approved + any feedback/edits itself.
    resume_value: dict = {"approved": payload.approved}
    if payload.feedback:
        resume_value["feedback"] = payload.feedback
    if payload.edited_state_payload:
        resume_value["edited_state_payload"] = payload.edited_state_payload

    command = Command(resume=resume_value)
    logger.info(
        "Resuming thread %s — phase=%d approved=%s (background)",
        thread_id, payload.phase, payload.approved,
    )

    # Kick off graph execution in the background — return immediately
    background_tasks.add_task(_run_graph_background, config_lg, command)

    return {
        "thread_id": thread_id,
        "next_nodes": [],
        "status": "running",
    }


@app.get("/report/{thread_id}")
async def get_report(thread_id: str):
    """Retrieve the final state of a completed (or in-progress) run."""
    try:
        snapshot = await app.state.graph.aget_state(
            {"configurable": {"thread_id": thread_id}}
        )
    except Exception as exc:
        logger.exception("Failed to fetch report for thread %s", thread_id)
        raise HTTPException(status_code=404, detail=str(exc))

    if snapshot is None or snapshot.values is None:
        raise HTTPException(status_code=404, detail="Thread not found")

    values = snapshot.values
    return {
        "thread_id": thread_id,
        "next_nodes": list(snapshot.next),
        "report": {
            "prd_site_type": values.get("prd_site_type"),
            "project_description": values.get("project_description"),
            "technical_overview": values.get("technical_overview"),
            "test_cases": values.get("test_cases"),
            "cypress_file_paths": values.get("cypress_file_paths"),
            "execution_history": values.get("execution_history"),
            "errors": values.get("errors"),
            "classified_errors": values.get("classified_errors"),
            "human_feedback": values.get("human_feedback"),
            "report_paths": values.get("report_paths"),
            "report_summary": values.get("report_summary"),
        },
    }


@app.get("/runs/{thread_id}/state")
async def get_run_state(thread_id: str):
    """Inspect the raw graph state — useful for HITL review or debugging."""
    try:
        snapshot = await app.state.graph.aget_state(
            {"configurable": {"thread_id": thread_id}}
        )
    except Exception as exc:
        logger.exception("Failed to fetch state for thread %s", thread_id)
        raise HTTPException(status_code=404, detail=str(exc))

    if snapshot is None or snapshot.values is None:
        raise HTTPException(status_code=404, detail="Thread not found")

    return {
        "thread_id": thread_id,
        "values": _serialize_state(snapshot.values),
        "next": list(snapshot.next),
        "config": snapshot.config,
    }


# ── LangGraph Platform compatibility ───────────────────────
if __name__ == "__main__":
    import uvicorn
    uvicorn.run("src.server:app", host="0.0.0.0", port=8000, reload=False)
