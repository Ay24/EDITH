# Edith Command Center

Edith is a Windows desktop assistant with a local-first Ollama brain, offline-capable voice input, system automation, persistent memory, coworker-style agent loops, and an immersive Jarvis-style UI.

## What Makes This GitHub Build Different

- Local-first by default: chat, memory, notes, file search, app launching, and system controls keep working without internet.
- Offline speech-ready: if you place a Vosk model in `models/vosk`, Edith uses local speech recognition first.
- Smooth setup: one PowerShell script creates the venv, installs dependencies, and can pull the default Ollama models.
- Safe defaults for any machine: no hardcoded drive assumptions and no personal contacts baked into the repo.
- Coworker mode: Edith can inspect the workspace, build a short plan, run checks, summarize findings, and resume the thread later.
- Persistent task queue: queue, complete, resume, and review cowork tasks across launches.
- Safe edit proposals: Edith can suggest likely files, planned edits, and verification steps before code changes.
- Desktop management: Edith can analyze clutter, infer context from names and document text, organize top-level files into meaningful folders, and move items into target folders.
- Optional local vision sorting: if an Ollama vision model is available, Edith can use actual image descriptions when classifying screenshots, designs, receipts, personal photos, wallpapers, and similar folders.
- Safer organization flow: preview the plan first, detect duplicate or blurry images, then undo the last organization run if needed.

## 5-Minute Windows Setup

1. Install Python 3.11+
2. Install Ollama for Windows
3. From this folder run:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\setup_windows.ps1
```

4. Pull the default local models if you skipped it in setup:

```powershell
ollama pull phi3
ollama pull mistral
ollama pull llama3.2-vision
```

5. For offline speech, extract a Vosk English model into:

```text
models\vosk
```

6. Launch Edith:

```bat
launch_edith.bat
```

After that, Edith can run locally without internet for local chat, local voice, file search, system controls, notes, and memory. Internet is only needed for online services like web search, Wikipedia, YouTube, Spotify, and WhatsApp delivery.

## Local-First Behavior

When internet is unavailable, Edith now stays useful instead of failing noisily:

- Ollama chat still works with already-pulled models
- Voice still works locally when `models/vosk` is present
- Local files, folders, notes, memory, and Windows actions still work
- Web-only actions return a clear offline message instead of a broken response

## Quick Commands

- `system status`
- `cowork on improving startup performance`
- `analyze workspace for voice issues`
- `coding task improve the startup flow and verify the result`
- `propose edit for making offline voice startup faster`
- `browser task compare local voice engines for Windows`
- `queue task tighten the cowork UI`
- `show tasks`
- `next task`
- `complete task tighten the cowork UI`
- `what were we working on`
- `analyze desktop`
- `analyze desktop by context`
- `preview organize desktop by context`
- `organize desktop`
- `organize desktop by context`
- `organize downloads`
- `preview organize folder by context F:\Photos Dump`
- `organize folder by context F:\Photos Dump`
- `undo last organization`
- `analyze downloads by context`
- `move screenshot.png to pictures`
- `analyze folder F:\Temp`
- `open notebooklm`
- `open downloads`
- `find budget in documents`
- `message primary_contact saying this is a test message`
- `set volume to 40`
- `set brightness to 60`
- `wifi off`
- `brainstorm a local-first AI product`
- `plan my study workflow`

## Project Layout

- `main.py`: launcher
- `launch_edith.bat`: one-click local launcher
- `scripts/setup_windows.ps1`: fast Windows setup
- `edith_app/app.py`: bootstrap
- `edith_app/assistant.py`: command routing and orchestration
- `edith_app/core/`: planner, tool registry, verifier, session memory, and coworker loop
- `edith_app/core/task_queue.py`: persistent cowork task management
- `edith_app/services/`: local agent, voice, audio, media, system, memory, notes, and WhatsApp automation
- `edith_app/ui.py`: desktop interface and immersive mode

## Optional Environment Variables

- `OLLAMA_URL`
- `OLLAMA_MODELS`
- `OLLAMA_MODEL`
- `EDITH_PLANNER_MODEL`
- `EDITH_CREATIVE_MODEL`
- `EDITH_FAST_MODEL`
- `EDITH_VISION_MODEL`
- `EDITH_WAKE_WORD`
- `EDITH_AUTO_LISTEN`
- `EDITH_REQUIRE_WAKE_WORD`
- `EDITH_LIGHTWEIGHT_MODE`
- `EDITH_AUTO_PULL_MODELS`
- `EDITH_PREFER_OFFLINE_VOICE`
- `EDITH_VOSK_MODEL_PATH`

## Notes

- Edith tries to start Ollama automatically on launch.
- If a required model is missing and `EDITH_AUTO_PULL_MODELS=1`, Edith will try to pull it.
- If `models/vosk` is missing, Edith falls back to the online speech recognizer when internet is available.
- Context sorting uses file names, folder context, document text where readable, and, when available, a local Ollama vision model for image descriptions. It can also separate likely duplicates and blurry images. It still avoids deleting anything, and the last organization run can be undone.
