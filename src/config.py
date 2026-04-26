"""Centralized configuration for QA-Web-Agent.

All constants and environment-driven settings live here.
Import `config` in any module instead of using os.getenv() directly.
"""

from __future__ import annotations
import sys

# Windows: Playwright needs ProactorEventLoop to spawn the browser subprocess.
# Setting the policy here (the earliest-imported module in the project) ensures
# it takes effect before uvicorn creates its event loop — in langgraph dev and
# in the FastAPI server alike.  No-op on macOS / Linux.
if sys.platform == "win32":
    import asyncio as _asyncio
    _asyncio.set_event_loop_policy(_asyncio.WindowsProactorEventLoopPolicy())

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    # ── Retry / timeout budgets ─────────────────────────────
    MAX_RETRIES: int = 3          # lint retry budget
    MAX_CYPRESS_RUNS: int = 3     # total Cypress executions (initial + heals)
    CYPRESS_TIMEOUT_SECONDS: int = 300

    # ── Cypress execution display ────────────────────────────
    CYPRESS_HEADED: bool = False         # True = visible browser, False = headless
    CYPRESS_STEP_DELAY_MS: int = 500     # ms pause after each test for visual inspection (0 = off)

    # ── LLM ─────────────────────────────────────────────────
    LLM_MODEL: str = "gpt-4o-mini"

    # ── Runtime environment ──────────────────────────────────
    TARGET_ENV: str = "local"       # "local" | "cloud"

    # ── API keys (read from .env) ────────────────────────────
    OPENAI_API_KEY: str = ""
    LANGSMITH_API_KEY: str = ""
    LANGSMITH_TRACING: bool = False
    LANGSMITH_PROJECT: str = "qa-web-agent"

    # ── Persistence ─────────────────────────────────────────
    CHECKPOINTER: str = "memory"    # "memory" | "sqlite" | "postgres"
    SQLITE_DB_PATH: str = "checkpoints.db"
    POSTGRES_URI: str = ""

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")


config = Settings()
