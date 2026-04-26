"""Reporter Agent — Phase 5: Report Generation (V2 Cluster).

Three specialized nodes replace the V1 monolith:
    1. aggregate_metrics  — Python: calculates pass/fail ratios from execution history
    2. draft_bug_tickets  — LLM: drafts Jira-style tickets for app_bug failures
    3. assemble_markdown  — Python: writes test_cases_report.md and bug_report.md
"""

from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime
from pathlib import Path

from langchain_core.prompts import ChatPromptTemplate
from langchain_openai import ChatOpenAI
from langsmith import traceable

from src.config import config
from src.models.state import QAState

logger = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).resolve().parents[2]
REPORTS_DIR = PROJECT_ROOT / "reports"


# ── LLM factory ─────────────────────────────────────────────

def _get_llm() -> ChatOpenAI:
    return ChatOpenAI(model=config.LLM_MODEL, temperature=0)


# ── Prompts ─────────────────────────────────────────────────

_BUG_TICKET_PROMPT = ChatPromptTemplate.from_messages(
    [
        (
            "system",
            "You are a QA Lead drafting Jira bug tickets.  "
            "For each app_bug entry provided, write a concise Jira ticket.\n\n"
            "Output strict JSON:\n"
            "{{\n"
            '  "tickets": [\n'
            "    {{\n"
            '      "title": "short bug title",\n'
            '      "severity": "Critical|High|Medium|Low",\n'
            '      "description": "what the bug is",\n'
            '      "steps_to_reproduce": ["step 1", "step 2"],\n'
            '      "expected": "what should happen",\n'
            '      "actual": "what actually happened"\n'
            "    }}\n"
            "  ]\n"
            "}}",
        ),
        (
            "human",
            "## App Bug Failures\n```json\n{app_bugs}\n```\n\n"
            "## Application Context\n{app_context}",
        ),
    ]
)


# ── Helpers ──────────────────────────────────────────────────

def _ensure_reports_dir() -> Path:
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    return REPORTS_DIR


def _write_reports(tc_md: str, bug_md: str) -> tuple[str, str]:
    """Sync: create reports dir + write both .md files. Called via asyncio.to_thread."""
    d = _ensure_reports_dir()
    tc_path = d / "test_cases_report.md"
    bug_path = d / "bug_report.md"
    tc_path.write_text(tc_md, encoding="utf-8")
    bug_path.write_text(bug_md, encoding="utf-8")
    return str(tc_path), str(bug_path)


def _build_test_cases_md(state: QAState) -> str:
    """Generate a structured test-case report in Markdown."""
    url = state.get("url", "N/A")
    prd = state.get("project_description", "N/A")
    test_cases = state.get("test_cases", [])
    kg = state.get("technical_overview", {})
    exec_history = state.get("execution_history", [])

    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    last_run = exec_history[-1] if exec_history else {}
    passed = last_run.get("passed", 0)
    failed = last_run.get("failed", 0)
    total = last_run.get("total_tests", len(test_cases))

    # Pull metrics if aggregate_metrics already computed them
    metrics = (kg or {}).get("metrics", {}) if kg else {}
    pass_rate = metrics.get("pass_rate_pct", "N/A")

    lines = [
        "# 📋 Test Cases Report",
        "",
        f"> **Generated**: {now}  ",
        f"> **Target URL**: [{url}]({url})  ",
        f"> **PRD**: {prd[:200]}{'…' if len(prd) > 200 else ''}",
        "",
        "---",
        "",
        "## 📊 Summary",
        "",
        "| Metric | Value |",
        "|--------|-------|",
        f"| Total Test Cases | {len(test_cases)} |",
        f"| Tests Executed | {total} |",
        f"| ✅ Passed | {passed} |",
        f"| ❌ Failed | {failed} |",
        f"| Pass Rate | {pass_rate}% |" if pass_rate != "N/A" else f"| Pass Rate | N/A |",
        f"| Retry Attempts | {state.get('retry_count', 0)} |",
        f"| Heal Attempts | {state.get('heal_retry_count', 0)} |",
        "",
    ]

    if kg:
        lines.extend([
            "## 🧠 Application Overview",
            "",
            f"- **App Title**: {kg.get('app_title', 'N/A')}",
            f"- **Tech Stack**: {', '.join(kg.get('tech_signals', []))}",
            "",
        ])
        impl_features = kg.get("implemented_features", [])
        if impl_features:
            lines.append("### ✅ Implemented Features")
            lines.append("")
            for f in impl_features:
                lines.append(f"- **{f.get('feature', '')}**: {f.get('evidence', '')}")
            lines.append("")
        missing = kg.get("missing_features", [])
        if missing:
            lines.append("### ❌ Missing Features")
            lines.append("")
            for f in missing:
                lines.append(f"- **{f.get('feature', '')}** — _{f.get('prd_reference', '')}_")
            lines.append("")

    lines.extend(["---", "", "## 🧪 Test Cases", ""])

    severity_icons = {"critical": "🔴", "high": "🟠", "medium": "🟡", "low": "🔵"}

    for i, tc in enumerate(test_cases, 1):
        tc_id = tc.get("id", f"TC-{i:03d}")
        feature = tc.get("feature", "Unknown")
        scenario = tc.get("scenario", "")
        severity = tc.get("severity", tc.get("priority", "medium")).lower()
        icon = severity_icons.get(severity, "⚪")
        tags = tc.get("tags", [])
        steps = tc.get("steps", [])

        lines.extend([
            f"### {icon} {tc_id} — {feature}",
            "",
            f"**Scenario**: {scenario}  ",
            f"**Severity**: `{severity}`  ",
        ])
        if tags:
            lines.append(f"**Tags**: {', '.join(f'`{t}`' for t in tags)}  ")
        if steps:
            lines.extend(["", "| Step | Action | Expected Result |", "|------|--------|-----------------|"])
            for step in steps:
                lines.append(
                    f"| {step.get('step_number', '')} | {step.get('action', '')} | {step.get('expected_result', '')} |"
                )
        lines.extend(["", "---", ""])

    cypress_paths = state.get("cypress_file_paths", [])
    if cypress_paths:
        lines.extend(["## 🌲 Generated Cypress Files", ""])
        for p in cypress_paths:
            lines.append(f"- `{Path(p).name}` — `{p}`")
        lines.append("")

    lines.extend(["---", "", f"*Report generated by QA-Web-Agent on {now}*"])
    return "\n".join(lines)


def _build_bug_report_md(state: QAState) -> str:
    """Generate a bug/failure report in Markdown."""
    url = state.get("url", "N/A")
    prd = state.get("project_description", "N/A")
    errors = state.get("errors", [])
    exec_history = state.get("execution_history", [])
    classified = state.get("classified_errors", [])
    kg = state.get("technical_overview", {})
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    lines = [
        "# 🐛 Bug Report",
        "",
        f"> **Generated**: {now}  ",
        f"> **Target URL**: [{url}]({url})  ",
        f"> **PRD**: {prd[:200]}{'…' if len(prd) > 200 else ''}",
        "",
        "---",
        "",
        "## 📊 Execution Summary",
        "",
        "| Attempt | Status | Passed | Failed | Total | Exit Code |",
        "|---------|--------|--------|--------|-------|-----------|",
    ]

    for run in exec_history:
        attempt = run.get("attempt", "?")
        status = run.get("status", "unknown")
        status_icon = "✅" if status == "pass" else "❌"
        lines.append(
            f"| {attempt} | {status_icon} {status} | {run.get('passed', 0)} "
            f"| {run.get('failed', 0)} | {run.get('total_tests', 0)} | {run.get('exit_code', '?')} |"
        )

    lines.extend(["", "---", ""])

    # App bugs from classify_errors
    app_bugs = [e for e in classified if e.get("type") == "app_bug"]
    test_code_bugs = [e for e in classified if e.get("type") == "test_code_error"]

    if app_bugs:
        lines.extend(["## 🔴 App Bugs (Real Defects)", ""])
        for i, bug in enumerate(app_bugs, 1):
            msg = bug.get("message", str(bug))
            lines.extend([
                f"### BUG-T{i:03d}: App Defect",
                "",
                f"- **Severity**: High",
                f"- **Category**: Application Bug",
                "- **Error Message**:",
                "  ```",
                f"  {msg}",
                "  ```",
                "- **Status**: Open",
                "",
            ])

    # Draft Jira tickets from technical_overview if generated
    jira_tickets = (kg or {}).get("jira_tickets", []) if kg else []
    if jira_tickets:
        lines.extend(["## 🎫 Jira Bug Tickets", ""])
        for ticket in jira_tickets:
            severity = ticket.get("severity", "Medium")
            lines.extend([
                f"### [{severity}] {ticket.get('title', 'Bug')}",
                "",
                f"{ticket.get('description', '')}",
                "",
                "**Steps to Reproduce:**",
            ])
            for step in ticket.get("steps_to_reproduce", []):
                lines.append(f"1. {step}")
            lines.extend([
                f"\n**Expected:** {ticket.get('expected', '')}",
                f"**Actual:** {ticket.get('actual', '')}",
                "",
            ])

    # Missing features
    missing = (kg or {}).get("missing_features", []) if kg else []
    if missing:
        lines.extend(["## ⚠️ Missing Features (PRD vs Live)", ""])
        for i, feat in enumerate(missing, 1):
            lines.extend([
                f"### BUG-M{i:03d}: Missing — {feat.get('feature', 'Unknown')}",
                "",
                "- **Severity**: High",
                "- **Category**: Missing Feature",
                f"- **PRD Reference**: {feat.get('prd_reference', 'N/A')}",
                "- **Status**: Open",
                "",
            ])

    # Persistent self-healing errors
    if errors:
        lines.extend(["## 🔄 Self-Healing Errors (Final State)", ""])
        for err in errors:
            lines.append(f"- `{err}`")
        lines.append("")

    if not app_bugs and not missing and not errors:
        lines.extend(["## ✅ No Bugs Found", "", "All tests passed successfully.", ""])

    risks = (kg or {}).get("risks", []) if kg else []
    recommendations = (kg or {}).get("recommendations", []) if kg else []
    if risks or recommendations:
        lines.extend(["---", "", "## 💡 Recommendations", ""])
        for r in risks:
            lines.append(f"- ⚠️ **Risk**: {r}")
        for r in recommendations:
            lines.append(f"- 💡 {r}")
        lines.append("")

    lines.extend(["---", "", f"*Bug report generated by QA-Web-Agent on {now}*"])
    return "\n".join(lines)


# ── Node functions ───────────────────────────────────────────


@traceable(name="aggregate_metrics", run_type="chain")
async def aggregate_metrics(state: QAState) -> dict:
    """Node 1 — Calculate pass/fail ratios from execution history."""
    exec_history = state.get("execution_history", [])
    classified = state.get("classified_errors", [])

    total_passed = sum(r.get("passed", 0) for r in exec_history if isinstance(r, dict))
    total_failed = sum(r.get("failed", 0) for r in exec_history if isinstance(r, dict))
    total_tests = total_passed + total_failed

    pass_rate_pct = round((total_passed / total_tests) * 100, 1) if total_tests > 0 else 0.0

    app_bug_count = sum(1 for e in classified if e.get("type") == "app_bug")
    test_code_error_count = sum(1 for e in classified if e.get("type") == "test_code_error")

    metrics = {
        "total_passed": total_passed,
        "total_failed": total_failed,
        "total_tests": total_tests,
        "pass_rate_pct": pass_rate_pct,
        "app_bug_count": app_bug_count,
        "test_code_error_count": test_code_error_count,
        "heal_attempts": state.get("heal_retry_count", 0),
    }

    logger.info(
        "Reporter / aggregate_metrics: %d/%d passed (%.1f%%), %d app bugs",
        total_passed,
        total_tests,
        pass_rate_pct,
        app_bug_count,
    )

    updated_overview = {**(state.get("technical_overview") or {}), "metrics": metrics}
    return {"technical_overview": updated_overview}


@traceable(name="draft_bug_tickets", run_type="chain")
async def draft_bug_tickets(state: QAState) -> dict:
    """Node 2 — LLM drafts Jira-style tickets for app_bug failures."""
    classified = state.get("classified_errors", [])
    app_bugs = [e for e in classified if e.get("type") == "app_bug"]

    if not app_bugs:
        logger.info("Reporter / draft_bug_tickets: no app bugs — skipping")
        return {}

    logger.info("Reporter / draft_bug_tickets: drafting %d tickets", len(app_bugs))

    kg = state.get("technical_overview", {})
    app_context = f"App: {(kg or {}).get('app_title', 'Unknown')} | Tech: {', '.join((kg or {}).get('tech_signals', []))}"

    result = await (_BUG_TICKET_PROMPT | _get_llm()).ainvoke(
        {
            "app_bugs": json.dumps(app_bugs, indent=2),
            "app_context": app_context,
        }
    )

    raw: str = result.content  # type: ignore[union-attr]
    try:
        cleaned = raw.strip()
        if cleaned.startswith("```"):
            cleaned = cleaned.split("\n", 1)[1].rsplit("```", 1)[0]
        tickets = json.loads(cleaned).get("tickets", [])
    except (json.JSONDecodeError, IndexError):
        logger.warning("Reporter / draft_bug_tickets: could not parse tickets")
        tickets = [{"title": "Parse error", "description": raw[:500]}]

    updated_overview = {**(state.get("technical_overview") or {}), "jira_tickets": tickets}
    return {"technical_overview": updated_overview}


@traceable(name="assemble_markdown", run_type="chain")
async def assemble_markdown(state: QAState) -> dict:
    """Node 3 — Write test_cases_report.md and bug_report.md, return paths + summary to state."""
    logger.info("Reporter / assemble_markdown: writing reports")

    tc_md = _build_test_cases_md(state)
    bug_md = _build_bug_report_md(state)

    tc_path_str, bug_path_str = await asyncio.to_thread(_write_reports, tc_md, bug_md)
    logger.info("Reporter / assemble_markdown: wrote %s and %s", tc_path_str, bug_path_str)

    # Build summary visible in LangSmith / /report endpoint
    kg = state.get("technical_overview") or {}
    metrics = kg.get("metrics", {})
    exec_history = state.get("execution_history", [])
    last_run = exec_history[-1] if exec_history and isinstance(exec_history[-1], dict) else {}

    report_summary = {
        "pass_rate_pct": metrics.get("pass_rate_pct", 0),
        "total_tests": metrics.get("total_tests", last_run.get("total_tests", 0)),
        "passed": metrics.get("total_passed", last_run.get("passed", 0)),
        "failed": metrics.get("total_failed", last_run.get("failed", 0)),
        "app_bugs": metrics.get("app_bug_count", 0),
        "test_code_errors": metrics.get("test_code_error_count", 0),
        "heal_attempts": state.get("heal_retry_count", 0),
        "report_files": [tc_path_str, bug_path_str],
    }

    return {
        "report_paths": [tc_path_str, bug_path_str],
        "report_summary": report_summary,
    }
