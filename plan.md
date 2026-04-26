# QA-Web-Agent Platform — Implementation Plan

## Overview

An autonomous multi-agent QA platform that transforms a URL and a PRD into a fully audited, automated, and reported test suite. Uses **LangGraph** (with checkpointing) for stateful orchestration, **LangChain-OpenAI** (GPT-4o) for reasoning, a **pluggable browser abstraction** (Playwright now, WebMCP later), and a **DOMProcessor** utility for context window management. Includes FastAPI serving, LangSmith tracing, and Cypress code generation with a self-healing retry loop.

---

## Step 1: Upgrade Python & Bootstrap Environment

- Install Python 3.11 via `brew install python@3.11`.
- Recreate the venv: `python3.11 -m venv venv && source venv/bin/activate`.
- Updated `requirements.txt`:
  ```
  langgraph
  langgraph-cli[inmem]
  langchain
  langchain-openai
  langchain-text-splitters
  python-dotenv
  httpx
  playwright
  fastapi
  uvicorn[standard]
  pydantic>=2.0
  langsmith
  tiktoken
  beautifulsoup4
  langgraph-checkpoint-sqlite
  aiosqlite
  ```
- Run `pip install -r requirements.txt && playwright install chromium`.
- `.env.example` created with:
  ```
  OPENAI_API_KEY=
  LANGSMITH_API_KEY=
  LANGSMITH_TRACING=true
  LANGSMITH_PROJECT=qa-web-agent
  BROWSER_BACKEND=playwright
  CHECKPOINTER=sqlite
  SQLITE_DB_PATH=checkpoints.db
  ```
- `.gitignore` covers venv, .env, __pycache__, node_modules, checkpoints.db, cypress artifacts.
- Initialize Cypress: `npm init -y && npm install cypress`.

---

## Step 2: Project Structure

```
qa-web-agent/
├── src/
│   ├── __init__.py
│   ├── models/
│   │   ├── __init__.py
│   │   ├── state.py          # LangGraph TypedDict state
│   │   └── schemas.py        # Pydantic request/response models
│   ├── browser/
│   │   ├── __init__.py
│   │   ├── base.py            # ABC BrowserAdapter + dataclasses
│   │   ├── playwright_adapter.py
│   │   ├── webmcp_adapter.py  # Stub for future WebMCP
│   │   └── factory.py         # Env-driven adapter selection
│   ├── dom/
│   │   ├── __init__.py
│   │   └── processor.py       # DOMProcessor class
│   ├── agents/
│   │   ├── __init__.py
│   │   ├── architect.py       # analyze_project node
│   │   ├── strategist.py      # generate_test_plan node
│   │   ├── sdet.py            # generate_cypress_scripts node
│   │   └── executor.py        # execute_and_verify node
│   ├── graph/
│   │   ├── __init__.py
│   │   ├── workflow.py        # StateGraph wiring + compile
│   │   └── checkpointer.py   # Checkpointer factory
│   └── server.py              # FastAPI entry point
├── cypress/
│   ├── e2e/                   # Generated spec files
│   ├── support/
│   │   └── pages/             # Page Object Model files
│   └── fixtures/
├── requirements.txt
├── package.json
├── langgraph.json             # LangGraph Platform config
├── .env.example
├── .gitignore
└── plan.md
```

### State Definition (`src/models/state.py`)

```python
class QAState(TypedDict, total=False):
    url: str
    project_description: str           # PRD text
    raw_dom: Optional[str]
    page_analysis: Optional[str]       # unified DOM summary
    technical_overview: Optional[dict]  # product knowledge graph
    test_cases: Annotated[list[dict], add]
    cypress_code: Optional[str]
    cypress_file_paths: Annotated[list[str], add]
    errors: Annotated[list[str], add]
    execution_history: Annotated[list[dict], add]
    retry_count: int
```

### Pydantic Schemas (`src/models/schemas.py`)

- `AnalyzeRequest` — `url: HttpUrl`, `prd_text: str`
- `AnalyzeResponse` — `thread_id`, `status`, `report`, `errors`
- `TestCase` — `id`, `feature`, `scenario`, `steps`, `expected_result`, `severity`
- `BugReport` — `title`, `severity`, `steps_to_reproduce`, `expected`, `actual`, `screenshot_path`
- `POVReport` — `stakeholder`, `developer`, `user`

---

## Step 3: Pluggable Browser Layer

### Architecture

```
BrowserAdapter (ABC)
    ├── PlaywrightAdapter  ← active (Playwright async API, Chromium)
    └── WebMCPAdapter      ← stub (raises NotImplementedError)

factory.py → reads BROWSER_BACKEND env var → returns correct adapter
```

### Key Methods

| Method | Description |
|---|---|
| `start()` / `stop()` | Lifecycle management |
| `crawl_page(url) → PageSnapshot` | Navigate + full extraction |
| `get_interactive_elements()` | Filtered interactive elements only |
| `get_accessibility_tree()` | Accessibility snapshot |
| `take_screenshot()` | PNG bytes |
| `click(selector)` / `fill(selector, value)` | User interactions |
| `evaluate_js(expression)` | Raw JS execution |

### Swapping to WebMCP

Change one env var: `BROWSER_BACKEND=webmcp` — zero code changes needed.

---

## Step 4: DOM Context Window Management

### `DOMProcessor` Pipeline

```
extract_dom(adapter) → filtered HTML (interactive elements only)
        │
        ▼
  needs_chunking?
   ├── NO  → return raw DOM directly
   └── YES → chunk_dom() → summarize_chunks() → merge_summaries()
                                  │                      │
                            (map: parallel LLM)    (reduce: single LLM)
                            semaphore(5) cap       unified page analysis
```

### Configuration

- `max_chunk_tokens=4000` per chunk
- `chunk_overlap=200` tokens
- `model_name="gpt-4o"` (uses `o200k_base` tiktoken encoding)
- `concurrency=5` (asyncio.Semaphore to avoid rate limits)

### Two-Tier Chunking

1. **Structural**: `HTMLHeaderTextSplitter` splits by `h1`/`h2`/`h3`
2. **Token-aware**: `RecursiveCharacterTextSplitter.from_tiktoken_encoder()` enforces 4K-token limit

---

## Step 5: Agent Nodes

All nodes decorated with `@traceable` from `langsmith` for observability.

### Architect (`analyze_project`)

- Crawls URL via `BrowserAdapter.crawl_page()`
- Processes DOM through `DOMProcessor.process_page()` (handles large SPAs)
- Compares page analysis against PRD using GPT-4o
- Outputs: `raw_dom`, `page_analysis`, `technical_overview` (Product Knowledge Graph)

### Strategist (`generate_test_plan`)

- Inputs: `technical_overview` + `page_analysis` + PRD
- Generates hierarchical test documentation (Feature → Scenarios → Test Cases)
- Generates multi-POV reports (Stakeholder, Developer, User perspectives)
- Outputs: `test_cases`, updated `technical_overview` with POV reports

### SDET (`generate_cypress_scripts`)

- Converts test cases into Cypress POM-pattern code
- Selector priority: `data-cy` > `data-testid` > `aria-label` > `role` > CSS
- On retry: includes error logs + re-crawled DOM for self-healing
- Writes files to `cypress/e2e/` and `cypress/support/pages/`
- Outputs: `cypress_code`, `cypress_file_paths`

### Executor (`execute_and_verify`)

- Runs `npx cypress run --reporter json`
- Parses results, captures screenshots
- Detects selector errors for self-healing loop
- Outputs: `execution_history`, `errors`, incremented `retry_count`

---

## Step 6: LangGraph Workflow + Checkpointing

### Graph Topology

```
START → analyze_project → generate_test_plan → generate_cypress_scripts → execute_and_verify
                                                        ↑                         │
                                                        └── (conditional edge) ───┘
                                                            if selector errors
                                                            AND retry_count < 3
                                                        otherwise → END
```

### Checkpointer Options

| Backend | Class | Use Case |
|---|---|---|
| `memory` | `MemorySaver` | Tests, ephemeral |
| `sqlite` | `AsyncSqliteSaver` | Local dev (persistent file) |
| `postgres` | `AsyncPostgresSaver` | Production |

Selected via `CHECKPOINTER` env var. All runs use `thread_id` for resumability.

### Self-Healing Loop

- Max 3 retries before giving up
- On selector error: routes back to SDET agent with error context
- SDET re-generates Cypress code with awareness of what failed

---

## Step 7: FastAPI Server

### Endpoints

| Method | Path | Description |
|---|---|---|
| `POST` | `/analyze` | Full graph run (URL + PRD → report) |
| `POST` | `/analyze/stream` | SSE streaming of agent steps |
| `GET` | `/report/{thread_id}` | Fetch completed run results |
| `GET` | `/runs/{thread_id}/state` | Raw graph state (debug/resume) |
| `GET` | `/health` | Liveness probe |

### Lifespan

- **Startup**: initialise BrowserAdapter, DOMProcessor, compile graph
- **Shutdown**: stop browser adapter, release resources

### Running

```bash
# Option A: FastAPI directly
uvicorn src.server:app --reload --port 8000

# Option B: LangGraph Platform
langgraph dev
```

---

## Architecture Decisions

| Decision | Choice | Rationale |
|---|---|---|
| Browser abstraction | ABC + factory pattern | Swap Playwright → WebMCP via env var, zero code changes |
| DOM management | Map-reduce with tiktoken | Handles SPAs with 10K+ elements without blowing context window |
| Checkpointer (dev) | AsyncSqliteSaver | Persistent across restarts, zero infrastructure |
| Checkpointer (prod) | AsyncPostgresSaver | Multi-process safe, scalable |
| Cypress POM | `cypress/support/pages/` with per-feature objects | Maintainable, reusable selectors across specs |
| Self-healing cap | 3 retries max | Prevents infinite loops on fundamentally broken tests |
| Concurrency cap | `asyncio.Semaphore(5)` in DOMProcessor | Prevents OpenAI rate limit hits during map-reduce |
| LLM | GPT-4o via `langchain_openai.ChatOpenAI` | Best balance of speed + reasoning for code gen |
| Tracing | LangSmith via `@traceable` + env vars | Zero-code observability for all nodes |

---

## Future Work

- **WebMCP adapter**: Implement `WebMCPAdapter` when the MCP SDK stabilises
- **PostgresSaver**: Add `langgraph-checkpoint-postgres` + `psycopg[binary]` for production
- **Visual regression**: Integrate screenshot diffing (e.g., pixelmatch)
- **Human-in-the-loop**: Use LangGraph interrupts for test plan approval before execution
- **CI/CD integration**: GitHub Actions workflow to run the agent on PR
