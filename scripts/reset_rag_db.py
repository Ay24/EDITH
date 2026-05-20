"""
scripts/reset_rag_db.py
=======================
One-time migration: delete the old nomic-embed-text ChromaDB (768-dim,
Ollama GPU) and rebuild using BAAI/bge-base-en-v1.5 (768-dim, CPU-only).

Run this ONCE after updating config.py:
    python scripts/reset_rag_db.py

This is necessary because the embedding SPACE changed (different model),
even though the vector dimension (768) is the same.
"""
import shutil
import sys
from pathlib import Path

# ── Locate the ChromaDB directory ─────────────────────────────────────────────
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

try:
    from edith_app.config import AppConfig
    cfg = AppConfig()
    chroma_path = Path(cfg.rag_db_path)
    docs_dir = Path(cfg.rag_docs_dir)
    embed_model = cfg.rag_embed_model
except Exception as e:
    print(f"[WARN] Could not load AppConfig ({e}), using defaults.")
    chroma_path = ROOT / "data" / "rag_chroma"
    docs_dir = ROOT / "docs"
    embed_model = "BAAI/bge-base-en-v1.5"

print("=" * 60)
print("  EDITH RAG Database Reset")
print("=" * 60)
print(f"  ChromaDB path : {chroma_path}")
print(f"  Embed model   : {embed_model} (CPU-only)")
print(f"  Docs dir      : {docs_dir}")
print()

# ── Delete old ChromaDB ────────────────────────────────────────────────────────
if chroma_path.exists():
    confirm = input(f"Delete {chroma_path}? (yes/no): ").strip().lower()
    if confirm != "yes":
        print("Aborted.")
        sys.exit(0)
    shutil.rmtree(chroma_path)
    print(f"[OK] Deleted {chroma_path}")
else:
    print(f"[INFO] {chroma_path} does not exist, nothing to delete.")

# ── Re-ingest documents ────────────────────────────────────────────────────────
if not docs_dir.exists() or not any(docs_dir.rglob("*")):
    print(f"[INFO] No docs found in {docs_dir} — skipping ingestion.")
    print("       Add files and run: python scripts/ingest_docs.py")
    sys.exit(0)

print(f"\n[INFO] Re-ingesting from {docs_dir} with model {embed_model}...")
try:
    from edith_app.rag.pipeline import RAGPipeline
    pipeline = RAGPipeline(
        chroma_path=str(chroma_path),
        embed_model=embed_model,
        ollama_url=cfg.ollama_url,
        ollama_model=cfg.ollama_model,
    )
    result = pipeline.ingest(str(docs_dir), reset=True)
    print(f"[OK] Ingestion complete: {result}")
except Exception as exc:
    print(f"[ERROR] Ingestion failed: {exc}")
    print("       Run manually: python scripts/ingest_docs.py")

print("\n[DONE] RAG database rebuilt with CPU embedder.")
print("       Start EDITH normally: python main.py")
