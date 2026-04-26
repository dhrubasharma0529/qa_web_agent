"""DOM Context-Window Management.

Handles the full pipeline:
    extract → filter → token-count → chunk → summarise → merge

Large SPA pages can have 10K+ elements.  This utility ensures we
never blow the LLM context window by using a map-reduce approach
with tiktoken-aware chunking.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from typing import Optional

import tiktoken
from langchain_core.documents import Document
from langchain_core.language_models import BaseChatModel
from langchain_core.prompts import ChatPromptTemplate
from langchain_text_splitters import (
    HTMLHeaderTextSplitter,
    RecursiveCharacterTextSplitter,
)

from src.browser.playwright_adapter import PlaywrightAdapter
from src.config import config

logger = logging.getLogger(__name__)

# ── Data ────────────────────────────────────────────────────


@dataclass
class DOMChunk:
    """A single token-bounded slice of filtered DOM content."""

    content: str
    token_count: int
    metadata: dict = field(default_factory=dict)
    summary: Optional[str] = None


# ── Prompts ─────────────────────────────────────────────────

_CHUNK_SUMMARY_PROMPT = ChatPromptTemplate.from_messages(
    [
        (
            "system",
            "You are a senior QA engineer analysing a DOM section for test planning. "
            "Be concise and focus on testable behaviour.",
        ),
        (
            "human",
            "Analyse the following DOM section and provide:\n"
            "1. Interactive elements with their best selectors\n"
            "2. User actions possible (click, type, select, navigate …)\n"
            "3. Expected behaviours / state changes\n\n"
            "Section metadata: {section_metadata}\n\n"
            "DOM content:\n```html\n{chunk_content}\n```",
        ),
    ]
)

_MERGE_PROMPT = ChatPromptTemplate.from_messages(
    [
        (
            "system",
            "You are a senior QA architect building a complete picture of a "
            "web application for automated test planning.",
        ),
        (
            "human",
            "Combine the following section summaries into a **unified page analysis**.\n\n"
            "Section summaries:\n{all_summaries}\n\n"
            "Produce:\n"
            "1. Page structure overview (navigation, main content, footer, modals)\n"
            "2. Complete list of interactive elements with recommended selectors\n"
            "3. Key user flows identifiable from the DOM\n"
            "4. Recommended test scenarios (smoke, regression, edge-case)",
        ),
    ]
)

# ── JS for filtered DOM extraction ──────────────────────────

_EXTRACT_FILTERED_HTML_JS = """
() => {
    const SELECTORS = [
        'button', 'a[href]', 'input', 'select', 'textarea', 'form',
        '[role]', '[data-testid]', '[data-cy]', '[aria-label]',
        'h1', 'h2', 'h3', 'h4', 'h5', 'h6', 'label',
        'nav', 'main', 'header', 'footer'
    ];
    const seen = new Set();
    const lines = [];
    for (const el of document.querySelectorAll(SELECTORS.join(','))) {
        if (seen.has(el) || el.offsetParent === null) continue;
        seen.add(el);
        const tag = el.tagName.toLowerCase();
        const attrs = {};
        for (const a of ['id','name','type','href','role','aria-label',
                          'data-testid','data-cy','placeholder','value']) {
            const v = el.getAttribute(a);
            if (v) attrs[a] = v;
        }
        const text = (el.textContent || '').trim().slice(0, 100);
        const attrStr = Object.entries(attrs).map(([k,v]) => `${k}="${v}"`).join(' ');
        lines.push(`<${tag} ${attrStr}>${text}</${tag}>`);
    }
    return lines.join('\\n');
}
"""


class DOMProcessor:
    """
    Processes large SPA DOMs into LLM-friendly chunks for QA analysis.

    Parameters
    ----------
    max_chunk_tokens : int
        Maximum tokens per chunk (default 4 000).
    chunk_overlap : int
        Token overlap between consecutive chunks (default 200).
    model_name : str
        OpenAI model name for tiktoken encoding lookup.
    concurrency : int
        Max parallel LLM calls during the map phase.
    """

    HEADERS_TO_SPLIT = [
        ("h1", "Page Section"),
        ("h2", "Sub Section"),
        ("h3", "Component"),
    ]

    def __init__(
        self,
        max_chunk_tokens: int = 4_000,
        chunk_overlap: int = 200,
        model_name: str | None = None,
        concurrency: int = 5,
    ):
        self.max_chunk_tokens = max_chunk_tokens
        self.chunk_overlap = chunk_overlap
        self.model_name = model_name or config.LLM_MODEL
        self._concurrency = concurrency

        # Lazy-init: tiktoken does blocking I/O (os.getcwd via tempfile)
        # which triggers blockbuster in langgraph dev.  Defer to first use.
        self._encoder = None
        self._html_splitter = HTMLHeaderTextSplitter(
            headers_to_split_on=self.HEADERS_TO_SPLIT,
        )
        self._token_splitter = None  # also deferred (uses tiktoken)

    @property
    def encoder(self):
        """Lazy-load tiktoken encoder on first access."""
        if self._encoder is None:
            self._encoder = tiktoken.encoding_for_model(self.model_name)
        return self._encoder

    @property
    def token_splitter(self):
        """Lazy-load the token-aware text splitter on first access."""
        if self._token_splitter is None:
            self._token_splitter = RecursiveCharacterTextSplitter.from_tiktoken_encoder(
                model_name=self.model_name,
                chunk_size=self.max_chunk_tokens,
                chunk_overlap=self.chunk_overlap,
                separators=["\n\n", "\n", ". ", " ", ""],
            )
        return self._token_splitter

    # ── Token helpers ───────────────────────────────────────

    def count_tokens(self, text: str) -> int:
        """Return exact token count for the configured model."""
        return len(self.encoder.encode(text))

    def needs_chunking(self, text: str) -> bool:
        """Return ``True`` if *text* exceeds ``max_chunk_tokens``."""
        return self.count_tokens(text) > self.max_chunk_tokens

    # ── DOM extraction ──────────────────────────────────────

    async def extract_dom(self, adapter: PlaywrightAdapter) -> str:
        """
        Extract filtered HTML from the current page via the adapter.

        Only interactive and meaningful elements are kept; ``<script>``,
        ``<style>``, ``<svg>`` and hidden elements are stripped at the
        browser level (see JS snippet).
        """
        return await adapter.evaluate_js(_EXTRACT_FILTERED_HTML_JS.strip())

    # ── Chunking ────────────────────────────────────────────

    def chunk_dom(self, html: str) -> list[DOMChunk]:
        """
        Two-tier split:
            1. Structural split by HTML headers (h1/h2/h3).
            2. Token-aware split to enforce ``max_chunk_tokens``.
        """
        # Tier 1 — structural
        try:
            header_docs: list[Document] = self._html_splitter.split_text(html)
        except Exception:
            # If HTML has no headers, wrap in a single Document
            header_docs = [Document(page_content=html)]

        # Tier 2 — token-aware sub-splits
        final_docs: list[Document] = self.token_splitter.split_documents(header_docs)

        chunks: list[DOMChunk] = []
        for doc in final_docs:
            content = doc.page_content
            chunks.append(
                DOMChunk(
                    content=content,
                    token_count=self.count_tokens(content),
                    metadata=doc.metadata,
                )
            )

        logger.info(
            "DOM chunked into %d pieces (total tokens ≈ %d)",
            len(chunks),
            sum(c.token_count for c in chunks),
        )
        return chunks

    # ── Map phase: summarise each chunk ─────────────────────

    async def summarize_chunks(
        self,
        chunks: list[DOMChunk],
        llm: BaseChatModel,
    ) -> list[DOMChunk]:
        """Summarise each chunk in parallel (capped by ``concurrency``)."""
        sem = asyncio.Semaphore(self._concurrency)
        chain = _CHUNK_SUMMARY_PROMPT | llm

        async def _summarise_one(chunk: DOMChunk) -> None:
            async with sem:
                result = await chain.ainvoke(
                    {
                        "section_metadata": str(chunk.metadata),
                        "chunk_content": chunk.content,
                    }
                )
                chunk.summary = result.content  # type: ignore[union-attr]

        await asyncio.gather(*[_summarise_one(c) for c in chunks])
        return chunks

    # ── Reduce phase: merge summaries ───────────────────────

    async def merge_summaries(
        self,
        chunks: list[DOMChunk],
        llm: BaseChatModel,
    ) -> str:
        """Combine all chunk summaries into a single unified page analysis."""
        all_summaries = "\n---\n".join(
            f"[Section {i + 1}] {c.summary}" for i, c in enumerate(chunks) if c.summary
        )
        chain = _MERGE_PROMPT | llm
        result = await chain.ainvoke({"all_summaries": all_summaries})
        return result.content  # type: ignore[union-attr]

    # ── Full pipeline ───────────────────────────────────────

    async def process_page(
        self,
        adapter: PlaywrightAdapter,
        llm: BaseChatModel,
    ) -> str:
        """
        End-to-end: extract → chunk → summarise → merge.

        If the filtered DOM fits within a single chunk, it is
        returned directly (no LLM round-trips needed).
        """
        raw_dom = await self.extract_dom(adapter)

        if not self.needs_chunking(raw_dom):
            logger.info(
                "DOM fits in one chunk (%d tokens) — skipping map-reduce",
                self.count_tokens(raw_dom),
            )
            return raw_dom

        chunks = self.chunk_dom(raw_dom)
        chunks = await self.summarize_chunks(chunks, llm)
        merged = await self.merge_summaries(chunks, llm)
        return merged
