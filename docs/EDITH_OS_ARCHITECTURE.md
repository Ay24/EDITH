# EDITH OS — Production Architecture (Lenovo IdeaPad Gaming 3)

Principal-engineering blueprint for a local-first AI operating layer inspired by J.A.R.V.I.S., EDITH, and FRIDAY — optimized for **Ryzen 5 5600H**, **GTX 1650 4GB**, **16GB RAM**, **Windows 11**, **120Hz display**.

---

## 1. Scalable architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                     EDITH ORBIT (Presentation)                   │
│  Tkinter HUD · waveform · partial transcript · 120Hz motion      │
└────────────────────────────┬────────────────────────────────────┘
                             │ events / voice_queue
┌────────────────────────────▼────────────────────────────────────┐
│                  EdithAssistant (Orchestration)                  │
│  L0a smalltalk → L0a.5 AgentOrchestrator → L0b PatternRouter     │
│  → L1 state machines → L2 NeuralRouter (ReAct)                   │
│  JarvisBrain (classifier + context + ProactiveLoop)              │
└─────┬──────────────┬──────────────┬──────────────┬──────────────┘
      │              │              │              │
  Voice OS       Memory/RAG      ToolDispatcher   Inference
  wake+stream    session+long     40+ tools        Ollama / GGUF
```

**Design principles:** event-driven, async worker threads, VRAM budget single-tenant LLM, CPU for STT/TTS/embeddings, modular packages under `edith_app/`.

---

## 2. Folder structure

```
EDITH-AI/
├── main.py, launch_adaptive.py, launch_cloud.py
├── edith_app/
│   ├── app.py                 # Entry / bootstrap
│   ├── assistant.py           # Central orchestrator
│   ├── config.py              # AppConfig + env
│   ├── ui.py                  # ORBIT HUD
│   ├── voice/                 # Wake + streaming intent
│   │   ├── wake_engine.py
│   │   └── streaming_intent.py
│   ├── core/
│   │   ├── agent_orchestrator.py
│   │   ├── jarvis_brain.py
│   │   ├── neural_router.py
│   │   ├── proactive_loop.py
│   │   ├── automation_timing.py
│   │   └── task_engine.py
│   ├── services/              # IO + desktop + voice + LLM
│   └── rag/                   # Chroma + BGE (CPU)
├── models/                    # vosk, kokoro, GGUF
├── data/                      # memory, tasks, telemetry
└── docs/
```

---

## 3. Core system design

| Subsystem | Responsibility |
|-----------|----------------|
| **ORBIT UI** | Voice-first HUD, streaming tokens, system metrics |
| **Voice OS** | openWakeWord + Vosk stream + streaming intent |
| **Brain** | Intent classification, situational context, proactive nudges |
| **NeuralRouter** | LLM ReAct tool loop (primary reasoning) |
| **ToolDispatcher** | Desktop, media, WhatsApp, RAG, tasks |
| **Memory** | JSONL long-term + session + vector RAG |

---

## 4. Agent orchestration

`AgentOrchestrator` maps classifier **lanes** to fast handlers before the full LLM:

| Agent lane | Role |
|------------|------|
| `system` | Volume, open, lock, wifi via pattern router |
| `media` | YouTube / Spotify shortcuts |
| `cowork` | Cowork status/sync |
| `memory` | remember / recall |
| `emotional` | Brief supportive replies (no LLM for short cues) |
| `automation` / `productivity` | Pattern → tool dispatch |
| `chat` | Falls through to NeuralRouter |

**Future:** LangGraph state machine per lane with shared `EventBus` (phase 3).

---

## 5. Memory architecture

| Layer | Store | Use |
|-------|-------|-----|
| Session | `edith_session_memory.json` | Last turns, cowork context |
| Long-term | `edith_memory.jsonl` | Facts, preferences |
| RAG | Chroma + BGE-base (CPU) | Documents, semantic recall |
| Turn cache | in-memory `_rag_cache` | Avoid repeat embed per utterance |

Voice path skips RAG when `EDITH_SKIP_RAG_ON_VOICE=1` (default).

---

## 6. Voice pipeline

```
Mic 16kHz PCM
  → WakeEngine (openWakeWord ONNX | keyword fallback)
  → Vosk partial/final
  → StreamingIntentDetector (stable partial → early command)
  → Confidence gate → handle()
  → Kokoro TTS (clause streaming)
```

**Barge-in:** partials >2 chars → `audio.stop()`.

---

## 7. UI system design

- Frameless ORBIT glass HUD (purple/violet palette)
- Isometric core + **live waveform bars** from mic RMS
- Partial transcript label
- 16ms voice queue poll (ultra-latency)
- Global hotkey `Ctrl+Shift+Space`

**Phase 3 UI:** PyQt6/QML GPU scene graph if Tkinter limits immersion.

---

## 8. Optimization strategy

- `EDITH_ULTRA_LATENCY=1` profile
- Preload Vosk, keep mic stream hot
- 2-step ReAct on voice, 4 on typed
- Clause TTS (not sentence-only)
- `main.py` sets `CUDA_VISIBLE_DEVICES=""` so TTS/STT don't steal 4GB VRAM from LLM

---

## 9. Bottleneck prevention

| Risk | Mitigation |
|------|------------|
| 6× LLM ReAct | Capped steps; pattern router first |
| RAG embed | Skip on voice; cache on typed |
| WhatsApp sleeps | `AutomationTiming` env tunables |
| UI blocking | Commands on worker threads |
| VRAM OOM | One resident LLM; CPU embed/TTS |

---

## 10. Async orchestration

- Voice loop, command `handle()`, TTS synth, bootstrap, proactive loop: **daemon threads**
- UI updates via `root.after()` only
- `_command_idle` Event replaces polling sleeps

---

## 11. GPU / RAM strategy (GTX 1650)

| Component | Placement |
|-----------|-----------|
| LLM (3B Q4) | GPU via llama.cpp or Ollama |
| Vosk STT | CPU |
| Kokoro TTS | CPU ONNX |
| BGE embeddings | CPU |
| openWakeWord | CPU ONNX (~light) |
| Vision | On-demand; long timeout |

Target: **≤3.5GB VRAM** for LLM leaving headroom for desktop.

---

## 12. Local AI integration

- **Default:** Ollama `llama3.2` / `phi3`
- **Best latency:** `launch_adaptive.py` → native GGUF
- **Optional:** `launch_cloud.py` Groq for heavy reasoning only

---

## 13. Plugin / tool architecture

`ToolDispatcher` + `ToolRegistry` (cowork) — add tools by registering JSON actions in manifest and handler map. Future: `edith_app/plugins/*.py` loaded via entry points.

---

## 14. Future scalability

- FastAPI control plane for remote triggers
- Redis task queue for multi-machine
- Separate STT/LLM/TTS processes with shared memory audio ring
- Plugin SDK for user automations

---

## 15. Production deployment

1. `python -m venv .venv` → `pip install -r requirements.txt`
2. Download Vosk + Kokoro models to `models/`
3. `ollama pull llama3.2` or `python launch_adaptive.py`
4. Configure `.env` from `.env.example`
5. `python main.py`

Logs: `data/edith_runtime.log`, runs: `edith_runs/`.

---

## 16. Development roadmap

| Phase | Deliverable |
|-------|-------------|
| **1 (done)** | ORBIT UI, ultra-latency, wake, streaming intent, brain wired |
| **2** | LangGraph agent graphs, emotional tone on TTS |
| **3** | PyQt6/QML HUD, Silero VAD endpoint |
| **4** | Plugin marketplace, multi-user profiles |

---

## 17. Priority implementation phases

1. Voice reliability (wake + streaming) ✅  
2. Tool coverage (desktop automation) — ongoing  
3. Memory quality (RAG ingest)  
4. UI immersion (GPU scene)  
5. Cloud hybrid optional path  

---

## 18. Recommended libraries

| Area | Library |
|------|---------|
| STT | vosk, (optional faster-whisper small) |
| Wake | openwakeword |
| TTS | kokoro-onnx |
| LLM | ollama, llama-cpp-python |
| Vectors | chromadb, sentence-transformers |
| Desktop | pyautogui, pywinauto |
| UI now | tkinter |
| UI next | PyQt6 |

---

## 19. Risk analysis

| Risk | Impact | Mitigation |
|------|--------|------------|
| 4GB VRAM | OOM | Single model, CPU offload |
| Wake false positives | Annoyance | Threshold tuning, keyword fallback |
| WhatsApp UI drift | Broken automation | UIA path + configurable delays |
| openWakeWord download | First-run friction | Lazy init + keyword fallback |

---

## 20. Performance recommendations

- Use `launch_adaptive.py` for lowest LLM jitter  
- Set `EDITH_VOICE_PAUSE_THRESHOLD=0.38` if room is quiet  
- Set `EDITH_NEURAL_MAX_STEPS_VOICE=2` for voice  
- Disable vision unless needed  
- Close Chrome tabs before long cowork sessions  

---

*This document is the canonical systems reference for EDITH OS on your IdeaPad hardware.*
