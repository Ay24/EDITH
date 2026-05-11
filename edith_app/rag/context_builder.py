"""
edith_app.rag.context_builder
==============================
Assembles retrieved chunks and memory facts into a structured, token-budgeted
context block ready for LLM consumption.

Responsibilities
----------------
* Deduplicate chunks by text similarity (Jaccard on tokens)
* Merge document chunks + memory facts with clear section headers
* Inject source citations for provenance
* Respect a configurable maximum character budget
* Format context for EDITH's grounded prompt template
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass

from edith_app.rag.retrieval import RetrievedChunk
from edith_app.rag.memory import MemoryFact

logger = logging.getLogger("edith.rag.context_builder")


@dataclass
class BuiltContext:
    """Output of the context builder."""
    context_block: str        # Full formatted context string for LLM prompt
    doc_chunks_used: int      # Number of document chunks included
    memory_facts_used: int    # Number of memory facts included
    sources: list[str]        # List of source file names used
    char_count: int           # Total character count of context_block
    was_truncated: bool       # True if content was cut to fit budget


def _tokenise(text: str) -> set[str]:
    """Simple token set for Jaccard similarity (lowercase, alpha-numeric only)."""
    return set(re.findall(r"[a-z0-9]{3,}", text.lower()))


def _jaccard(a: set[str], b: set[str]) -> float:
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


def _deduplicate(
    chunks: list[RetrievedChunk],
    sim_threshold: float = 0.72,
) -> list[RetrievedChunk]:
    """
    Remove near-duplicate chunks using Jaccard similarity on token sets.
    Keeps the highest-scored chunk when duplicates are found.
    """
    kept: list[RetrievedChunk] = []
    kept_tokens: list[set[str]] = []

    for chunk in chunks:
        tokens = _tokenise(chunk.text)
        is_dup = any(_jaccard(tokens, kt) >= sim_threshold for kt in kept_tokens)
        if not is_dup:
            kept.append(chunk)
            kept_tokens.append(tokens)

    return kept


class ContextBuilder:
    """
    Merges document chunks and memory facts into a single formatted context block.

    Parameters
    ----------
    max_chars        : character budget for the entire context block
    dedup_threshold  : Jaccard threshold above which two chunks are considered duplicates
    include_scores   : whether to append retrieval scores in the output (useful for debug)
    """

    SECTION_DOCS = "## Relevant Knowledge"
    SECTION_MEMORY = "## Your Memory Context"

    def __init__(
        self,
        max_chars: int = 6000,
        dedup_threshold: float = 0.72,
        include_scores: bool = False,
    ) -> None:
        self._max_chars = max_chars
        self._dedup_threshold = dedup_threshold
        self._include_scores = include_scores

    # ── Public API ────────────────────────────────────────────────────────────

    def build(
        self,
        query: str,
        doc_chunks: list[RetrievedChunk],
        memory_facts: list[MemoryFact],
        ranked_chunks: list | None = None,
    ) -> BuiltContext:
        """
        Assemble the context block.

        Parameters
        ----------
        query         : original user query (used for logging)
        doc_chunks    : retrieved document chunks (post-MMR)
        memory_facts  : retrieved memory facts
        ranked_chunks : if provided (from reranker), use this ordering instead
        """
        # Use reranked chunks if available, else raw retrieval order
        if ranked_chunks is not None:
            # ranked_chunks is list[RankedChunk]
            ordered = [rc.chunk for rc in ranked_chunks]
        else:
            ordered = sorted(doc_chunks, key=lambda c: c.score, reverse=True)

        # Deduplicate
        deduped = _deduplicate(ordered, sim_threshold=self._dedup_threshold)

        # Build document section
        doc_lines: list[str] = []
        sources_used: list[str] = []
        budget = self._max_chars
        was_truncated = False

        for chunk in deduped:
            label = f"[Source: {chunk.source_name}, chunk {chunk.chunk_index + 1}]"
            if self._include_scores:
                label += f" (score={chunk.score:.2f})"
            entry = f"{label}\n{chunk.text}"
            if len(entry) + 2 > budget:
                was_truncated = True
                # Try to include a truncated version if at least 200 chars remain
                if budget > 200:
                    entry = entry[: budget - 4] + " ..."
                    doc_lines.append(entry)
                    sources_used.append(chunk.source_name)
                break
            doc_lines.append(entry)
            if chunk.source_name and chunk.source_name not in sources_used:
                sources_used.append(chunk.source_name)
            budget -= len(entry) + 2  # 2 for newlines

        # Build memory section
        mem_lines: list[str] = []
        for fact in memory_facts:
            label = f"[Memory: {fact.category}]"
            entry = f"{label} {fact.text}"
            if len(entry) + 2 > budget:
                was_truncated = True
                break
            mem_lines.append(entry)
            budget -= len(entry) + 2

        # Assemble final context block
        parts: list[str] = []

        if doc_lines:
            parts.append(self.SECTION_DOCS)
            parts.extend(doc_lines)

        if mem_lines:
            parts.append(self.SECTION_MEMORY)
            parts.extend(mem_lines)

        if not parts:
            context_block = "[No relevant context found in knowledge base]"
        else:
            context_block = "\n\n".join(parts)

        result = BuiltContext(
            context_block=context_block,
            doc_chunks_used=len(doc_lines),
            memory_facts_used=len(mem_lines),
            sources=sources_used,
            char_count=len(context_block),
            was_truncated=was_truncated,
        )

        logger.debug(
            "Context built for '%s': %d doc chunks, %d memory facts, %d chars%s",
            query[:50],
            result.doc_chunks_used,
            result.memory_facts_used,
            result.char_count,
            " [TRUNCATED]" if was_truncated else "",
        )
        return result

    def format_for_prompt(self, context: BuiltContext, query: str) -> str:
        """
        Wrap the context block in a grounded prompt template.

        The template instructs the LLM to answer ONLY from the provided context,
        preventing hallucination on knowledge-base queries.
        """
        sources_note = ""
        if context.sources:
            sources_note = f"\nSources consulted: {', '.join(context.sources)}"

        return (
            "You are EDITH, an intelligent assistant. "
            "Answer the question below STRICTLY using the provided context. "
            "If the answer is not present in the context, say: "
            "'I don't have that information in my knowledge base.' "
            "Do NOT fabricate facts. Be concise and natural.\n\n"
            f"{context.context_block}"
            f"{sources_note}\n\n"
            f"Question: {query}\n"
            "Answer:"
        )
