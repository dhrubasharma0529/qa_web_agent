# QA-Web-Agent

**An autonomous multi-agent QA platform.** Give it a URL and a Product Requirements Document; it crawls the site, generates a test plan, writes Cypress specs, runs them, self-heals broken selectors, and produces a markdown bug report.

Built on **LangGraph** for multi-agent orchestration, **LangChain-OpenAI** for reasoning, **Playwright** for crawling, and **Cypress** for execution.

---

## Quick start

You need Docker Desktop running and an OpenAI API key.

```bash
git clone <this-repo-url>
cd qa-agent-dhur

# Configure secrets
cp .env.example .env
# Edit .env and set OPENAI_API_KEY (and optionally LANGSMITH_API_KEY)

# Build and run
docker compose up --build

# Open the UI
# → http://localhost:8000
```

Submit a URL + PRD in the form. Watch the Live Log tab while the 5 agents (Architect → Strategist → SDET → Executor → Reporter) work through your input.

---

## What's inside

```
src/                     Python source (FastAPI + LangGraph + agents)
  agents/                  5 agent nodes — one per phase of the QA pipeline
  browser/                 Pluggable browser abstraction (Playwright now, MCP later)
  dom/                     Map-reduce DOM summariser for large pages
  graph/                   LangGraph StateGraph wiring + checkpointer
  models/                  Pydantic schemas + LangGraph state
  server.py                FastAPI app, SSE streaming, static UI mount
static/index.html        Single-page UI with 7 tabs and live SSE log
cypress/                 Generated specs (e2e/) and page objects (support/pages/)
reports/                 Generated test_cases_report.md and bug_report.md
tests/                   pytest suite (smoke tests for CI)
Dockerfile               Production container recipe
docker-compose.yml       Local development orchestration
requirements.txt         Production Python dependencies
requirements-dev.txt     CI/test-only dependencies
```

For the full architectural deep-dive (mermaid diagrams, agent roles, data flow), read [ARCHITECTURE.md](ARCHITECTURE.md).
For the original implementation plan, read [plan.md](plan.md).

---

## Configuration

All configuration is read from `.env` at runtime. See [.env.example](.env.example) for the full list. The most important variables:

| Variable | Required | Purpose |
|---|---|---|
| `OPENAI_API_KEY` | yes | OpenAI authentication for all agents |
| `OPENAI_MODEL` | no | Defaults to `gpt-4o-mini` |
| `BROWSER_BACKEND` | no | `playwright` (default) or `webmcp` |
| `CHECKPOINTER` | no | `memory`, `sqlite` (default), or `postgres` |
| `LANGSMITH_API_KEY` | no | Enables tracing in LangSmith |
| `CYPRESS_HEADED` | no | `false` on servers (default), `true` only with a display |

---

## Development

```bash
# Activate your virtualenv first (qaenv on Windows, .venv elsewhere)
python -m pip install -r requirements-dev.txt

# Run tests
python -m pytest -q

# Run the app outside Docker (requires Playwright + Cypress installed locally)
uvicorn src.server:app --reload --port 8000
```

---

## Deployment

This project deploys to a single AWS EC2 instance with Cloudflare in front and CI/CD via GitHub Actions. Detailed plan and architecture documents will land in the repo as the deployment work progresses.

---

## License

Currently unlicensed (private repository). If/when this becomes public, choose explicitly.
