# EDITH AI System — Knowledge Base

## Overview

EDITH (Enhanced Desktop Intelligence and Task Handler) is a production-quality
autonomous desktop AI assistant. It combines voice control, local LLM inference
via Ollama, a multi-agent task system, and a Retrieval-Augmented Generation (RAG)
knowledge base.

---

## Architecture

EDITH's core components:

- **Voice Layer**: Speech-to-text via Vosk (offline) or SpeechRecognition. Converts
  spoken commands into text queries routed to the intelligence engine.

- **Neural Engine**: Classifies intent complexity (simple / medium / deep) and selects
  the optimal Ollama model per request.

- **Jarvis Brain**: High-speed intent router that classifies queries into lanes:
  chat, cowork, media, system, memory.

- **Agent Service**: Manages all Ollama HTTP communication with retry logic,
  model fallback, and async recovery.

- **RAG Pipeline**: Retrieval-Augmented Generation subsystem for answering
  questions from documents. Uses ChromaDB with BGE-small embeddings, MMR
  retrieval, cross-encoder re-ranking, and grounded Ollama generation.

- **Memory System**: Two-tier memory — MemoryService (JSONL, TF-IDF) for
  structured conversation history, and RAGMemory (ChromaDB) for long-term
  semantic user facts.

- **Task Engine**: Personal task management with priority, status tracking,
  due-date detection, and a graphical dashboard.

- **Tool Router**: Routes commands to 10+ specialized lanes: files, media,
  browser, audio, system, notes, WhatsApp, cowork, agent, and knowledge.

---

## RAG Knowledge Base

### How It Works

1. Drop documents (.txt, .md, .pdf) into the `docs/` folder.
2. Run `python scripts/ingest_docs.py` to index them.
3. Ask EDITH: "ask docs what is the project architecture?"

### Trigger Phrases

Say any of these to query the knowledge base:

- "ask docs <question>"
- "search knowledge base <question>"
- "from my documents <question>"
- "what does my document say about <topic>"
- "knowledge base status" — shows stats

### RAG Pipeline Stages

1. **Query Expansion** — generates alternative rephrasings for better recall
2. **MMR Retrieval** — ChromaDB cosine search with diversity selection
3. **Cross-encoder Re-ranking** — ms-marco-MiniLM-L-6-v2 scores passage relevance
4. **Context Building** — deduplicates and formats chunks with source citations
5. **Grounded Generation** — Ollama answers strictly from provided context
6. **Memory Storage** — persists the interaction for future context

---

## Voice Commands Reference

### General
- "help" — list capabilities
- "status" — system status report
- "knowledge base status" — RAG stats

### System Control
- "lock pc", "sleep pc", "shutdown pc", "restart pc"
- "set volume to 70", "volume up", "volume down", "mute"
- "set brightness to 80"
- "wifi on / off", "bluetooth on / off"

### Media
- "play <song> on YouTube", "open Spotify"
- "play <track> on Spotify"
- "open YouTube", "open Google", "open GitHub"

### Files
- "organize desktop", "organize downloads"
- "analyze desktop", "find file <name>"
- "open folder <path>"

### Tasks
- "add task <title>", "show tasks", "next task"
- "complete task <title>", "delete task <title>"
- "task dashboard"

### AI Cowork
- "cowork on <goal>" — multi-step autonomous coding/planning task
- "brainstorm <topic>"
- "plan <topic>"
- "think with me about <topic>"

### Knowledge Base
- "ask docs <question>"
- "search knowledge base <question>"
- "from my documents <question>"

---

## Setup and Requirements

### Core Requirements
- Python 3.11+
- Ollama (for local LLM) with phi3, mistral, or llama3
- Windows OS (for system control features)

### RAG Requirements (optional but recommended)
```
pip install chromadb sentence-transformers pypdf
```

### Quick Start
```bash
# 1. Install core deps
pip install -r requirements.txt

# 2. Install RAG deps
pip install -r requirements_rag.txt

# 3. Add your documents to docs/
# 4. Ingest them
python scripts/ingest_docs.py

# 5. Start EDITH
python main.py
```

---

## Configuration

All settings are controlled via environment variables or AppConfig defaults:

| Variable | Default | Description |
|---|---|---|
| OLLAMA_MODEL | phi3 | Default Ollama model |
| EDITH_RAG_ENABLED | 1 | Enable/disable RAG |
| EDITH_RAG_DOCS_DIR | docs/ | Knowledge base source folder |
| EDITH_RAG_DB_PATH | data/rag_chroma | ChromaDB persistence path |
| EDITH_RAG_EMBED_MODEL | BAAI/bge-small-en-v1.5 | Embedding model |
| EDITH_RAG_RERANK_MODEL | cross-encoder/ms-marco-MiniLM-L-6-v2 | Re-ranking model |
| EDITH_RAG_RETRIEVAL_K | 6 | Chunks retrieved per query |

---

## Developer Notes

- The RAG package lives at `edith_app/rag/` and is fully modular
- All RAG dependencies are soft-optional (EDITH runs without them)
- ChromaDB data is persisted in `data/rag_chroma/`
- Embeddings are computed offline using sentence-transformers (no cloud API)
- The cross-encoder runs on CPU and scores in ~50-150ms for 6 candidates
