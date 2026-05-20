# EDITH ORBIT — Architecture & Competitive Position

## System map

```
Voice (Vosk stream) → Confidence gate → EdithAssistant.handle()
  Layer 0a: smalltalk (0 ms)
  Layer 0b: pattern router + tool dispatch (0 ms)
  Layer 1: pending confirmations (WhatsApp, organize, …)
  Layer 2: NeuralRouter ReAct (1–4 steps typed, 1–2 steps voice)
       → AgentService (Ollama HTTP | llama.cpp native)
       → ToolDispatcher → desktop / media / RAG / tasks
  TTS: Kokoro ONNX (clause streaming, not full-sentence wait)
```

## Ultra-latency profile (`EDITH_ULTRA_LATENCY=1`, default on)

| Stage | Before | ORBIT default |
|-------|--------|---------------|
| End-of-speech | 1.0s pause | 0.42s |
| Voice timeout | 6s | 4s |
| STT LLM normalize | 500ms optional | Off |
| ReAct steps (voice) | 6 | 2 |
| ReAct steps (typed) | 6 | 4 |
| RAG on voice | Always if warranted | Skipped |
| TTS start | After `. ` | After ~14 chars or clause |
| UI voice poll | 100ms | 16ms |
| Processing wait | 150ms sleep | 20ms event wait |

## vs. public JARVIS / FRIDAY projects

| Project | Strength | EDITH ORBIT advantage |
|---------|----------|------------------------|
| isair/jarvis | MCP, memory | Full Windows desktop automation, WhatsApp, cowork tasks |
| InterGenJLU/jarvis | GPU MoE, fine Whisper | Runs on GTX 1650-class hardware; native GGUF path |
| RayP11/Friday | Offline Llama | Deeper tool layer + RAG + vision without cloud |
| projecthub JARVIS | Apple MLX RAG | Windows-first pywinauto + app control |
| thesongzhu/Friday | Approval gates | Voice-first with barge-in + instant pattern router |

## Tuning

Set in `.env` or environment:

- `EDITH_ULTRA_LATENCY=0` — disable fast profile
- `EDITH_NEURAL_MAX_STEPS_VOICE=3` — allow longer voice chains
- `EDITH_VOICE_PAUSE_THRESHOLD=0.35` — snappier end-of-utterance (may clip words)
- `EDITH_PRELOAD_VOSK_MODEL=1` — keep STT hot
- `launch_adaptive.py` — native llama.cpp (lowest LLM jitter vs Ollama HTTP)

## Honest limits

True **zero** latency is impossible (microphone capture, inference, audio playback). ORBIT targets **sub-300ms perceived** on the listen path and **first audible token** while the model still streams.
