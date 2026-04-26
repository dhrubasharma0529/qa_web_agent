"""Smoke test for the /health endpoint.

We call the handler directly rather than going through FastAPI's
TestClient so the app's `lifespan` (which starts a Playwright browser
and a background docs-refresh task) does not run. For CI all we need
to prove is: imports work, the handler returns the expected payload.
"""

import pytest

from src.server import health


@pytest.mark.asyncio
async def test_health_returns_ok():
    result = await health()
    assert result == {"status": "ok"}
