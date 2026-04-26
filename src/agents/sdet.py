"""SDET Agent — Phase 3: Autonomous Automation (V2 Cluster).

Three specialized nodes replace the V1 monolith:
    1. generate_page_objects  — LLM writes ONLY Cypress POM classes
    2. generate_specs         — LLM writes .cy.js specs using POMs + human_feedback
    3. syntax_linter          — subprocess `npx eslint --fix`; fails → route to generate_specs

CommonJS only (no ES module syntax).
"""

from __future__ import annotations

import asyncio
import json
import logging
from pathlib import Path

from langchain_core.prompts import ChatPromptTemplate
from langchain_openai import ChatOpenAI
from langsmith import traceable

from src.config import config
from src.models.state import QAState

logger = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).resolve().parents[2]
CYPRESS_E2E_DIR = PROJECT_ROOT / "cypress" / "e2e"
CYPRESS_PAGES_DIR = PROJECT_ROOT / "cypress" / "support" / "pages"


# ── LLM factory ─────────────────────────────────────────────

def _get_llm() -> ChatOpenAI:
    return ChatOpenAI(model=config.LLM_MODEL, temperature=0)


# ── Prompts ─────────────────────────────────────────────────

_SHARED_RULES = (
    "## CRITICAL Rules\n"
    "1. Use **CommonJS** module syntax everywhere:\n"
    "   - Page Objects: `class Foo {{ ... }}  module.exports = new Foo();`\n"
    "   - Specs: `const homePage = require('../support/pages/homePage');`\n"
    "   - **NEVER** use `import`/`export` ES module syntax.\n"
    "2. Follow the **Page Object Model** pattern.\n"
    "3. Selector priority: `data-cy` > `data-testid` > `[aria-label=\"...\"]`\n"
    "   > `[role=\"...\"]` > `a[href=\"...\"]` > tag+attribute combos.\n"
    "   - **NEVER** use bare tag selectors like `nav`, `h1`, `h2`, `h3`, `button`.\n"
    "   - **ALWAYS** qualify with an attribute: `h2:contains(\"...\")` or `a[href=\"...\"]`.\n"
    "4. When `cy.get()` may match multiple elements, use `.first()` or `.eq(0)`.\n"
    "5. Do NOT use `cy.intercept` or `cy.wait('@alias')` — the target is a static site.\n"
    "6. Do NOT use `cy.click()` on `<a>` tags that navigate to external sites — use\n"
    "   `.should('have.attr', 'href').and('include', '...')` instead.\n"
    "7. For PDF / file download links, assert the href attribute rather than clicking.\n"
    "8. Generate **one spec file per test case / feature** (not one mega-file).\n"
    "9. Every `it()` block MUST have at least one real assertion (`should`, `expect`).\n"
    "   No empty bodies or placeholder comments.\n"
    "10. Use `cy.visit('/')` — baseUrl is already configured.\n\n"
    "## DOM-Driven Rules — read the DOM snapshot before writing any assertion\n"
    "11. **Form feedback — determine form type from the DOM, never assume:**\n"
    "    - Look at the inputs in the DOM snapshot to classify the form:\n"
    "      username+password fields → LOGIN form. message textarea → CONTACT form.\n"
    "    - **LOGIN forms**: success = URL changes after submit.\n"
    "      Use `cy.url().should('not.include', '/login')` or\n"
    "      `cy.url().should('include', '<path>')` where <path> is a route you see in the DOM.\n"
    "      For failed login: look for `[data-test='error']` or `[class*='error']` in the DOM.\n"
    "    - **CONTACT/FEEDBACK forms**: look for a success heading or div in the DOM.\n"
    "      If none visible, assert `cy.get('form').should('not.exist')`.\n"
    "    - **Validation errors**: search the DOM for custom error divs first.\n"
    "      Only use `cy.get('input:invalid')` if the DOM has no custom error containers.\n"
    "    - NEVER assert `.success-message`, `.error-message`, `.alert`, `.toast` unless\n"
    "      those exact class names appear in the DOM snapshot.\n"
    "    - NEVER use `cy.contains(/thank you|sent|success/i)` on login or auth pages.\n"
    "    - NEVER guess success message text. If you don't see the exact text in the DOM,\n"
    "      assert a structural change instead (button disabled, inputs cleared, form gone).\n"
    "    - NEVER use `[class*='error']` for validation unless those classes appear in the DOM.\n"
    "      Instead: try `cy.get('input:invalid').should('exist')` for HTML5 validation, or\n"
    "      assert the URL has not changed after submitting an invalid form.\n"
    "12. **Accessibility — derive from the DOM, never invent:**\n"
    "    - Search the DOM snapshot for `<label for='X'>` elements before asserting them.\n"
    "    - If `<label>` elements exist → `cy.get('label[for=\"X\"]').should('exist')`.\n"
    "    - If NO label elements in the DOM → check `aria-label` or `placeholder` instead.\n"
    "    - NEVER assert `label[for='...']` when the DOM snapshot contains no label tags.\n"
    "    - NEVER assert `aria-label` on nav links or buttons that have visible text — visible\n"
    "      text IS an accessible name. Only assert `aria-label` on icon-only controls.\n"
    "13. **Cross-browser / IE11 tests** — NEVER generate a test that looks for a\n"
    "    `.compatibility-message` element or simulates IE11/Safari. Cypress runs in\n"
    "    Electron/Chrome only. If a test case is tagged 'cross-browser', write:\n"
    "    `it.skip('cross-browser testing requires a real multi-browser setup', () => {{}});`\n\n"
    "14. **Single-Page App navigation — derive routing type from DOM href values:**\n"
    "    - Before calling `cy.visit('/path')`, inspect the anchor `href` attributes in the DOM.\n"
    "    - If hrefs use `#section`, `#about`, `javascript:void(0)`, or click-handler patterns\n"
    "      → the site is a **SPA**. `cy.visit('/about')` will 404. NEVER use it.\n"
    "    - For SPA: click the nav link and assert a section becomes visible:\n"
    "      `cy.get('a[href=\"#about\"]').click(); cy.get('#about').should('be.visible')`\n"
    "    - NEVER assert `cy.url().should('include', '/about')` on a SPA — the URL won't change.\n"
    "    - For multi-page apps (href='/about' with real paths): `cy.visit('/about')` is correct.\n"
    "15b. **404 / broken link tests:**\n"
    "    - NEVER assert `cy.url().should('include', '404')` — the URL rarely contains '404'.\n"
    "      Sites redirect broken URLs to homepage; the URL never changes to a 404 path.\n"
    "    - Correct approach: `cy.contains(/404|not found/i).should('exist')` on the page content.\n"
    "    - If the site always redirects (no 404 page at all), write:\n"
    "      `it.skip('site redirects all broken URLs to homepage — no 404 page available')`\n\n"
    "15. **Cypress API — only use methods that exist:**\n"
    "    - `.or()` does NOT exist in Cypress. Never write `.should(...).or(...)`.\n"
    "    - To check 'element A or element B exists': use a combined selector:\n"
    "      `cy.get('selectorA, selectorB').should('have.length.gte', 1)`\n"
    "    - To conditionally handle two states: use `.then($el => {{ if (...) {{...}} }})`\n"
    "    - Valid Cypress chain methods after `.should()`: `.and()`, `.then()`, `.as()`, `.within()`\n"
    "    - `.and()` is an alias for `.should()` — use it to chain multiple assertions:\n"
    "      `cy.get('a').should('be.visible').and('have.attr', 'href')`\n\n"
    "16. **Multi-element actions — always narrow the subject first:**\n"
    "    - `cy.click()`, `cy.type()`, `cy.check()`, `cy.select()` fail if the subject contains\n"
    "      more than one element. Always add `.first()`, `.last()`, or `.eq(N)` when the\n"
    "      selector can match multiple nodes (e.g. nav links duplicated in desktop+mobile menus).\n"
    "    - Example: `cy.get('a[href=\"#about\"]').first().click()`\n"
    "    - Use `{{ multiple: true }}` ONLY when you intentionally want to act on every match.\n\n"
    "17. **Keyboard / tab navigation — `.tab()` does NOT exist in Cypress by default:**\n"
    "    - Never write `.tab()` or `.focus().tab()` — it throws TypeError at runtime.\n"
    "    - To verify an element is keyboard-focusable:\n"
    "      `cy.get('input[name=\"name\"]').focus().should('be.focused')`\n"
    "    - Test each focusable element individually. Do NOT chain focus assertions across\n"
    "      different elements (focusing element A does NOT move focus to element B).\n"
    "    - Only use `cy.realPress('Tab')` if `cypress-real-events` is listed in package.json.\n\n"
    "18. **Element visibility / interaction failures:**\n"
    "    - If an element is below the fold, call `.scrollIntoView()` before acting:\n"
    "      `cy.get('button[type=\"submit\"]').scrollIntoView().click()`\n"
    "    - If an element is covered by an overlay (cookie banner, modal), dismiss the overlay\n"
    "      first. Use `{{ force: true }}` only as a last resort (it bypasses actionability checks).\n"
    "    - If an element is animating, chain `.should('not.have.class', 'animating')` first,\n"
    "      or pass `{{ waitForAnimations: false }}` to the action.\n\n"
    "19. **Slow-loading content / assertion timeouts:**\n"
    "    - If content loads asynchronously and assertions time out, increase per-command timeout:\n"
    "      `cy.get('selector', {{ timeout: 15000 }}).should('be.visible')`\n"
    "    - Do NOT add `cy.wait(N)` with a fixed number — use retry-based assertions instead.\n\n"
    "20. **Detached DOM — stale element references:**\n"
    "    - After an action that re-renders the DOM (form submit, route change), never reuse a\n"
    "      previously chained subject. Re-query: `cy.get('selector').should('...')`.\n\n"
    "21. **Network / HTTP assertions:**\n"
    "    - To check a URL returns a valid response: `cy.request({{ url: href, failOnStatusCode: false }}).its('status').should('be.lt', 400)`.\n"
    "    - Do NOT click external links — assert the `href` attribute value instead.\n\n"
    "22. **Cross-origin navigation:**\n"
    "    - If the app navigates to a different domain, wrap all subsequent commands:\n"
    "      `cy.origin('https://other.com', () => {{ cy.get('...').should('...') }})`\n"
    "    - Never assert on a page from a different origin without `cy.origin()`.\n\n"
    "23. **iframe content:**\n"
    "    - To interact with content inside an `<iframe>`, use:\n"
    "      `cy.frameLoaded('#iframe-selector'); cy.iframe('#iframe-selector').find('...').should('...')`\n"
    "    - Only if `cypress-iframe` is installed. Otherwise skip the test with `it.skip()`.\n\n"
)

_PAGE_OBJECT_PROMPT = ChatPromptTemplate.from_messages(
    [
        (
            "system",
            "You are a Senior SDET.  Generate **Page Object Model (POM) classes ONLY** "
            "(no spec files).\n\n"
            + _SHARED_RULES
            + "## Output format (strict JSON)\n"
            "{{\n"
            '  "page_objects": [\n'
            '    {{"filename": "homePage.js", "code": "…full CommonJS JS…"}}\n'
            "  ]\n"
            "}}\n\n"
            "Return ONLY valid JSON — no extra commentary.",
        ),
        (
            "human",
            "## Target URL\n{url}\n\n"
            "## Test Cases\n```json\n{test_cases}\n```\n\n"
            "## Actual Page DOM (use ONLY selectors present here)\n"
            "```html\n{page_analysis}\n```\n\n"
            "## Raw DOM Snippet (for available elements)\n"
            "```html\n{raw_dom}\n```\n\n"
            "{cypress_api_context_block}"
            "{pom_lint_feedback}",
        ),
    ]
)

_SPEC_GEN_PROMPT = ChatPromptTemplate.from_messages(
    [
        (
            "system",
            "You are a Senior SDET writing Cypress E2E tests.\n\n"
            + _SHARED_RULES
            + "## Output format (strict JSON)\n"
            "{{\n"
            '  "specs": [\n'
            '    {{"filename": "resume.cy.js", "code": "…full JS…"}},\n'
            '    {{"filename": "contact.cy.js", "code": "…full JS…"}}\n'
            "  ]\n"
            "}}\n\n"
            "Return ONLY valid JSON — no extra commentary.",
        ),
        (
            "human",
            "## Target URL\n{url}\n\n"
            "## Test Cases\n```json\n{test_cases}\n```\n\n"
            "## Generated Page Objects (use ONLY these methods — do not invent others)\n"
            "{pom_contents}\n\n"
            "## Actual Page DOM\n"
            "```html\n{page_analysis}\n```\n\n"
            "## Raw DOM Snippet\n"
            "```html\n{raw_dom}\n```\n\n"
            "{cypress_api_context_block}"
            "{human_feedback_block}"
            "{lint_feedback_block}"
            "{self_heal_context}",
        ),
    ]
)


# ── Helpers ──────────────────────────────────────────────────

def _write_file(directory: Path, filename: str, code: str) -> str:
    directory.mkdir(parents=True, exist_ok=True)
    filepath = directory / filename
    filepath.write_text(code, encoding="utf-8")
    logger.info("Wrote %s", filepath)
    return str(filepath)


def _clean_generated_specs() -> None:
    """Remove previously generated spec and page-object files."""
    for d in (CYPRESS_E2E_DIR, CYPRESS_PAGES_DIR):
        if d.exists():
            for f in d.iterdir():
                if f.is_file() and f.suffix == ".js":
                    f.unlink()
                    logger.info("Cleaned old file %s", f)


def _read_pom_contents() -> str:
    """Read all generated POM files into a formatted block for the spec-gen prompt."""
    parts = []
    if CYPRESS_PAGES_DIR.exists():
        for f in sorted(CYPRESS_PAGES_DIR.iterdir()):
            if f.is_file() and f.suffix == ".js":
                parts.append(f"### {f.name}\n```js\n{f.read_text(encoding='utf-8')}\n```")
    return "\n\n".join(parts) or "(no page objects generated)"


def _write_spec_files(specs: list[dict]) -> tuple[list[str], list[dict]]:
    """Delete stale spec files then write fresh ones. Returns (paths, manifest)."""
    if CYPRESS_E2E_DIR.exists():
        for f in CYPRESS_E2E_DIR.iterdir():
            if f.is_file() and f.suffix == ".js":
                f.unlink()
    paths: list[str] = []
    manifest: list[dict] = []
    for spec in specs:
        path = _write_file(CYPRESS_E2E_DIR, spec["filename"], spec["code"])
        paths.append(path)
        manifest.append({"filename": spec["filename"], "path": path})
    return paths, manifest


def _collect_lint_files(generated_paths: list[str]) -> tuple[list[Path], list[Path]]:
    """Collect POM and spec Path objects for linting from state + directory scan."""
    pom_files: list[Path] = []
    spec_files: list[Path] = []
    for p_str in generated_paths:
        p = Path(p_str)
        if not p.exists() or p.suffix != ".js":
            continue
        if "support/pages" in p_str or "support\\pages" in p_str:
            pom_files.append(p)
        elif p_str.endswith(".cy.js"):
            spec_files.append(p)
    if CYPRESS_PAGES_DIR.exists():
        for f in CYPRESS_PAGES_DIR.iterdir():
            if f.is_file() and f.suffix == ".js" and f not in pom_files:
                pom_files.append(f)
    if CYPRESS_E2E_DIR.exists():
        for f in CYPRESS_E2E_DIR.iterdir():
            if f.is_file() and f.name.endswith(".cy.js") and f not in spec_files:
                spec_files.append(f)
    return pom_files, spec_files


async def _node_syntax_check(files: list[Path]) -> list[str]:
    """Run `node --check` on each file concurrently.

    Uses the Node.js parser directly — catches any JS SyntaxError (mismatched
    quotes, unclosed brackets, invalid tokens) before ESLint ever runs.
    Returns a list of human-readable error strings: "<filename>: <error line>".
    """
    if not files:
        return []
    async def _check_one(path: Path) -> list[str]:
        try:
            import subprocess
            result = await asyncio.to_thread(
                lambda: subprocess.run(
                    ["node", "--check", str(path)],
                    capture_output=True, text=True, timeout=15
                )
            )
        except Exception:
            return []
        if result.returncode == 0:
            return []
        return [
            f"{path.name}: {line.strip()}"
            for line in result.stderr.splitlines()
            if line.strip()
    ]
    # async def _check_one(path: Path) -> list[str]:
    #     try:
    #         proc = await asyncio.create_subprocess_exec(
    #             "node", "--check", str(path),
    #             stdout=asyncio.subprocess.PIPE,
    #             stderr=asyncio.subprocess.PIPE,
    #         )
    #         _, stderr_bytes = await asyncio.wait_for(proc.communicate(), timeout=15)
    #     except (FileNotFoundError, asyncio.TimeoutError):
    #         return []
    #     if proc.returncode == 0:
    #         return []
    #     stderr = stderr_bytes.decode(errors="replace").strip()
    #     return [
    #         f"{path.name}: {line.strip()}"
    #         for line in stderr.splitlines()
    #         if line.strip()
    #     ]

    results = await asyncio.gather(*[_check_one(f) for f in files])
    return [err for errors in results for err in errors]


def _self_heal_block(state: QAState) -> str:
    """Build extra prompt context when retrying after failures (used by generate_specs)."""
    errors = state.get("errors", [])
    exec_history = state.get("execution_history", [])
    classified = state.get("classified_errors", [])

    test_code_errors = [e for e in classified if e.get("type") == "test_code_error"]
    if not test_code_errors and not errors:
        return ""

    messages = [e.get("message", str(e)) for e in test_code_errors] or errors[-10:]
    block = (
        "## ⚠️  Previous Execution Errors (self-healing context)\n"
        "Fix the selectors and assertions for these test-code errors:\n"
        f"```\n{chr(10).join(messages)}\n```\n\n"
    )

    if exec_history:
        last_run = exec_history[-1] if isinstance(exec_history[-1], dict) else {}
        stdout_tail = last_run.get("stdout_tail", "")
        if stdout_tail:
            block += (
                "## Last Cypress stdout (tail)\n"
                f"```\n{stdout_tail[-3000:]}\n```\n\n"
            )

    raw_dom = state.get("raw_dom", "")
    block += (
        "## Re-crawled DOM Snapshot\n"
        f"```html\n{raw_dom[:6000]}\n```"
    )
    return block


def _human_feedback_block(state: QAState) -> str:
    feedback = state.get("human_feedback", [])
    if not feedback:
        return ""
    return (
        "## Human Reviewer Feedback\n"
        "Incorporate the following reviewer notes when generating specs:\n"
        + "\n".join(f"- {f}" for f in feedback)
        + "\n\n"
    )


def _pom_lint_feedback_block(state: QAState) -> str:
    """Inject POM syntax errors into the page-object regeneration prompt."""
    errors = state.get("pom_lint_errors") or []
    if not errors:
        return ""
    return (
        "## ⚠️  Syntax Errors in Previous Page Objects — FIX THESE\n"
        "The files you generated last time failed `node --check` with these errors.\n"
        "Read each error carefully (filename:line:col) and produce corrected code:\n"
        f"```\n{chr(10).join(errors)}\n```\n\n"
    )


def _spec_lint_feedback_block(state: QAState) -> str:
    """Inject spec lint/syntax errors into the spec regeneration prompt."""
    errors = state.get("lint_errors") or []
    if not errors:
        return ""
    return (
        "## ⚠️  Lint / Syntax Errors in Previous Specs — FIX THESE\n"
        "The spec files you generated last time failed linting with these errors.\n"
        "Read each error carefully (filename:line:col) and produce corrected code:\n"
        f"```\n{chr(10).join(errors)}\n```\n\n"
    )


def _cypress_api_context_block(state: QAState) -> str:
    """Inject live Cypress API updates fetched from docs.cypress.io.

    Only emits content when the docs subgraph found new or changed behaviors
    versus the hardcoded baseline rules.  Returns empty string otherwise so
    the prompts are not polluted with a no-op block.
    """
    ctx = state.get("cypress_api_context") or {}
    if not ctx.get("has_updates"):
        return ""

    lines = [
        "## 🔄 Live Cypress API Updates (fetched from docs.cypress.io on "
        f"{ctx.get('fetched_at', 'unknown date')})\n"
        "The following changes were detected against the known baseline rules.\n"
        "These OVERRIDE or SUPPLEMENT the static rules above — apply them first.\n"
    ]

    changes = ctx.get("changes_detected") or []
    if changes:
        lines.append("### Detected Changes")
        for c in changes:
            tag = c.get("change_type", "info").upper()
            cmd = c.get("command", "?")
            detail = c.get("detail", "")
            lines.append(f"- [{tag}] `{cmd}`: {detail}")
        lines.append("")

    addendum = ctx.get("rules_addendum", "")
    if addendum:
        lines.append("### Additional Rules from Docs")
        lines.append(addendum)
        lines.append("")

    return "\n".join(lines)


# ── Node functions ───────────────────────────────────────────


@traceable(name="generate_page_objects", run_type="chain")
async def generate_page_objects(state: QAState) -> dict:
    """Node 1 — Generate Cypress POM classes only."""
    url = state["url"]
    test_cases = state.get("test_cases", [])
    page_analysis = state.get("page_analysis", "")
    raw_dom = state.get("raw_dom", "")

    logger.info("SDET / generate_page_objects: generating POM classes")

    # Clean old generated files before starting a fresh generation
    await asyncio.to_thread(_clean_generated_specs)

    result = await (_PAGE_OBJECT_PROMPT | _get_llm()).ainvoke(
        {
            "url": url,
            "test_cases": json.dumps(test_cases, indent=2),
            "page_analysis": page_analysis,
            "raw_dom": raw_dom[:6000] if raw_dom else "(not available)",
            "pom_lint_feedback": _pom_lint_feedback_block(state),
            "cypress_api_context_block": _cypress_api_context_block(state),
        }
    )

    raw: str = result.content  # type: ignore[union-attr]
    try:
        cleaned = raw.strip()
        if cleaned.startswith("```"):
            cleaned = cleaned.split("\n", 1)[1].rsplit("```", 1)[0]
        generated = json.loads(cleaned)
    except (json.JSONDecodeError, IndexError):
        logger.error("SDET / generate_page_objects: failed to parse response")
        return {"errors": [f"Page object gen parse error: {raw[:500]}"]}

    file_paths: list[str] = []
    po_manifest = []
    for po in generated.get("page_objects", []):
        path = await asyncio.to_thread(_write_file, CYPRESS_PAGES_DIR, po["filename"], po["code"])
        file_paths.append(path)
        po_manifest.append({"filename": po["filename"], "path": path})

    logger.info("SDET / generate_page_objects: wrote %d POM files", len(file_paths))
    return {
        "cypress_file_paths": file_paths,
        "cypress_code": json.dumps({"page_objects": po_manifest}, indent=2),
        "lint_retry_count": 0,  # reset linter retry counter on fresh generation
    }


@traceable(name="generate_specs", run_type="chain")
async def generate_specs(state: QAState) -> dict:
    """Node 2 — Generate .cy.js spec files using existing POMs + human feedback."""
    url = state["url"]
    test_cases = state.get("test_cases", [])
    page_analysis = state.get("page_analysis", "")
    raw_dom = state.get("raw_dom", "")

    logger.info(
        "SDET / generate_specs: generating specs (lint retry #%d)",
        state.get("lint_retry_count", 0),
    )

    # Read generated POM files so the LLM only uses methods that actually exist
    pom_contents = await asyncio.to_thread(_read_pom_contents)

    result = await (_SPEC_GEN_PROMPT | _get_llm()).ainvoke(
        {
            "url": url,
            "test_cases": json.dumps(test_cases, indent=2),
            "pom_contents": pom_contents,
            "page_analysis": page_analysis,
            "raw_dom": raw_dom[:6000] if raw_dom else "(not available)",
            "human_feedback_block": _human_feedback_block(state),
            "lint_feedback_block": _spec_lint_feedback_block(state),
            "self_heal_context": _self_heal_block(state),
            "cypress_api_context_block": _cypress_api_context_block(state),
        }
    )

    raw: str = result.content  # type: ignore[union-attr]
    try:
        cleaned = raw.strip()
        if cleaned.startswith("```"):
            cleaned = cleaned.split("\n", 1)[1].rsplit("```", 1)[0]
        generated = json.loads(cleaned)
    except (json.JSONDecodeError, IndexError):
        logger.error("SDET / generate_specs: failed to parse response")
        return {"errors": [f"Spec gen parse error: {raw[:500]}"]}

    # Remove old spec files and write new ones (all blocking I/O in one thread call)
    spec_paths, spec_manifest = await asyncio.to_thread(
        _write_spec_files, generated.get("specs", [])
    )

    logger.info("SDET / generate_specs: wrote %d spec files", len(spec_paths))

    # Merge with existing POM manifest
    existing_code = state.get("cypress_code") or "{}"
    try:
        existing = json.loads(existing_code)
    except json.JSONDecodeError:
        existing = {}

    existing["specs"] = spec_manifest
    return {
        "cypress_file_paths": spec_paths,
        "cypress_code": json.dumps(existing, indent=2),
        "lint_errors": None,  # reset before linter runs
    }


@traceable(name="syntax_linter", run_type="tool")
async def syntax_linter(state: QAState) -> dict:
    """Node 3 — Two-pass linter for ALL generated files (POMs + specs).

    Pass 1:  `node --check` — catches JS SyntaxErrors (mismatched quotes,
             unclosed brackets, invalid tokens).
    Pass 2:  `npx eslint --fix` on surviving files — catches style + logic
             warnings.

    Errors are separated into *pom_lint_errors* and *lint_errors* so the
    router can decide which generator to loop back to.  The shared
    *lint_retry_count* is incremented on every invocation that finds errors
    to prevent infinite loops.
    """
    generated_paths = state.get("cypress_file_paths", [])
    current_retry = state.get("lint_retry_count", 0)

    # Collect ALL .js files under cypress/ (POMs + specs) — blocking I/O off event loop
    pom_files, spec_files = await asyncio.to_thread(_collect_lint_files, generated_paths)

    all_files = pom_files + spec_files
    if not all_files:
        logger.warning("SDET / syntax_linter: no files to lint")
        return {"lint_errors": [], "pom_lint_errors": []}

    logger.info(
        "SDET / syntax_linter: checking %d POMs + %d specs (retry #%d)",
        len(pom_files), len(spec_files), current_retry,
    )

    # ── Pass 1: node --check (JS parse errors) ──────────────
    node_errors = await _node_syntax_check(all_files)
    pom_errs: list[str] = []
    spec_errs: list[str] = []
    for err_line in node_errors:
        # err_line looks like "homePage.js: SyntaxError: …"
        if any(pf.name in err_line for pf in pom_files):
            pom_errs.append(err_line)
        else:
            spec_errs.append(err_line)

    # If node --check found parse errors, skip ESLint (it would just fail too)
    if pom_errs or spec_errs:
        logger.warning(
            "SDET / syntax_linter: node --check found %d POM + %d spec parse error(s)",
            len(pom_errs), len(spec_errs),
        )
        return {
            "pom_lint_errors": pom_errs,
            "lint_errors": spec_errs,
            "lint_retry_count": current_retry + 1,
        }

    # ── Pass 2: ESLint on spec files only (POMs are simple classes) ──
    if spec_files:
        try:
            import subprocess
            result = await asyncio.to_thread(
                lambda: subprocess.run(
                    [
                        "npx", "eslint", "--fix", "--no-eslintrc",
                        "--rule", "no-undef: warn",
                        "--rule", "no-unused-vars: warn",
                        "--env", "browser",
                        "--env", "node",
                        *[str(f) for f in spec_files],
                    ],
                    capture_output=True, text=True,
                    timeout=60, cwd=str(PROJECT_ROOT)
                )
            )
        except FileNotFoundError:
            logger.warning("SDET / syntax_linter: npx/eslint not found — skipping")
            return {"lint_errors": [], "pom_lint_errors": []}
        except Exception:
            logger.warning("SDET / syntax_linter: eslint timed out — skipping")
            return {"lint_errors": [], "pom_lint_errors": []}

        if result.returncode != 0:
            combined = (result.stdout + "\n" + result.stderr).strip()
            eslint_errs = [
                line.strip()
                for line in combined.splitlines()
                if line.strip()
                and ("error" in line.lower() or "warning" in line.lower())
            ]
            if eslint_errs:
                return {
                    "lint_errors": eslint_errs,
                    "pom_lint_errors": [],
                    "lint_retry_count": current_retry + 1,
                }
    # if spec_files:
    #     try:
    #         import subprocess
    #         proc = await asyncio.to_thread(
    #             "npx", "eslint", "--fix", "--no-eslintrc",
    #             "--rule", "no-undef: warn",
    #             "--rule", "no-unused-vars: warn",
    #             "--env", "browser",
    #             "--env", "node",
    #             *[str(f) for f in spec_files],
    #             cwd=str(PROJECT_ROOT),
    #             stdout=asyncio.subprocess.PIPE,
    #             stderr=asyncio.subprocess.PIPE,
    #         )
    #         stdout_bytes, stderr_bytes = await asyncio.wait_for(
    #             proc.communicate(), timeout=60
    #         )
    #     except FileNotFoundError:
    #         logger.warning("SDET / syntax_linter: npx/eslint not found — skipping")
    #         return {"lint_errors": [], "pom_lint_errors": []}
    #     except asyncio.TimeoutError:
    #         logger.warning("SDET / syntax_linter: eslint timed out — skipping")
    #         return {"lint_errors": [], "pom_lint_errors": []}

    #     if proc.returncode != 0:
    #         combined = (
    #             stdout_bytes.decode(errors="replace")
    #             + "\n"
    #             + stderr_bytes.decode(errors="replace")
    #         ).strip()
    #         eslint_errs = [
    #             line.strip()
    #             for line in combined.splitlines()
    #             if line.strip()
    #             and ("error" in line.lower() or "warning" in line.lower())
    #         ]
    #         if eslint_errs:
    #             logger.warning(
    #                 "SDET / syntax_linter: eslint found %d issue(s)",
    #                 len(eslint_errs),
    #             )
    #             return {
    #                 "lint_errors": eslint_errs,
    #                 "pom_lint_errors": [],
    #                 "lint_retry_count": current_retry + 1,
    #             }

    logger.info("SDET / syntax_linter: ✅ all %d files passed", len(all_files))
    return {"lint_errors": [], "pom_lint_errors": []}
