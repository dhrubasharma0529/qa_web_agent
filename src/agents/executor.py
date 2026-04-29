"""Executor Agent — Phase 4: Test Execution & Verification (V2 Cluster).

Four specialized nodes replace the V1 monolith:
    1. pre_flight_check  — clean old screenshots, validate spec files exist
    2. run_cypress       — subprocess npx cypress run, captures stdout
    3. classify_errors   — LLM classifies failures as test_code_error or app_bug
    4. heal_tests        — LLM rewrites broken spec files when test_code_error present
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
import sys
import threading
from pathlib import Path

from langchain_core.prompts import ChatPromptTemplate
from langchain_openai import ChatOpenAI
from langsmith import traceable

from src.config import config
from src.models.state import QAState

logger = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).resolve().parents[2]
CYPRESS_SCREENSHOTS_DIR = PROJECT_ROOT / "cypress" / "screenshots"
CYPRESS_RESULTS_DIR = PROJECT_ROOT / "cypress" / "results"

# ── LLM factory ─────────────────────────────────────────────

def _get_llm() -> ChatOpenAI:
    return ChatOpenAI(model=config.LLM_MODEL, temperature=0)


# ── Prompts ─────────────────────────────────────────────────

_CLASSIFY_PROMPT = ChatPromptTemplate.from_messages(
    [
        (
            "system",
            "You are a QA Engineer analysing Cypress test output.\n\n"
            "Classify each failing test line as ONE of:\n"
            '- `"test_code_error"` : The test code itself is broken (wrong selector, '
            "flawed assertion, timing issue, assertion that does not match the page type) — NOT an app defect.\n"
            '- `"app_bug"` : The application has a real defect (feature missing, '
            "wrong value, broken functionality).\n\n"
            "## Classification guidance\n"
            "Use the DOM snapshot to determine the page type, then apply these rules:\n"
            "- If the test expects a 'thank you/sent/success' message but the DOM shows a LOGIN form\n"
            "  (username+password inputs, no message textarea) → `test_code_error`.\n"
            "  Login success = URL change, not a thank-you message.\n"
            "- If the test expects `label[for='...']` but the DOM snapshot has NO `<label>` elements → `test_code_error`.\n"
            "- If the test expects `input:invalid` but the DOM shows custom JS error divs → `test_code_error`.\n"
            "- If the test expects a button to be `disabled` but the DOM shows it is always enabled → `test_code_error`.\n"
            "- If the test expects a selector that simply does not appear anywhere in the DOM → `test_code_error`.\n"
            "- If the test checks `cy.url().should('include', '404')` but the URL stays at the root\n"
            "  → `test_code_error`. URL-based 404 checks are wrong; the correct check is page content.\n"
            "- If the test expects `h2:contains('Thank You')` or similar success text on a contact form\n"
            "  but the DOM shows no such text → `test_code_error`. The test guessed the wrong text.\n"
            "- If the test asserts a SPECIFIC literal word/phrase like `cy.contains('Error')`,\n"
            "  `cy.contains('Not Found')`, `cy.contains('Success')`, `cy.contains('Welcome')`\n"
            "  after a navigation/click that lands on a page whose actual text is unknown\n"
            "  → `test_code_error`. The test guessed an arbitrary keyword the page may not use.\n"
            "  Real error/success pages use varied wording (`Error`, `404`, `Not Found`,\n"
            "  `Page doesn't exist`, `Sorry`, etc.) — a literal-string assertion is fragile.\n"
            "  The fix is a regex like `cy.contains(/error|not found|404|sorry/i)`, which\n"
            "  the healer can apply. Do NOT classify these as `app_bug` just because the\n"
            "  expected text was missing — the test's expectation was the bug.\n"
            "- If the test expects `[class*='error']` for form validation but the DOM shows no error\n"
            "  class elements → `test_code_error`. The site uses HTML5 or custom validation differently.\n"
            "- If the test expects `aria-label` on nav links that have visible text → `test_code_error`.\n"
            "  Visible link text IS accessible; aria-label is only required on icon-only controls.\n"
            "- If the test calls `.tab()`, `.or()`, or any method that does not exist in Cypress → `test_code_error`.\n"
            "- If the test asserts a URL path change on a SPA that uses hash routing → `test_code_error`.\n"
            "- If the test calls `cy.click()` on a subject containing N>1 elements → `test_code_error`.\n"
            "- If the test visits a route like `/about`, `/contact`, `/projects` that returns 404 on a SPA → `test_code_error`.\n"
            "- If the test asserts an element that simply does not appear in the DOM and is not\n"
            "  a known application feature (e.g. `a[href='#broken-link']`) → `test_code_error`.\n"
            "- If the test asserts `should('be.disabled')` on a button that the DOM shows as always enabled → `test_code_error`.\n"
            "- If the test visits a cross-origin URL without `cy.origin()` → `test_code_error`.\n"
            "- Only use `app_bug` when the feature SHOULD exist based on the page's clear purpose\n"
            "  (e.g. a checkout button missing from a shopping cart page).\n\n"
            "Each failure message is a multi-line block, often prefixed with "
            "`[spec: <filename>]`. Preserve the WHOLE block verbatim in `message` "
            "(do NOT shorten it to a single line) — downstream healing relies on "
            "the element HTML and reason text inside the block.\n\n"
            "Output strict JSON:\n"
            "{{\n"
            '  "classifications": [\n'
            '    {{"type": "test_code_error"|"app_bug", "message": "<full original block, verbatim>"}}\n'
            "  ]\n"
            "}}",
        ),
        (
            "human",
            "## Cypress stdout (tail)\n```\n{stdout_tail}\n```\n\n"
            "## Failure Messages\n```\n{failure_messages}\n```\n\n"
            "## DOM Snapshot (to determine page type and actual elements)\n"
            "```html\n{raw_dom}\n```",
        ),
    ]
)

_HEAL_PROMPT = ChatPromptTemplate.from_messages(
    [
        (
            "system",
            "You are a Senior SDET fixing broken Cypress spec files.\n"
            "Use CommonJS syntax only. Do NOT add `import`/`export` statements.\n"
            "Every `it()` block must keep at least one `should()` or `expect()` assertion.\n\n"
            "## Fixing process — always follow this order:\n"
            "1. Each error message starts with `[spec: <filename>]`. Only edit the spec\n"
            "   files that have errors; leave the others untouched (do NOT include them\n"
            "   in `fixed_specs`). Read the FULL multi-line block — the lines AFTER the\n"
            "   `CypressError:` / `AssertionError:` header contain the actual element\n"
            "   HTML and the reason (e.g. 'is not visible because parent has display:none').\n"
            "2. Identify WHICH category the error falls into (table below).\n"
            "3. Read the DOM snapshot to understand what elements actually exist.\n"
            "4. Determine the page/form type from the DOM:\n"
            "   - username + password inputs → LOGIN form\n"
            "   - message textarea → CONTACT/FEEDBACK form\n"
            "   - product listings, cart → E-COMMERCE flow\n"
            "5. Apply ONLY the fix for that category — do not apply unrelated changes.\n\n"
            "## Error → Fix Reference Table\n\n"
            "### A. Multi-element action\n"
            "Error: `cy.click() can only be called on a single element … contained N elements`\n"
            "Error: `cy.type() … contained N elements`\n"
            "Fix: Add `.first()` before the action: `cy.get('selector').first().click()`\n"
            "Use `{{ multiple: true }}` only when every matched element must be clicked.\n\n"
            "### B. cy.visit() failed / route not found\n"
            "Error: `cy.visit() failed trying to load`\n"
            "Error: `404` on a page object visit\n"
            "Fix: Check href values in the DOM.\n"
            "  - If hrefs contain `#section` anchors → SPA. Replace `cy.visit('/about')` with\n"
            "    `cy.visit('/')` (or just remove the extra visit — the page is already loaded).\n"
            "  - Replace page-object `visit('/about')` calls with `cy.visit('/')`.\n"
            "  - Replace `cy.url().should('include', '/about')` with `cy.get('#about').should('exist')`.\n\n"
            "### C. Element not found / timeout\n"
            "Error: `Timed out retrying … Expected to find element: 'X'`\n"
            "Error: `cy.get() failed — no elements found`\n"
            "Fix: Derive the correct selector from the DOM snapshot — never guess.\n"
            "  - If the element simply does not exist (e.g. `a[href=\"#broken-link\"]`),\n"
            "    replace the test with an assertion on elements that DO exist, or use `it.skip()`.\n"
            "  - If content loads asynchronously, increase timeout:\n"
            "    `cy.get('selector', {{ timeout: 15000 }}).should('be.visible')`\n\n"
            "### D. Method does not exist (.tab, .or, .spread, etc.)\n"
            "Error: `cy.get(…).focus(…).tab is not a function`\n"
            "Error: `.or is not a function`\n"
            "Error: `X is not a function`\n"
            "Fix for `.tab()`: Replace with per-element focus assertions:\n"
            "  `cy.get('input[name=\"name\"]').focus().should('be.focused')`\n"
            "  `cy.get('input[name=\"email\"]').focus().should('be.focused')`\n"
            "  Each element must focus and assert itself — focusing A does NOT make B focused.\n"
            "Fix for `.or()`: Use combined selector `cy.get('A, B').should('have.length.gte', 1)`\n"
            "  or chain with `.and()`: `cy.get('a').should('be.visible').and('have.attr', 'href')`\n\n"
            "### E. Element not interactable (not visible / covered / animating / off-screen)\n"
            "Match ANY of these wordings as Category E — they all mean the same thing:\n"
            "- `cy.click() failed because the element cannot be interacted with`\n"
            "- `cy.click() failed because this element ... is being covered by another element`\n"
            "- `element is not visible`\n"
            "- `element is currently animating`\n"
            "- `element is fixed and being covered`\n"
            "- `element is hidden by an overlay / modal / banner / tour`\n\n"
            "**CRITICAL — the click line itself MUST be modified.** Adding a `beforeEach`\n"
            "alone is NOT a fix. The same `cy.get(...).click()` will fail again because\n"
            "the cover often re-appears or was never dismissable in the first place.\n\n"
            "## Decide based on WHAT the covering element is\n\n"
            "Read the error block carefully — it shows the covering element's tag, id\n"
            "and class. Pick ONE of these strategies:\n\n"
            "**Strategy 1 — Force-click (use this for VISUAL-ONLY overlays):**\n"
            "Apply when the covering element is ANY of these:\n"
            "- A `<canvas>` element (canvas overlays don't capture clicks anyway)\n"
            "- An `<svg>` element used as a backdrop\n"
            "- id/class contains: `Disabled`, `DisabledArea`, `Backdrop`, `Spotlight`,\n"
            "  `Mask`, `Veil`, `Dim`, `Scrim`, `Highlight`, `TourTip` (the tip area\n"
            "  itself, not a banner)\n"
            "- The element has `pointer-events: none` style\n"
            "- A full-viewport overlay with no visible close affordance in the DOM\n"
            "Fix: change EVERY `.click()` on the affected target to `.click({{ force: true }})`.\n"
            "This is the correct fix for visual-only dimming layers — they exist to\n"
            "highlight things, not to block real interaction.\n\n"
            "**Strategy 2 — Dismiss the cover first (use this for INTERACTIVE banners):**\n"
            "Apply when the covering element is a banner/modal that has a clear close\n"
            "control visible in the DOM snapshot, e.g.:\n"
            "- Cookie consent: `[aria-label=\"Accept cookies\"]`, `.cookie-banner button`\n"
            "- Modal dialogs with a close button: `[aria-label=\"Close\"]`, `.modal-close`\n"
            "- Newsletter/popup with an `×` button selectable in the DOM\n"
            "Add a `beforeEach` that clicks ONLY selectors that actually exist in the\n"
            "DOM snapshot:\n"
            "```\n"
            "beforeEach(() => {{\n"
            "  cy.visit('/');\n"
            "  cy.get('body').then($b => {{\n"
            "    const sels = [/* only selectors verified to exist in the DOM */];\n"
            "    sels.forEach(s => {{\n"
            "      if ($b.find(s).length) cy.get(s).first().click({{ force: true }});\n"
            "    }});\n"
            "  }});\n"
            "}});\n"
            "```\n"
            "Then ALSO add `{{ force: true }}` to the action click — banners can re-appear.\n\n"
            "**Strategy 3 — Off-screen / animating (less common):**\n"
            "If the element is genuinely off-screen, prepend `.scrollIntoView()`.\n"
            "If it is mid-animation, wait: `.should('not.have.class', 'animating')`.\n\n"
            "When in doubt between Strategy 1 and 2: **prefer Strategy 1 (force-click)**.\n"
            "It is the safer, more reliable fix for any 'covered by' error and never\n"
            "introduces new failure modes.\n\n"
            "### F. Subject detached from DOM\n"
            "Error: `CypressError: cy… failed because the element has been detached`\n"
            "Fix: Re-query the element after the action that caused re-render:\n"
            "  `cy.get('selector').click(); cy.get('selector').should('...')`  (two separate gets)\n\n"
            "### G. SPA navigation assertions\n"
            "Error: `cy.url().should('include', '/about')` times out on SPA\n"
            "Fix: Assert visible section instead:\n"
            "  `cy.get('a[href=\"#about\"]').first().click(); cy.get('#about').should('be.visible')`\n"
            "  Never assert URL path changes on a hash-routing SPA.\n\n"
            "### H. 404 / broken-link URL check\n"
            "Error: `cy.url().should('include', '404')` never matches\n"
            "Error: `Expected to find element: 'a[href=\"#broken-link\"]'`\n"
            "Fix: Replace with content-based check:\n"
            "  `cy.contains(/404|not found|page doesn't exist/i).should('exist')`\n"
            "  If the site always redirects, use `it.skip('site redirects broken URLs to homepage')`.\n\n"
            "### I. Form feedback assertions\n"
            "LOGIN success: `cy.url().should('not.include', '/login')` or include actual destination path.\n"
            "LOGIN failure: search DOM for `[data-test='error']`, `[class*='error']` — use exact selector.\n"
            "CONTACT success: assert button disabled or inputs cleared; NEVER guess success text.\n"
            "Validation (empty submit): try `cy.get('input:invalid').should('exist')` first,\n"
            "  then `cy.get('[data-error]').should('exist')`, then assert URL unchanged.\n\n"
            "### J. Accessibility assertions\n"
            "Nav links with visible text are already accessible — do NOT assert `aria-label` on them.\n"
            "Replace `should('have.attr', 'aria-label')` on nav links with:\n"
            "  `cy.get('a.nav-link').each($el => {{ expect($el.text().trim()).to.not.be.empty }})`\n"
            "Only assert `aria-label` on icon-only controls (no visible text).\n\n"
            "### K. Cross-browser / IE11 tests\n"
            "Replace entire `it()` body with:\n"
            "  `it.skip('cross-browser testing requires a real multi-browser setup', () => {{}});`\n\n"
            "### L. Cross-origin navigation\n"
            "Error: `cy.visit() failed … attempting to visit a different origin`\n"
            "Fix: Wrap cross-origin commands:\n"
            "  `cy.origin('https://otherdomain.com', () => {{ cy.get('...').should('...') }})`\n\n"
            "### M. Button disabled assertion on always-enabled button\n"
            "Error: `expected button to be disabled`\n"
            "Fix: Only assert `should('be.disabled')` if DOM shows a `disabled` attribute.\n"
            "If the button is always enabled, assert the expected POST-click behaviour instead.\n\n"
            "Output strict JSON:\n"
            "{{\n"
            '  "fixed_specs": [\n'
            '    {{"filename": "foo.cy.js", "code": "…full fixed JS…"}}\n'
            "  ]\n"
            "}}",
        ),
        (
            "human",
            "## Test-Code Errors to Fix\n```\n{error_messages}\n```\n\n"
            "## Current Spec Files\n{spec_contents}\n\n"
            "## DOM Snapshot (derive ALL selectors and page type from here)\n"
            "```html\n{raw_dom}\n```",
        ),
    ]
)


# ── Failure-block extraction ────────────────────────────────
#
# Cypress prints failures in multi-line blocks. Example:
#
#     Running:  someSpec.cy.js
#     ...
#       1) Suite name
#            test title:
#          CypressError: cy.click() failed because this element:
#
#            <a href="..." class="...">Send</a>
#
#          is not visible because its parent <nav#sq-nav> has CSS …
#
#       2) Suite name
#          ...
#
#     (Screenshots)
#
# We must capture the WHOLE block (header + element HTML + reason + stack
# preview) and tag it with the spec filename, so the healer knows which
# file to rewrite and the classifier can see the actual element/reason
# rather than just a truncated header.

_FAILURE_NUM_RE = re.compile(r"^\s+(\d+)\)\s+\S")
_RUNNING_SPEC_RE = re.compile(r"\s*Running:\s+(.+\.cy\.js)")
_FAILURES_HEADER_RE = re.compile(r"\(Failures\)|^\s*\d+\s+failing", re.IGNORECASE)
_END_OF_FAILURES_RE = re.compile(
    r"\s*(\(Screenshots\)|\(Run Finished\)|\(Results\)|={4,}|-{4,})"
)

_MAX_BLOCK_CHARS = 2500     # per-failure cap — leaves room for many blocks
_MAX_BLOCKS = 12            # cap total failures we forward to the LLM


def _extract_failure_messages(stdout: str, stderr: str) -> list[str]:
    """Extract complete multi-line Cypress failure blocks, tagged with spec file.

    Each returned string is a self-contained failure block:
        [spec: foo.cy.js]
        1) Suite name
             test title:
           CypressError: cy.click() failed because this element:

             <a href="..." class="...">Send</a>

           is not visible because its parent <nav#sq-nav> ...

    The previous line-by-line filter cut off at the first blank line, which
    discarded the element HTML and the human-readable reason — exactly the
    fields the healer needs to actually fix a broken selector or assertion.
    """
    blocks: list[str] = []
    current_spec: str = ""
    current_block: list[str] = []
    in_failures = False

    def _flush() -> None:
        if not current_block:
            return
        text = "\n".join(current_block).rstrip()
        if not text:
            current_block.clear()
            return
        tagged = f"[spec: {current_spec}]\n{text}" if current_spec else text
        if len(tagged) > _MAX_BLOCK_CHARS:
            tagged = tagged[:_MAX_BLOCK_CHARS] + "\n…[truncated]"
        blocks.append(tagged)
        current_block.clear()

    for line in stdout.splitlines():
        m_spec = _RUNNING_SPEC_RE.match(line)
        if m_spec:
            _flush()
            current_spec = m_spec.group(1).strip()
            in_failures = False
            continue

        if _FAILURES_HEADER_RE.search(line):
            _flush()
            in_failures = True
            continue

        if in_failures and _END_OF_FAILURES_RE.match(line):
            _flush()
            in_failures = False
            continue

        if in_failures and _FAILURE_NUM_RE.match(line):
            _flush()
            current_block.append(line.rstrip())
            continue

        if in_failures and current_block:
            current_block.append(line.rstrip())

    _flush()

    # Fallback: if Cypress crashed before any spec ran, surface stderr so the
    # caller still sees something actionable instead of an empty list.
    if not blocks:
        stderr_clean = stderr.strip()
        if stderr_clean:
            blocks.append(f"[stderr]\n{stderr_clean[:_MAX_BLOCK_CHARS]}")

    return blocks[:_MAX_BLOCKS]


# ── Sync I/O helpers (wrapped with asyncio.to_thread at call sites) ─────────

def _clean_screenshots() -> None:
    if CYPRESS_SCREENSHOTS_DIR.exists():
        for p in CYPRESS_SCREENSHOTS_DIR.rglob("*.png"):
            p.unlink()


def _check_missing_specs(spec_files: list[str]) -> list[str]:
    return [p for p in spec_files if not Path(p).exists()]


def _get_screenshot_paths() -> list[str]:
    if not CYPRESS_SCREENSHOTS_DIR.exists():
        return []
    return [str(p) for p in CYPRESS_SCREENSHOTS_DIR.rglob("*.png")]


# ── Background ProactorEventLoop for subprocess on Windows ──────────────────
# asyncio.create_subprocess_exec requires ProactorEventLoop on Windows.
# langgraph dev uses SelectorEventLoop, so we maintain a background thread.

_bg_proactor_loop: asyncio.AbstractEventLoop | None = None
_bg_proactor_lock = threading.Lock()


def _get_bg_proactor_loop() -> asyncio.AbstractEventLoop:
    global _bg_proactor_loop
    if _bg_proactor_loop is not None and _bg_proactor_loop.is_running():
        return _bg_proactor_loop
    with _bg_proactor_lock:
        if _bg_proactor_loop is not None and _bg_proactor_loop.is_running():
            return _bg_proactor_loop
        ready = threading.Event()
        holder: dict = {}

        def _run() -> None:
            lp = asyncio.ProactorEventLoop()
            asyncio.set_event_loop(lp)
            holder["lp"] = lp
            ready.set()
            lp.run_forever()

        threading.Thread(target=_run, daemon=True, name="cypress-proactor").start()
        ready.wait(timeout=10)
        _bg_proactor_loop = holder["lp"]
    return _bg_proactor_loop


async def _exec_cypress_impl(cypress_args: list[str], cwd: str, timeout: int) -> tuple[bytes, bytes, int]:
    proc = await asyncio.create_subprocess_exec(
        *cypress_args,
        cwd=cwd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    try:
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout)
    except asyncio.TimeoutError:
        proc.kill()
        await proc.wait()
        raise
    return stdout, stderr, proc.returncode


async def _exec_cypress(cypress_args: list[str], cwd: str, timeout: int) -> tuple[bytes, bytes, int]:
    """Dispatch cypress subprocess. Routes to background ProactorEventLoop on Windows SelectorEventLoop."""
    needs_bg = sys.platform == "win32" and not isinstance(
        asyncio.get_running_loop(), asyncio.ProactorEventLoop
    )
    coro = _exec_cypress_impl(cypress_args, cwd, timeout)
    if needs_bg:
        return await asyncio.wrap_future(
            asyncio.run_coroutine_threadsafe(coro, _get_bg_proactor_loop())
        )
    return await coro


def _read_spec_contents(spec_files: list[str]) -> str:
    parts = []
    for sp in spec_files:
        p = Path(sp)
        if p.exists():
            code = p.read_text(encoding="utf-8")
            parts.append(f"### {p.name}\n```js\n{code}\n```")
    return "\n\n".join(parts) or "(no spec files found)"


# ── Node functions ───────────────────────────────────────────


@traceable(name="pre_flight_check", run_type="tool")
async def pre_flight_check(state: QAState) -> dict:
    """Node 1 — Clean old screenshots and validate spec files exist."""
    logger.info("Executor / pre_flight_check: cleaning screenshots")

    # Remove old screenshots
    await asyncio.to_thread(_clean_screenshots)
    logger.info("Executor / pre_flight_check: removed old screenshots")

    # Validate spec files exist
    generated_paths = state.get("cypress_file_paths", [])
    spec_files = [p for p in generated_paths if p.endswith(".cy.js")]

    if not spec_files:
        msg = "pre_flight_check: no Cypress spec files found — nothing to run"
        logger.error(msg)
        return {"errors": [msg]}

    missing = await asyncio.to_thread(_check_missing_specs, spec_files)
    if missing:
        msg = f"pre_flight_check: missing spec files: {missing}"
        logger.error(msg)
        return {"errors": [msg]}

    logger.info("Executor / pre_flight_check: %d spec files validated", len(spec_files))
    return {}


@traceable(name="run_cypress", run_type="tool")
async def run_cypress(state: QAState) -> dict:
    """Node 2 — Execute Cypress tests and capture stdout."""
    retry_count = state.get("retry_count", 0)
    logger.info("Executor / run_cypress: running tests (attempt #%d)", retry_count + 1)

    url = state.get("url", "").rstrip("/")
    generated_paths = state.get("cypress_file_paths", [])
    # Deduplicate by filename — Annotated[list, add] can accumulate duplicates across heals
    seen: set[str] = set()
    spec_files: list[str] = []
    for p in generated_paths:
        if p.endswith(".cy.js") and Path(p).name not in seen:
            seen.add(Path(p).name)
            spec_files.append(p)
    spec_pattern = ",".join(
        str(Path(p).relative_to(PROJECT_ROOT)).replace("\\", "/")
        for p in spec_files
    )

    npx = "npx.cmd" if sys.platform == "win32" else "npx"

    cypress_config = f"screenshotsFolder={CYPRESS_SCREENSHOTS_DIR}"
    if url:
        cypress_config += f",baseUrl={url}"
    cypress_args = [
        npx, "cypress", "run",
        "--headed" if config.CYPRESS_HEADED else "--headless",
        "--spec", spec_pattern,
        "--reporter", "spec",
        "--config", cypress_config,
    ]
    if config.CYPRESS_STEP_DELAY_MS > 0:
        cypress_args += ["--env", f"stepDelay={config.CYPRESS_STEP_DELAY_MS}"]

    try:
        stdout_bytes, stderr_bytes, returncode = await _exec_cypress(
            cypress_args, str(PROJECT_ROOT), config.CYPRESS_TIMEOUT_SECONDS
        )
    except FileNotFoundError:
        msg = "npx/cypress not found — is Node.js + Cypress installed?"
        logger.error(msg)
        return {
            "errors": [msg],
            "execution_history": [{"attempt": retry_count + 1, "status": "error", "exit_code": None, "passed": 0, "failed": 0, "total_tests": 0, "detail": msg}],
            "retry_count": retry_count + 1,
        }
    except asyncio.TimeoutError:
        msg = f"Cypress timed out after {config.CYPRESS_TIMEOUT_SECONDS}s"
        logger.error(msg)
        return {
            "errors": [msg],
            "execution_history": [{"attempt": retry_count + 1, "status": "timeout", "exit_code": None, "passed": 0, "failed": 0, "total_tests": 0, "detail": msg}],
            "retry_count": retry_count + 1,
        }

    stdout = stdout_bytes.decode(errors="replace")
    stderr = stderr_bytes.decode(errors="replace")

    # SUM all per-spec matches. Cypress prints "N passing" / "N failing" once per
    # spec file and never prints a combined total in text form — only a table.
    # Taking [-1] gives only the last spec's count; summing gives the run total.
    passing_matches = re.findall(r"(\d+)\s+passing", stdout)
    failing_matches = re.findall(r"(\d+)\s+failing", stdout)
    pending_matches = re.findall(r"(\d+)\s+pending", stdout)

    passed = sum(int(m) for m in passing_matches)
    failed = sum(int(m) for m in failing_matches)
    pending = sum(int(m) for m in pending_matches)

    run_result: dict = {
        "attempt": retry_count + 1,
        "exit_code": returncode,
        "stdout_tail": stdout[-3000:],
        "stderr_tail": stderr[-2000:],
        "total_tests": passed + failed + pending,
        "passed": passed,
        "failed": failed,
        "pending": pending,
        "status": "pass" if (returncode == 0 and failed == 0) else "fail",
        "failure_messages": _extract_failure_messages(stdout, stderr),
        "screenshots": await asyncio.to_thread(_get_screenshot_paths),
    }

    logger.info(
        "Executor / run_cypress: %s — %d passed, %d failed",
        run_result["status"],
        passed,
        failed,
    )

    return {
        "execution_history": [run_result],
        "retry_count": retry_count + 1,
    }


@traceable(name="classify_errors", run_type="chain")
async def classify_errors(state: QAState) -> dict:
    """Node 3 — LLM classifies failure lines as test_code_error or app_bug."""
    exec_history = state.get("execution_history", [])
    if not exec_history:
        return {"classified_errors": []}

    last_run = exec_history[-1] if isinstance(exec_history[-1], dict) else {}
    stdout_tail = last_run.get("stdout_tail", "")
    failure_messages = last_run.get("failure_messages", [])

    if not failure_messages:
        logger.info("Executor / classify_errors: no failure messages to classify")
        return {"classified_errors": []}

    logger.info(
        "Executor / classify_errors: classifying %d failure messages",
        len(failure_messages),
    )

    raw_dom = state.get("raw_dom", "") or ""
    result = await (_CLASSIFY_PROMPT | _get_llm()).ainvoke(
        {
            "stdout_tail": stdout_tail[-2000:],
            "failure_messages": "\n".join(failure_messages),
            "raw_dom": raw_dom[:4000],
        }
    )

    raw: str = result.content  # type: ignore[union-attr]
    try:
        cleaned = raw.strip()
        if cleaned.startswith("```"):
            cleaned = cleaned.split("\n", 1)[1].rsplit("```", 1)[0]
        parsed = json.loads(cleaned)
        classifications = parsed.get("classifications", [])
    except (json.JSONDecodeError, IndexError):
        logger.warning("Executor / classify_errors: could not parse LLM response")
        # Fallback: treat everything as test_code_error for safe retrying
        classifications = [
            {"type": "test_code_error", "message": m}
            for m in failure_messages
        ]

    logger.info(
        "Executor / classify_errors: %d test_code_error, %d app_bug",
        sum(1 for c in classifications if c.get("type") == "test_code_error"),
        sum(1 for c in classifications if c.get("type") == "app_bug"),
    )
    return {"classified_errors": classifications}


@traceable(name="heal_tests", run_type="chain")
async def heal_tests(state: QAState) -> dict:
    """Node 4 — LLM rewrites spec files for test_code_error classified failures."""
    classified = state.get("classified_errors", [])
    test_code_errors = [e for e in classified if e.get("type") == "test_code_error"]

    if not test_code_errors:
        logger.info("Executor / heal_tests: no test_code_errors — nothing to heal")
        return {}

    heal_count = state.get("heal_retry_count", 0)
    logger.info(
        "Executor / heal_tests: healing %d test-code error(s) (heal attempt #%d)",
        len(test_code_errors),
        heal_count + 1,
    )

    # Read current spec files — deduplicate paths before reading
    generated_paths = state.get("cypress_file_paths", [])
    seen_names: set[str] = set()
    spec_files: list[str] = []
    for p in generated_paths:
        if p.endswith(".cy.js") and Path(p).name not in seen_names:
            seen_names.add(Path(p).name)
            spec_files.append(p)

    spec_contents = await asyncio.to_thread(_read_spec_contents, spec_files)
    error_messages = "\n".join(e.get("message", str(e)) for e in test_code_errors)
    raw_dom = state.get("raw_dom", "")

    result = await (_HEAL_PROMPT | _get_llm()).ainvoke(
        {
            "error_messages": error_messages,
            "spec_contents": spec_contents,
            "raw_dom": raw_dom[:6000] if raw_dom else "(not available)",
        }
    )

    raw: str = result.content  # type: ignore[union-attr]
    try:
        cleaned = raw.strip()
        if cleaned.startswith("```"):
            cleaned = cleaned.split("\n", 1)[1].rsplit("```", 1)[0]
        healed = json.loads(cleaned)
    except (json.JSONDecodeError, IndexError):
        logger.error("Executor / heal_tests: could not parse healed specs")
        return {"heal_retry_count": heal_count + 1}

    # Overwrite spec files with healed versions — do NOT return cypress_file_paths
    # (it uses Annotated[list, add] and would duplicate on every heal loop)
    from src.agents.sdet import CYPRESS_E2E_DIR, _write_file  # local import to avoid circular

    fixed_specs = healed.get("fixed_specs", [])
    for fixed in fixed_specs:
        await asyncio.to_thread(_write_file, CYPRESS_E2E_DIR, fixed["filename"], fixed["code"])

    logger.info("Executor / heal_tests: healed %d spec file(s)", len(fixed_specs))
    return {"heal_retry_count": heal_count + 1}
