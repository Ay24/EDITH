#!/usr/bin/env python3
"""
scripts/ingest_docs.py
======================
Standalone CLI tool to ingest documents into EDITH's RAG knowledge base.

Usage
-----
    # Ingest all docs from the default docs/ folder
    python scripts/ingest_docs.py

    # Ingest from a custom folder
    python scripts/ingest_docs.py --docs-dir path/to/my/docs

    # Full reset (delete and rebuild the vector DB)
    python scripts/ingest_docs.py --reset

    # Check knowledge base stats only
    python scripts/ingest_docs.py --stats

    # Ingest a single text file
    python scripts/ingest_docs.py --file path/to/doc.txt --source-name my-doc

Example output
--------------
    [EDITH RAG] Ingesting from: docs/
    [EDITH RAG] Found 3 file(s): readme.md, notes.txt, project.pdf
    [EDITH RAG] Ingested readme.md → 4 chunks
    [EDITH RAG] Ingested notes.txt → 7 chunks
    [EDITH RAG] Ingested project.pdf → 12 chunks
    [EDITH RAG] Done: 3 files, 23 chunks in 4.2s
    [EDITH RAG] Total chunks in KB: 23 | Memory facts: 0
"""
from __future__ import annotations

import argparse
import os
import sys
import time
from pathlib import Path

# ── Ensure the project root is on sys.path ───────────────────────────────────
_SCRIPTS_DIR = Path(__file__).resolve().parent
_PROJECT_ROOT = _SCRIPTS_DIR.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

# Change cwd to project root so relative paths (data/, docs/) work correctly
os.chdir(_PROJECT_ROOT)


def _print(msg: str) -> None:
    print(f"[EDITH RAG] {msg}", flush=True)


def _check_deps() -> bool:
    """Verify that required dependencies are installed."""
    missing = []
    try:
        import chromadb  # noqa: F401
    except ImportError:
        missing.append("chromadb")
    try:
        import sentence_transformers  # noqa: F401
    except ImportError:
        missing.append("sentence-transformers")
    if missing:
        _print(f"Missing dependencies: {', '.join(missing)}")
        _print("Install with: pip install " + " ".join(missing))
        return False
    return True


def cmd_ingest(args: argparse.Namespace) -> int:
    """Run directory ingestion."""
    from edith_app.config import AppConfig
    from edith_app.rag.ingestion import DocumentIngester

    cfg = AppConfig()
    docs_dir = Path(args.docs_dir or cfg.rag_docs_dir)
    db_path = args.db_path or cfg.rag_db_path
    embed_model = args.embed_model or cfg.rag_embed_model

    if not docs_dir.exists():
        _print(f"docs-dir not found: {docs_dir}")
        _print("Create the directory and add .txt, .md, or .pdf files to it.")
        return 1

    supported = {".txt", ".md", ".pdf", ".rst", ".text"}
    files = [f for f in docs_dir.rglob("*") if f.is_file() and f.suffix.lower() in supported]
    if not files:
        _print(f"No supported files found in {docs_dir}")
        _print("Supported formats: .txt .md .pdf .rst")
        return 0

    _print(f"Ingesting from: {docs_dir}")
    _print(f"Found {len(files)} file(s): {', '.join(f.name for f in files[:5])}" +
           (" ..." if len(files) > 5 else ""))
    _print(f"Vector DB path: {db_path}")
    _print(f"Embedding model: {embed_model}")
    if args.reset:
        _print("RESET mode: existing knowledge base will be cleared")

    ingester = DocumentIngester(
        chroma_path=db_path,
        embed_model=embed_model,
        target_tokens=500,
        overlap_tokens=80,
    )

    t0 = time.monotonic()
    stats = ingester.ingest_directory(docs_dir, reset=args.reset)
    elapsed = time.monotonic() - t0

    _print(f"Done: {stats.files_processed} files processed, {stats.files_skipped} skipped, "
           f"{stats.files_failed} failed")
    _print(f"Chunks added: {stats.chunks_added} in {elapsed:.1f}s")
    _print(f"Total chunks in KB: {ingester.chunk_count()}")

    if stats.errors:
        _print("Errors:")
        for err in stats.errors:
            _print(f"  - {err}")

    return 0 if stats.files_failed == 0 else 1


def cmd_ingest_file(args: argparse.Namespace) -> int:
    """Ingest a single file."""
    from edith_app.config import AppConfig
    from edith_app.rag.ingestion import DocumentIngester, _load_file, _clean_text  # type: ignore

    cfg = AppConfig()
    fp = Path(args.file)
    if not fp.exists():
        _print(f"File not found: {fp}")
        return 1

    db_path = args.db_path or cfg.rag_db_path
    embed_model = args.embed_model or cfg.rag_embed_model
    source_name = args.source_name or fp.stem

    _print(f"Ingesting file: {fp.name} as '{source_name}'")
    ingester = DocumentIngester(chroma_path=db_path, embed_model=embed_model)

    try:
        raw = _load_file(fp)
        cleaned = _clean_text(raw)
        n = ingester.ingest_text(cleaned, source_name=source_name)
        _print(f"Done: {n} chunks stored for '{source_name}'")
        _print(f"Total chunks in KB: {ingester.chunk_count()}")
    except Exception as exc:
        _print(f"Failed: {exc}")
        return 1
    return 0


def cmd_stats(args: argparse.Namespace) -> int:
    """Show knowledge base statistics."""
    from edith_app.config import AppConfig
    from edith_app.rag.pipeline import RAGPipeline

    cfg = AppConfig()
    db_path = args.db_path or cfg.rag_db_path
    embed_model = args.embed_model or cfg.rag_embed_model

    _print(f"Checking knowledge base at: {db_path}")
    try:
        pipeline = RAGPipeline(
            chroma_path=db_path,
            embed_model=embed_model,
            ollama_model=cfg.ollama_model,
        )
        s = pipeline.knowledge_base_stats()
        _print(f"Document chunks : {s.get('doc_chunks', 0)}")
        _print(f"Memory facts    : {s.get('memory_facts', 0)}")
        _print(f"Retriever ready : {s.get('retriever_ready', False)}")
        _print(f"Re-ranker ready : {s.get('reranker_ready', False)}")
    except Exception as exc:
        _print(f"Could not read stats: {exc}")
        return 1
    return 0


def cmd_query(args: argparse.Namespace) -> int:
    """Run a test RAG query directly from the CLI."""
    from edith_app.config import AppConfig
    from edith_app.rag.pipeline import RAGPipeline

    cfg = AppConfig()
    db_path = args.db_path or cfg.rag_db_path
    embed_model = args.embed_model or cfg.rag_embed_model

    _print(f"Running RAG query: '{args.question}'")
    try:
        pipeline = RAGPipeline(
            chroma_path=db_path,
            embed_model=embed_model,
            ollama_url=cfg.ollama_url,
            ollama_model=cfg.ollama_model,
        )
        result = pipeline.query(args.question)
        print("\n" + "="*60)
        print(f"Answer:\n{result.answer}")
        print("="*60)
        print(f"Sources: {', '.join(result.sources) if result.sources else 'none'}")
        print(f"Chunks used: {result.doc_chunks_used} | Memory facts: {result.memory_facts_used}")
        print(f"Latency: {result.latency_ms:.0f}ms | Grounded: {result.was_grounded}")
    except Exception as exc:
        _print(f"Query failed: {exc}")
        return 1
    return 0


# ── CLI entry point ───────────────────────────────────────────────────────────

def main() -> int:
    parser = argparse.ArgumentParser(
        description="EDITH RAG — Knowledge Base Management CLI",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    # Shared options
    parser.add_argument("--db-path", default=None, help="Override ChromaDB path")
    parser.add_argument("--embed-model", default=None, help="Override embedding model")

    subparsers = parser.add_subparsers(dest="command", help="Command to run")

    # ingest (default)
    p_ingest = subparsers.add_parser("ingest", help="Ingest a directory of documents (default)")
    p_ingest.add_argument("--docs-dir", default=None, help="Directory containing documents")
    p_ingest.add_argument("--reset", action="store_true", help="Clear and rebuild the knowledge base")

    # ingest-file
    p_file = subparsers.add_parser("ingest-file", help="Ingest a single file")
    p_file.add_argument("--file", required=True, help="Path to the file")
    p_file.add_argument("--source-name", default=None, help="Override source name")

    # stats
    subparsers.add_parser("stats", help="Show knowledge base statistics")

    # query
    p_query = subparsers.add_parser("query", help="Run a test RAG query")
    p_query.add_argument("question", help="Question to ask the knowledge base")

    # Parse args — default to 'ingest' if no subcommand given
    args = parser.parse_args()
    if args.command is None:
        args.command = "ingest"
        args.docs_dir = None
        args.reset = False

    if not _check_deps():
        return 1

    if args.command == "ingest":
        return cmd_ingest(args)
    elif args.command == "ingest-file":
        return cmd_ingest_file(args)
    elif args.command == "stats":
        return cmd_stats(args)
    elif args.command == "query":
        return cmd_query(args)
    else:
        parser.print_help()
        return 1


if __name__ == "__main__":
    sys.exit(main())
