"""Checkpointer factory — select persistence backend via env config.

Supported backends
------------------
* ``memory``   – :class:`MemorySaver` (sync + async, ephemeral)
* ``sqlite``   – :class:`AsyncSqliteSaver` (async, local-dev, file-based)
* ``postgres`` – :class:`AsyncPostgresSaver` (async, production)

Two factories are provided:

* :func:`create_checkpointer` — **sync**, always returns ``MemorySaver``.
  Used by the ``langgraph dev`` CLI and tests.
* :func:`create_async_checkpointer` — **async**, returns the backend
  specified by ``CHECKPOINTER``.  Used by the FastAPI server lifespan.
"""

from __future__ import annotations

from typing import Any

from src.config import config


def create_checkpointer() -> Any:
    """
    Return a sync-safe :class:`MemorySaver`.

    This is the only checkpointer that works in both sync and async
    contexts, making it safe for ``langgraph dev`` and unit tests.
    """
    from langgraph.checkpoint.memory import MemorySaver

    return MemorySaver()


async def create_async_checkpointer(backend: str | None = None) -> Any:
    """
    Return an **async-safe** checkpointer based on *backend*.

    Must be called inside an ``async`` context (e.g. FastAPI lifespan).
    Falls back to the ``CHECKPOINTER`` env-var, then ``"memory"``.
    """
    backend = (backend or config.CHECKPOINTER).lower().strip()

    match backend:
        case "memory":
            from langgraph.checkpoint.memory import MemorySaver

            return MemorySaver()

        case "sqlite":
            import aiosqlite

            from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver

            conn = await aiosqlite.connect(config.SQLITE_DB_PATH)
            return AsyncSqliteSaver(conn)

        case "postgres":
            from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver

            uri = config.POSTGRES_URI or None
            if not uri:
                raise ValueError(
                    "POSTGRES_URI env-var is required when CHECKPOINTER=postgres"
                )
            saver = AsyncPostgresSaver.from_conn_string(uri)
            await saver.asetup()  # creates tables on first use
            return saver

        case _:
            raise ValueError(
                f"Unknown checkpointer backend: {backend!r}.  "
                "Supported: 'memory', 'sqlite', 'postgres'."
            )
                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                            