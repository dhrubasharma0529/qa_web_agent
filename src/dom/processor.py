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
            "You are a senior QA engineer analysing a DOM section for test planning.\n"
            "The section may belong to ANY kind of web product: marketing site, blog, "
            "e-commerce, SaaS dashboard, admin console, social feed, media player, "
            "single-page app, multi-step wizard, documentation, search UI, auth flow, "
            "data table, file uploader, chat, map, calendar, payments, etc.\n\n"
            "Do NOT assume a fixed page skeleton (header/main/footer). Describe ONLY "
            "what is actually present in this section. Use neutral language. Skip any "
            "category that has zero evidence in the DOM rather than inventing it.\n\n"
            "Ground every selector in the DOM verbatim — never guess attribute values. "
            "Be concise and focused on testable behaviour.",
        ),
        (
            "human",
            "Analyse the DOM section below and produce a structured summary.\n\n"
            "Section metadata: {section_metadata}\n\n"
            "DOM content:\n```html\n{chunk_content}\n```\n\n"
            "Cover the following — OMIT any item that does not apply:\n"
            "1. **Section role** — what this slice appears to do (one short line; "
            "   e.g. login form, product grid, settings panel, comment thread, video "
            "   player, filter sidebar, error state, empty state). Infer from the DOM, "
            "   not from assumptions.\n"
            "2. **Interactive elements** — list each one with its best selector "
            "   (prefer in order: data-cy → data-testid → id → unique aria-label → "
            "   role+name → stable attribute combo). Quote attribute values verbatim.\n"
            "3. **User actions** — concrete actions the DOM supports "
            "   (click, type, upload, drag, hover, keyboard navigation, scroll, "
            "   pagination, filter, sort, submit, copy, share, play/pause, etc.).\n"
            "4. **Expected behaviours / state changes** — visible or implied "
            "   (validation, navigation, modal open, toast, loading, optimistic "
            "   update, async fetch, redirect, download, auth gate, etc.).\n"
            "5. **Notable signals** — anything testers should know: "
            "   missing labels, duplicate IDs, dynamic IDs, iframe boundaries, "
            "   shadow DOM hints, role/aria mismatches, third-party widgets, "
            "   media autoplay, CAPTCHA, rate limits, paywalls.",
        ),
    ]
)

_MERGE_PROMPT = ChatPromptTemplate.from_messages(
    [
        (
            "system",
            "You are a senior QA architect assembling a unified picture of a web "
            "application from per-section summaries. The application could be ANY "
            "kind of site or app — make no assumptions about its layout, framework, "
            "or domain. Adapt your output to the evidence you actually have.\n\n"
            "Be exhaustive about what IS present and silent about what is not. "
            "Never fabricate elements, flows, or selectors that do not appear in the "
            "summaries.",
        ),
        (
            "human",
            "Section summaries:\n{all_summaries}\n\n"
            "Produce a **unified page analysis** with the sections below. "
            "Skip any section that has no evidence; do not pad with placeholders.\n\n"
            "1. **Page identity** — one paragraph: what kind of page/app this is, "
            "   its apparent primary purpose, and the dominant UI patterns observed "
            "   (e.g. CRUD table, content feed, checkout funnel, dashboard, "
            "   onboarding wizard, search-centric, media-centric, form-centric).\n"
            "2. **Structural map** — the regions actually found in the DOM "
            "   (use the labels the DOM suggests; do NOT force a header/main/footer "
            "   template if it is not present). Note modals, drawers, popovers, "
            "   iframes, and shadow roots if observed.\n"
            "3. **Interactive inventory** — consolidated, deduplicated list of every "
            "   interactive element with a verified selector and its purpose. Group "
            "   by region or feature for readability.\n"
            "4. **User flows** — end-to-end paths the DOM supports (e.g. sign-in, "
            "   add-to-cart, filter+sort, create-record, multi-step submit). Only "
            "   list flows whose required elements are actually present.\n"
            "5. **Test scenarios** — recommended coverage tiered as: smoke "
            "   (critical happy paths), regression (feature breadth), edge cases "
            "   (validation, empty/error/loading states, boundaries, accessibility, "
            "   responsive/keyboard, network failure, auth/permission gates). "
            "   Tailor categories to what this specific app actually exposes.\n"
            "6. **Risks & gaps** — testability concerns surfaced across sections "
            "   (dynamic selectors, missing test hooks, hidden state, third-party "
            "   embeds, race conditions, observability gaps).",
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
