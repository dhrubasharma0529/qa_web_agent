# 🏗️ QA-Web-Agent — Full Project Architecture

> **Autonomous end-to-end QA platform** that transforms a URL + PRD into a fully audited, automated, and reported test suite — powered by LangGraph, LangChain-OpenAI, Playwright, and Cypress.

---

## 📁 Project Structure

```
qa-web-agent/
├── langgraph.json              # LangGraph Platform config (graph entry point + env)
├── package.json                # Node.js deps (Cypress)
├── requirements.txt            # Python deps (LangGraph, LangChain, Playwright, FastAPI…)
├── cypress.config.js           # Cypress runner configuration
├── .env                        # API keys + runtime config
│
├── src/                        # ── Python source ──
│   ├── server.py               # FastAPI HTTP server (alternative to langgraph dev)
│   │
│   ├── models/                 # Data layer
│   │   ├── state.py            # LangGraph QAState TypedDict
│   │   └── schemas.py          # Pydantic request/response models
│   │
│   ├── browser/                # Pluggable browser abstraction
│   │   ├── base.py             # Abstract BrowserAdapter + dataclasses
│   │   ├── factory.py          # Env-driven adapter factory
│   │   ├── playwright_adapter.py  # Playwright implementation
│   │   └── webmcp_adapter.py   # WebMCP stub (future)
│   │
│   ├── dom/                    # DOM intelligence
│   │   └── processor.py        # Chunking + map-reduce summarisation
│   │
│   ├── agents/                 # LLM-powered agent nodes
│   │   ├── architect.py        # Phase 1 — Contextual Intelligence
│   │   ├── strategist.py       # Phase 2 — QA Documentation
│   │   ├── sdet.py             # Phase 3 — Cypress Code Generation
│   │   ├── executor.py         # Phase 4 — Test Execution & Verification
│   │   └── reporter.py         # Phase 5 — Markdown Report Generation
│   │
│   └── graph/                  # LangGraph orchestration
│       ├── workflow.py         # StateGraph definition + conditional edges
│       └── checkpointer.py     # Persistence backend factory
│
├── static/
│   └── index.html              # Single-page web UI (SSE + tabbed output)
│
├── cypress/                    # ── Generated test artefacts ──
│   ├── e2e/                    # Generated .cy.js spec files
│   ├── support/
│   │   ├── e2e.js              # Cypress support file
│   │   ├── commands.js         # Custom Cypress commands
│   │   └── pages/              # Generated Page Object files
│   └── screenshots/            # Failure screenshots
│
└── reports/                    # Generated markdown reports
    ├── test_cases_report.md
    └── bug_report.md
```

---

## 🔄 High-Level System Flow

```mermaid
flowchart TB
    subgraph INPUT["🎯 User Input"]
        URL["Target URL"]
        PRD["Product Requirements<br/>Document (PRD)"]
    end

    subgraph PLATFORM["⚙️ Entry Points"]
        LGD["langgraph dev<br/>(Port 2024)"]
        FAST["FastAPI Server<br/>(Port 8000)"]
    end

    subgraph GRAPH["🧠 LangGraph StateGraph"]
        direction TB
        A["Phase 1<br/>🏛️ Architect"]
        B["Phase 2<br/>📋 Strategist"]
        C["Phase 3<br/>🔧 SDET"]
        D["Phase 4<br/>▶️ Executor"]
        E["Phase 5<br/>📄 Reporter"]

        A --> B --> C --> D
        D -->|"selector errors<br/>& retries < 3"| C
        D -->|"pass / budget<br/>exhausted"| E
    end

    subgraph INFRA["🔌 Infrastructure"]
        BROWSER["Playwright<br/>Browser"]
        DOM["DOM<br/>Processor"]
        LLM["OpenAI<br/>GPT-4o-mini"]
        CYPRESS["Cypress<br/>Runner"]
        CHECK["Checkpointer<br/>(Memory / SQLite)"]
    end

    subgraph OUTPUT["📦 Output"]
        SPECS["Cypress Spec<br/>Files"]
        PO["Page Object<br/>Files"]
        TC_RPT["Test Cases<br/>Report (.md)"]
        BUG_RPT["Bug Report<br/>(.md)"]
        SCREENSHOTS["Failure<br/>Screenshots"]
    end

    URL --> PLATFORM
    PRD --> PLATFORM
    LGD --> GRAPH
    FAST --> GRAPH

    A -.->|crawl| BROWSER
    A -.->|chunk + summarise| DOM
    A -.->|analyse| LLM
    B -.->|plan| LLM
    C -.->|generate code| LLM
    D -.->|npx cypress run| CYPRESS
    GRAPH -.->|persist state| CHECK

    C -->|write files| SPECS
    C -->|write files| PO
    D -->|capture| SCREENSHOTS
    E -->|write| TC_RPT
    E -->|write| BUG_RPT
```

---

## 🧩 Module-by-Module Deep Dive

### 1. Models Layer — `src/models/`

```mermaid
classDiagram
    class QAState {
        <<TypedDict>>
        +str url
        +str project_description
        +str raw_dom
        +str page_analysis
        +dict technical_overview
        +list~dict~ test_cases ⊕
        +str cypress_code
        +list~str~ cypress_file_paths ⊕
        +list~str~ errors ⊕
        +list~dict~ execution_history ⊕
        +int retry_count
    }

    class AnalyzeRequest {
        <<Pydantic>>
        +HttpUrl url
        +str prd_text
    }

    class AnalyzeResponse {
        <<Pydantic>>
        +str thread_id
        +RunStatus status
        +dict report
        +list~str~ errors
    }

    class TestCase {
        <<Pydantic>>
        +str id
        +str feature
        +str scenario
        +list~TestStep~ steps
        +str expected_result
        +Severity severity
        +list~str~ tags
    }

    class BugReport {
        <<Pydantic>>
        +str title
        +Severity severity
        +list~str~ steps_to_reproduce
        +str expected_behaviour
        +str actual_behaviour
    }

    QAState ..> TestCase : test_cases contain
    QAState ..> BugReport : errors reference
    AnalyzeRequest --> QAState : initializes
    QAState --> AnalyzeResponse : produces
```

**Purpose**: The shared data contract for the entire system.

| File | Role |
|------|------|
| `state.py` | `QAState` — the single TypedDict that flows through every LangGraph node. Fields marked `⊕` use the `Annotated[list, add]` reducer so each node **appends** rather than overwrites. |
| `schemas.py` | Pydantic models for HTTP request/response validation (`AnalyzeRequest`, `AnalyzeResponse`) plus structured LLM output schemas (`TestCase`, `BugReport`, `POVReport`). |

**How it connects**: Every agent node receives `QAState` as input and returns a partial dict that LangGraph merges back using the field reducers.

---

### 2. Browser Layer — `src/browser/`

```mermaid
classDiagram
    class BrowserAdapter {
        <<Abstract>>
        +start()
        +stop()
        +crawl_page(url) PageSnapshot
        +get_interactive_elements() list~InteractiveElement~
        +get_accessibility_tree() dict
        +take_screenshot() bytes
        +click(selector)
        +fill(selector, value)
        +evaluate_js(expression) Any
        +get_page_html() str
    }

    class PlaywrightAdapter {
        -Playwright _pw
        -Browser _browser
        -Page _page
        +_ensure_started()
        +crawl_page(url)
        +evaluate_js(expression)
    }

    class WebMCPAdapter {
        -str _mcp_url
        +all methods → NotImplementedError
    }

    class PageSnapshot {
        <<dataclass>>
        +str url
        +str title
        +str html
        +list~InteractiveElement~ elements
        +dict accessibility_tree
        +bytes screenshot
    }

    class InteractiveElement {
        <<dataclass>>
        +int index
        +str tag
        +str text
        +str role
        +str href
        +str selector
        +dict bounding_box
    }

    BrowserAdapter <|-- PlaywrightAdapter
    BrowserAdapter <|-- WebMCPAdapter
    PlaywrightAdapter --> PageSnapshot : returns
    PageSnapshot --> InteractiveElement : contains
    
    class BrowserFactory {
        <<factory.py>>
        +create_browser_adapter(backend) BrowserAdapter
    }
    BrowserFactory --> PlaywrightAdapter : creates
    BrowserFactory --> WebMCPAdapter : creates
```

**Purpose**: Pluggable browser abstraction — swap Playwright for WebMCP (or any future adapter) via a single `BROWSER_BACKEND` env var.

| File | Role |
|------|------|
| `base.py` | Defines the `BrowserAdapter` ABC with 10 abstract methods, plus `PageSnapshot` and `InteractiveElement` dataclasses. |
| `factory.py` | `create_browser_adapter()` — reads `BROWSER_BACKEND` from env, returns the matching concrete adapter. |
| `playwright_adapter.py` | Full Playwright implementation. Key features: **lazy auto-start** (`_ensure_started()`), two JS extraction scripts (interactive elements + filtered HTML), accessibility tree snapshot. |
| `webmcp_adapter.py` | Stub for future MCP-based browser control. All methods raise `NotImplementedError`. |

**How it connects**:
- The **Architect agent** calls `browser.crawl_page(url)` to get a `PageSnapshot`.
- The **DOM Processor** calls `browser.evaluate_js()` to extract filtered HTML.
- `_ensure_started()` enables **langgraph dev** compatibility (no explicit lifecycle management needed).

---

### 3. DOM Layer — `src/dom/processor.py`

```mermaid
flowchart LR
    subgraph EXTRACT["1️⃣ Extract"]
        RAW["Raw Filtered HTML<br/>(via evaluate_js)"]
    end

    subgraph CHECK_SIZE["2️⃣ Check"]
        TOK{"Tokens ><br/>4,000?"}
    end

    subgraph CHUNK["3️⃣ Chunk"]
        H_SPLIT["HTMLHeaderTextSplitter<br/>(h1/h2/h3 boundaries)"]
        T_SPLIT["RecursiveCharacterTextSplitter<br/>(tiktoken-aware)"]
        H_SPLIT --> T_SPLIT
    end

    subgraph MAP["4️⃣ Map (parallel)"]
        S1["Summarise<br/>Chunk 1"]
        S2["Summarise<br/>Chunk 2"]
        SN["Summarise<br/>Chunk N"]
    end

    subgraph REDUCE["5️⃣ Reduce"]
        MERGE["Merge all summaries<br/>→ Unified Page Analysis"]
    end

    RAW --> TOK
    TOK -->|No| PASSTHROUGH["Return raw HTML<br/>(fits context window)"]
    TOK -->|Yes| H_SPLIT
    T_SPLIT --> S1 & S2 & SN
    S1 & S2 & SN --> MERGE
```

**Purpose**: Intelligently manages the DOM context window for LLM processing.

| Component | What it does |
|-----------|-------------|
| `extract_dom()` | Runs a JS snippet in the browser to collect only **testable** HTML elements (buttons, links, inputs, headings, landmarks, ARIA, data-* attributes). |
| `count_tokens()` / `needs_chunking()` | Uses **tiktoken** (lazy-loaded) to check if the filtered DOM exceeds the 4,000-token threshold. |
| `chunk_dom()` | Two-tier splitting: first by HTML headers (h1/h2/h3 semantic boundaries), then by token count using `RecursiveCharacterTextSplitter.from_tiktoken_encoder()`. |
| `summarize_chunks()` | **Map phase**: sends each `DOMChunk` to the LLM with `asyncio.Semaphore(5)` concurrency cap. |
| `merge_summaries()` | **Reduce phase**: combines all chunk summaries into a single unified page analysis. |
| `process_page()` | Orchestrates the full pipeline: extract → check → (chunk → map → reduce) or passthrough. |

**How it connects**: Called by the **Architect agent** during Phase 1. The resulting page analysis string flows into `QAState.page_analysis` and is used by all downstream agents.

---

### 4. Agents Layer — `src/agents/`

```mermaid
flowchart TB
    subgraph PHASE1["Phase 1 — Architect"]
        A1["Crawl URL via<br/>PlaywrightAdapter"]
        A2["Process DOM via<br/>DOMProcessor"]
        A3["LLM: Compare DOM<br/>vs PRD"]
        A4["Output: Product<br/>Knowledge Graph"]
        A1 --> A2 --> A3 --> A4
    end

    subgraph PHASE2["Phase 2 — Strategist"]
        B1["Input: Knowledge Graph<br/>+ Page Analysis + PRD"]
        B2["LLM: Generate<br/>Test Cases"]
        B3["LLM: Generate<br/>POV Reports"]
        B4["Output: test_cases[]<br/>+ pov_reports"]
        B1 --> B2 --> B3 --> B4
    end

    subgraph PHASE3["Phase 3 — SDET"]
        C1["Input: test_cases[]<br/>+ raw_dom + errors"]
        C2["Clean old spec files"]
        C3["LLM: Generate Cypress<br/>specs + Page Objects"]
        C4["Write files to<br/>cypress/e2e/ & support/pages/"]
        C1 --> C2 --> C3 --> C4
    end

    subgraph PHASE4["Phase 4 — Executor"]
        D1["Collect generated<br/>.cy.js file paths"]
        D2["npx cypress run<br/>--headed --spec --reporter spec"]
        D3["Parse stdout:<br/>passing/failing/pending"]
        D4["Classify errors:<br/>selector vs other"]
        D1 --> D2 --> D3 --> D4
    end

    subgraph PHASE5["Phase 5 — Reporter"]
        E1["Build test_cases_report.md<br/>(summary + detailed TCs)"]
        E2["Build bug_report.md<br/>(failures + missing features)"]
        E3["Write to reports/"]
        E1 --> E3
        E2 --> E3
    end

    PHASE1 ==> PHASE2 ==> PHASE3 ==> PHASE4
    PHASE4 ==>|"self-heal<br/>loop"| PHASE3
    PHASE4 ==> PHASE5
```

#### Phase 1: Architect (`architect.py`)

| Aspect | Detail |
|--------|--------|
| **Input** | `url`, `project_description` |
| **Process** | 1. Crawls URL via `browser.crawl_page()` → `PageSnapshot` <br/> 2. Processes DOM via `dom_processor.process_page()` → page analysis string <br/> 3. Sends PRD + page analysis to LLM with structured prompt → Product Knowledge Graph |
| **Output** | `raw_dom`, `page_analysis`, `technical_overview` (JSON with implemented/missing features, tech signals, risks) |
| **LLM Prompt** | Senior QA Architect role — maps every PRD requirement to implementation status |
| **Dependencies** | `BrowserAdapter`, `DOMProcessor`, `ChatOpenAI` |

#### Phase 2: Strategist (`strategist.py`)

| Aspect | Detail |
|--------|--------|
| **Input** | `technical_overview`, `page_analysis`, `project_description` |
| **Process** | 1. Generates hierarchical test cases from Knowledge Graph <br/> 2. Generates multi-POV reports (Stakeholder / Developer / User) |
| **Output** | `test_cases` (list of structured TC dicts), updated `technical_overview` with POV reports |
| **LLM Prompts** | Two-chain: Test Plan prompt → POV Report prompt |
| **Dependencies** | `ChatOpenAI` only (no browser needed) |

#### Phase 3: SDET (`sdet.py`)

| Aspect | Detail |
|--------|--------|
| **Input** | `url`, `test_cases`, `page_analysis`, `raw_dom`, `errors` (on retry) |
| **Process** | 1. Cleans old generated files <br/> 2. Generates Cypress specs + Page Objects via LLM <br/> 3. Writes `.js` files to disk |
| **Output** | `cypress_code`, `cypress_file_paths` |
| **Self-Healing** | On retry: injects previous errors + last Cypress stdout + re-crawled DOM into prompt |
| **Key Rules** | CommonJS only, no bare tag selectors, no `cy.intercept`, `.first()` for multi-match, one spec per feature |
| **Dependencies** | `ChatOpenAI`, filesystem |

#### Phase 4: Executor (`executor.py`)

| Aspect | Detail |
|--------|--------|
| **Input** | `cypress_file_paths`, `retry_count` |
| **Process** | 1. Validates spec files exist <br/> 2. Runs `npx cypress run --headed --spec <files> --reporter spec` <br/> 3. Parses regex: `(\d+) passing/failing/pending` <br/> 4. Classifies errors as selector-related or other |
| **Output** | `execution_history` (attempt details), `errors` (selector errors), `retry_count` |
| **Timeout** | 300 seconds |
| **Dependencies** | Node.js + Cypress (subprocess) |

#### Phase 5: Reporter (`reporter.py`)

| Aspect | Detail |
|--------|--------|
| **Input** | Full `QAState` (all accumulated data) |
| **Process** | 1. Builds `test_cases_report.md` with summary table, app overview, detailed TCs with severity badges <br/> 2. Builds `bug_report.md` with execution summary, missing features (BUG-M###), test failures (BUG-T###) |
| **Output** | `cypress_file_paths` (appends report file paths) |
| **Dependencies** | Filesystem only (no LLM calls) |

---

### 5. Graph Layer — `src/graph/`

```mermaid
stateDiagram-v2
    [*] --> analyze_project: START

    analyze_project --> generate_test_plan
    generate_test_plan --> generate_cypress_scripts
    generate_cypress_scripts --> execute_and_verify

    state execute_decision <<choice>>
    execute_and_verify --> execute_decision

    execute_decision --> generate_cypress_scripts: errors & retries < 3
    execute_decision --> generate_reports: pass OR retries ≥ 3

    generate_reports --> [*]: END
```

#### `workflow.py`

| Component | Role |
|-----------|------|
| `build_graph()` | Full graph construction with explicit browser + DOM processor injection. Used by `server.py`. |
| `create_graph()` | **Zero-arg factory** for `langgraph dev`. Creates default browser + DOM processor internally. Referenced in `langgraph.json`. |
| `_should_retry()` | Conditional edge function: returns `"retry"` if errors exist and `retry_count < MAX_RETRIES (3)`, else `"done"`. |
| 5 nodes | `analyze_project` → `generate_test_plan` → `generate_cypress_scripts` → `execute_and_verify` → `generate_reports` |
| Self-healing loop | `execute_and_verify` ↔ `generate_cypress_scripts` (up to 3 retries) |

#### `checkpointer.py`

| Function | Backend | Use Case |
|----------|---------|----------|
| `create_checkpointer()` | `MemorySaver` | For `langgraph dev` CLI (zero-arg, synchronous) |
| `create_async_checkpointer()` | `MemorySaver` / `AsyncSqliteSaver` / `AsyncPostgresSaver` | For FastAPI server (async, env-configurable) |

**How it connects**: The checkpointer enables **state persistence** across graph steps, allowing inspection of intermediate results and potential run resumption.

---

### 6. Server Layer — `src/server.py`

```mermaid
flowchart LR
    subgraph CLIENT["Client"]
        UI["Web UI<br/>(index.html)"]
        STUDIO["LangGraph<br/>Studio"]
        CURL["cURL /<br/>HTTP Client"]
    end

    subgraph FASTAPI["FastAPI Server (Port 8000)"]
        HEALTH["GET /health"]
        ANALYZE["POST /analyze"]
        STREAM["POST /analyze/stream<br/>(SSE)"]
        REPORT["GET /report/:id"]
        STATE["GET /runs/:id/state"]
        REPORTS["GET /reports/:filename"]
        STATIC["GET / (index.html)"]
    end

    subgraph LANGGRAPH_DEV["langgraph dev (Port 2024)"]
        LG_API["LangGraph Platform<br/>API"]
    end

    UI -->|SSE| STREAM
    UI -->|fetch| REPORT
    UI -->|fetch| REPORTS
    STUDIO --> LG_API
    CURL --> ANALYZE

    STREAM --> GRAPH["StateGraph.astream_events()"]
    ANALYZE --> GRAPH
    LG_API --> GRAPH
```

| Endpoint | Method | Purpose |
|----------|--------|---------|
| `/` | GET | Serves the web UI (`static/index.html`) |
| `/health` | GET | Liveness probe |
| `/analyze` | POST | Synchronous full graph run, returns final result |
| `/analyze/stream` | POST | **SSE streaming** — emits `on_chain_start/end/stream` events in real-time |
| `/report/{thread_id}` | GET | Fetches final state of a completed run (uses `aget_state()`) |
| `/runs/{thread_id}/state` | GET | Raw graph state inspection for debugging |
| `/reports/{filename}` | GET | Serves generated markdown report files |

**Two entry points**:
- **`langgraph dev`** (port 2024) — uses `langgraph.json` → `create_graph()`, exposes LangGraph Platform API, works with LangGraph Studio.
- **`uvicorn src.server:app`** (port 8000) — uses `build_graph()` with explicit lifecycle management, serves custom web UI with SSE.

---

### 7. Frontend — `static/index.html`

```mermaid
flowchart TB
    subgraph UI["Single-Page Web UI"]
        INPUT["URL + PRD<br/>Input Form"]
        TABS["7 Tabs"]

        subgraph TAB_LIST["Tab Views"]
            T1["📡 Live Log<br/>(real-time SSE)"]
            T2["🧠 Knowledge Graph<br/>(features, risks)"]
            T3["📋 Test Cases<br/>(steps, severity)"]
            T4["🌲 Cypress Files<br/>(generated paths)"]
            T5["▶️ Execution<br/>(pass/fail cards)"]
            T6["📄 Reports<br/>(download .md)"]
            T7["🔧 Raw JSON<br/>(debug)"]
        end
    end

    INPUT -->|"POST /analyze/stream"| SSE["SSE Event Stream"]
    SSE -->|events| T1
    SSE -->|"on_chain_end<br/>analyze_project"| T2
    SSE -->|"on_chain_end<br/>generate_test_plan"| T3
    SSE -->|"on_chain_end<br/>generate_cypress_scripts"| T4
    SSE -->|"on_chain_end<br/>execute_and_verify"| T5
    SSE -->|"on_chain_end<br/>generate_reports"| T6
    SSE -->|done| T7
```

---

## 🔗 Complete Data Flow

```mermaid
sequenceDiagram
    actor User
    participant UI as Web UI / Studio
    participant Server as FastAPI / langgraph dev
    participant Graph as LangGraph StateGraph
    participant Architect as 🏛️ Architect
    participant Browser as 🌐 Playwright
    participant DOM as 📄 DOMProcessor
    participant LLM as 🤖 GPT-4o-mini
    participant Strategist as 📋 Strategist
    participant SDET as 🔧 SDET
    participant FS as 📁 Filesystem
    participant Cypress as 🌲 Cypress
    participant Reporter as 📄 Reporter

    User->>UI: Enter URL + PRD
    UI->>Server: POST /analyze/stream
    Server->>Graph: ainvoke(initial_state)

    Note over Graph: Phase 1 — Contextual Intelligence
    Graph->>Architect: QAState{url, prd}
    Architect->>Browser: crawl_page(url)
    Browser-->>Architect: PageSnapshot{html, elements}
    Architect->>DOM: process_page(browser, llm)
    DOM->>Browser: evaluate_js(filtered HTML)
    DOM->>LLM: chunk summaries (if >4K tokens)
    LLM-->>DOM: unified page analysis
    DOM-->>Architect: page_analysis string
    Architect->>LLM: PRD + page_analysis → Knowledge Graph
    LLM-->>Architect: JSON Knowledge Graph
    Architect-->>Graph: {raw_dom, page_analysis, technical_overview}

    Note over Graph: Phase 2 — QA Documentation
    Graph->>Strategist: QAState
    Strategist->>LLM: KG + analysis → test cases
    LLM-->>Strategist: test_cases[]
    Strategist->>LLM: KG + TCs → POV reports
    LLM-->>Strategist: {stakeholder, developer, user}
    Strategist-->>Graph: {test_cases, technical_overview}

    Note over Graph: Phase 3 — Cypress Code Generation
    Graph->>SDET: QAState
    SDET->>FS: clean old specs
    SDET->>LLM: TCs + DOM + rules → Cypress code
    LLM-->>SDET: {page_objects, specs} JSON
    SDET->>FS: write .js files
    SDET-->>Graph: {cypress_code, cypress_file_paths}

    Note over Graph: Phase 4 — Execution & Verification
    Graph->>Cypress: npx cypress run --headed --spec files
    Cypress-->>Graph: stdout (passing/failing/pending)

    alt Selector errors & retries < 3
        Graph->>SDET: errors + stdout + DOM (self-heal)
        SDET->>LLM: fix selectors
        LLM-->>SDET: corrected specs
        SDET->>FS: overwrite files
        Graph->>Cypress: re-run
    end

    Note over Graph: Phase 5 — Report Generation
    Graph->>Reporter: full QAState
    Reporter->>FS: write test_cases_report.md
    Reporter->>FS: write bug_report.md
    Reporter-->>Graph: {cypress_file_paths: [report paths]}

    Graph-->>Server: final QAState
    Server-->>UI: SSE: done + thread_id
    UI->>Server: GET /report/{thread_id}
    Server-->>UI: Full results
    UI->>Server: GET /reports/test_cases_report.md
    Server-->>UI: Markdown content
```

---

## ⚙️ Configuration & Environment

```mermaid
flowchart LR
    subgraph ENV[".env File"]
        KEY["OPENAI_API_KEY"]
        MODEL["OPENAI_MODEL=gpt-4o-mini"]
        BACKEND["BROWSER_BACKEND=playwright"]
        CHECK["CHECKPOINTER=sqlite"]
        LS_KEY["LANGSMITH_API_KEY"]
        LS_TRACE["LANGSMITH_TRACING=true"]
    end

    MODEL -->|read by| ARCH["architect.py"]
    MODEL -->|read by| STRAT["strategist.py"]
    MODEL -->|read by| SDET_M["sdet.py"]
    MODEL -->|read by| DOM_M["processor.py"]
    BACKEND -->|read by| FACTORY["factory.py"]
    CHECK -->|read by| CHECKPT["checkpointer.py"]
    KEY -->|used by| OPENAI["ChatOpenAI"]
    LS_KEY -->|used by| SMITH["LangSmith Tracing"]
```

| Variable | Default | Used By | Purpose |
|----------|---------|---------|---------|
| `OPENAI_API_KEY` | — | All agents | OpenAI API authentication |
| `OPENAI_MODEL` | `gpt-4o-mini` | All agents + DOMProcessor | Which LLM model to use |
| `BROWSER_BACKEND` | `playwright` | `factory.py` | Select browser adapter |
| `CHECKPOINTER` | `memory` | `checkpointer.py` | Persistence backend |
| `LANGSMITH_TRACING` | `true` | `@traceable` decorators | Enable LangSmith observability |
| `LANGSMITH_API_KEY` | — | LangSmith SDK | LangSmith authentication |

---

## 🔄 Self-Healing Loop Detail

```mermaid
flowchart TD
    START["execute_and_verify<br/>runs Cypress"] --> PARSE["Parse results:<br/>passing / failing / pending"]
    PARSE --> CHECK{"Selector errors<br/>detected?"}

    CHECK -->|No errors| DONE["→ generate_reports"]
    CHECK -->|Yes| RETRY_CHECK{"retry_count<br/>< 3?"}

    RETRY_CHECK -->|No| EXHAUST["Log warning:<br/>budget exhausted<br/>→ generate_reports"]
    RETRY_CHECK -->|Yes| HEAL["Self-Healing Context Built"]

    HEAL --> CTX1["Previous error messages"]
    HEAL --> CTX2["Last Cypress stdout tail"]
    HEAL --> CTX3["Raw DOM snapshot (6K chars)"]

    CTX1 & CTX2 & CTX3 --> REGEN["SDET re-generates<br/>all spec files"]
    REGEN --> RERUN["execute_and_verify<br/>runs again"]
    RERUN --> PARSE
```

**Error classification patterns**:
- `Timed out retrying after` → Selector error
- `Expected to find element` → Selector error
- `cy.get() failed` → Selector error
- `AssertionError` → Assertion error
- `CypressError` → Runtime error

---

## 🚀 How to Run

### Option A: LangGraph Dev (Recommended)

```bash
# 1. Activate venv
source venv/bin/activate

# 2. Start LangGraph dev server
langgraph dev --no-browser

# 3. Open LangGraph Studio
# → https://smith.langchain.com/studio/?baseUrl=http://127.0.0.1:2024

# 4. Send input:
# {
#   "url": "https://example.com",
#   "project_description": "Description of the app..."
# }
```

### Option B: FastAPI Server + Web UI

```bash
# 1. Activate venv
source venv/bin/activate

# 2. Start FastAPI server
uvicorn src.server:app --reload --port 8000

# 3. Open web UI
# → http://localhost:8000
```

---

## 📊 Technology Stack

```mermaid
mindmap
  root((QA-Web-Agent))
    Orchestration
      LangGraph 1.1.3
        StateGraph
        Conditional Edges
        Checkpointing
      LangGraph CLI
        langgraph dev
        LangGraph Studio
    AI / LLM
      LangChain-OpenAI
        ChatOpenAI
        GPT-4o-mini
      LangChain Core
        ChatPromptTemplate
        Document
      tiktoken
        Token counting
        Context window management
    Browser Automation
      Playwright 1.58
        Async API
        Chromium
        Lazy auto-start
      Cypress 15.12
        E2E test runner
        Spec reporter
        Headed mode
    Web Framework
      FastAPI 0.135
        SSE streaming
        Static files
        Lifespan hooks
      Pydantic v2
        Request validation
        Response schemas
    Observability
      LangSmith
        @traceable decorators
        Run tracing
        LangGraph Studio
    Persistence
      MemorySaver
      AsyncSqliteSaver
      aiosqlite
```

---

## 🔑 Key Design Decisions

| Decision | Rationale |
|----------|-----------|
| **Pluggable browser adapter** | Swap Playwright ↔ WebMCP without touching agent code |
| **Lazy auto-start** (`_ensure_started`) | Enables `langgraph dev` usage without explicit lifecycle management |
| **Map-reduce DOM processing** | Handles large pages that exceed LLM context windows |
| **Lazy tiktoken initialization** | Avoids blocking I/O during ASGI startup |
| **Annotated reducers** on `QAState` | Each node appends to shared lists instead of overwriting |
| **Two entry points** (FastAPI + langgraph dev) | Development flexibility — use Studio or custom UI |
| **CommonJS-only Cypress generation** | Cypress doesn't support ES modules by default |
| **One spec per feature** | Easier debugging, cleaner self-healing |
| **Self-healing with full context** | Injects errors + stdout + DOM so LLM can fix selectors accurately |
| **`@traceable` on every agent** | Full observability via LangSmith |

---

*Architecture document generated for QA-Web-Agent v0.1.0*
