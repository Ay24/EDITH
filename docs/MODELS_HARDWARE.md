# Models for GTX 1650 4GB + 16GB RAM (Ryzen 5600H)

Goal: one **resident** LLM on GPU (~3–3.5GB), everything else on **CPU**.

## Primary LLM (pick one)

| Model | Ollama tag (examples) | Notes |
|-------|----------------------|--------|
| **Llama 3.2 3B** | `llama3.2` / `llama3.2:3b` | Safe default; good tone; solid tools with good prompts |
| **Qwen 2.5 3B Instruct** | `qwen2.5:3b` | Often **best tool JSON** at this size; try for hardest automation |
| **Gemma 2 2B** | `gemma2:2b` | Fastest; use if VRAM tight or multitasking heavy |

Set in `.env`:

```env
OLLAMA_MODEL=qwen2.5:3b
EDITH_PLANNER_MODEL=qwen2.5:3b
EDITH_FAST_MODEL=gemma2:2b
EDITH_COMPLEX_MODEL=qwen2.5:3b
```

Keeping **one** heavy model loaded avoids VRAM thrash. Optional second small model only if you have headroom.

## Vision (optional, on demand)

| Model | Notes |
|-------|--------|
| `llava:7b` | Often **too large** for 4GB alongside 3B chat |
| `moondream` / tiny VLMs | Prefer small multimodal or **skip vision** when gaming |

Use vision only when triggered; it is never “always on.”

## Speech

| Role | Recommendation |
|------|----------------|
| STT | **Vosk** (current) — CPU, offline |
| Upgrade path | `faster-whisper` **small** or **base** on CPU for accuracy (more RAM/CPU) |
| Wake | **openWakeWord** (CPU ONNX) |

## TTS

| Engine | Notes |
|--------|--------|
| **Kokoro** (current) | CPU ONNX; good latency |

## Embeddings / RAG

| Component | Current | Notes |
|-----------|---------|--------|
| Embed | `BAAI/bge-base-en-v1.5` | CPU; 768-dim; fine for 16GB |
| Rerank | `cross-encoder/ms-marco-MiniLM-L-6-v2` | CPU; optional on long docs |

## Native path

`launch_adaptive.py` + **llama.cpp** GGUF **Q4** ~3B often beats Ollama for **steady** latency on one GPU.

## What to avoid on this laptop

- 7B+ LLMs as the always-on model (VRAM + system stutter)
- Multiple large models + vision + game simultaneously
- Huge context (`num_ctx` 8192+) unless you need it

Pull commands:

```bash
ollama pull llama3.2
ollama pull qwen2.5:3b
ollama pull gemma2:2b
```

Tune `EDITH_NEURAL_MAX_STEPS_VOICE` down for voice; use `qwen2.5:3b` when tool reliability matters most.
